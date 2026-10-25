"""Executor and run control API per contracts "Run state machine" and "Run control API"."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from api.executor import run_workflow as ex
from api.models.db import Artifact, ArtifactKind, NodeRun, NodeStatus, Run, RunStatus, Workflow
from api.services import budget
from packages.providers.base import GPUSpec, Pod, Quote

CHAIN = """
name: chain
nodes:
  - id: a
    type: data-prep
    inputs: {dataset: "${{ inputs.dataset }}"}
  - id: b
    type: data-prep
    needs: [a]
    inputs: {dataset: "${{ nodes.a.outputs.train_jsonl }}", format: qa}
  - id: c
    type: data-prep
    needs: [b]
    inputs: {dataset: "${{ nodes.b.outputs.train_jsonl }}"}
"""


class FakeProvider:
    """A node provider. script[node_id] = {"outputs": {...}, "error": "<last ERROR line>", "exit": int | None};
    exit None blocks until the executor cancels the wait."""

    name = "local-docker"

    def __init__(self, db):
        self.db, self.script, self.logs = db, {}, []
        self.envs, self.provisioned, self.terminated, self.granted = {}, [], [], []
        self.started, self.provisioning, self.terminating = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.provision_gate = self.terminate_gate = None  # an asyncio.Event blocks that call until set

    async def provision(self, gpu_spec, image, env):
        self.provisioning.set()
        if self.provision_gate:
            await self.provision_gate.wait()  # docker run still pulling the image
        self.provisioned.append((env["ORCHAPOD_NODE_ID"], image))
        self.granted.append(float(env["ORCHAPOD_MAX_COST_USD"]))
        self.envs[env["ORCHAPOD_NODE_ID"]] = env
        return Pod(provider="local-docker", pod_id=env["ORCHAPOD_NODE_ID"])

    async def quote(self, gpu_spec):
        return Quote(provider=self.name, price_per_hour=4.5, available=True, gpu_type="gpu-h100-sxm")

    async def stream_logs(self, pod):
        for line in self.logs:
            yield line

    async def wait(self, pod):
        self.started.set()
        step = self.script.get(pod.pod_id, {})
        if "outputs" in step or "error" in step:  # what the container's SDK would have posted
            run_id = uuid.UUID(self.envs[pod.pod_id]["ORCHAPOD_RUN_ID"])
            nr = await self.db.scalar(select(NodeRun).where(NodeRun.run_id == run_id, NodeRun.node_id == pod.pod_id))
            nr.outputs = {**(nr.outputs or {}), **step.get("outputs", {})}
            nr.error = step.get("error")
            await self.db.commit()
        if "cost" in step:  # the node's SDK registers its cost_json through /internal/artifact (self.client)
            env = self.envs[pod.pod_id]
            run = Run(id=uuid.UUID(env["ORCHAPOD_RUN_ID"]), user_id=uuid.uuid4())
            body = cost_json(run, pod.pod_id, step["cost"], 1, env["ORCHAPOD_ATTEMPT"])
            assert (await self.client.post("/internal/artifact", json=body)).is_success
        if "during" in step:  # something that lands while the pod runs (an earlier attempt's late flush, say)
            assert (await step["during"]()).is_success
        if "pod_error" in step:  # platform-w5's NebiusProvider: why the job ended, set before wait() returns
            pod.error = step["pod_error"]
        if "exit" in step and step["exit"] is None:
            await asyncio.Event().wait()
        return step.get("exit", 0)

    async def terminate(self, pod):
        self.terminating.set()
        if self.terminate_gate:
            await self.terminate_gate.wait()  # inside the 30 s SIGTERM grace
        self.terminated.append(pod.pod_id)


@pytest.fixture
def provider(db, monkeypatch):
    p = FakeProvider(db)

    async def local(resources):
        return p, None

    async def no_gpu(resources):
        raise RuntimeError("NEBIUS_PROJECT_ID not set")

    monkeypatch.setattr("api.services.provider_selector.pick_local_docker", local)
    monkeypatch.setattr("api.services.provider_selector.pick_provider", no_gpu)
    return p


@pytest.fixture
def gpu(provider, db, monkeypatch):
    """The GPU provider gpu nodes land on (Nebius, an H100 at $4.50 an hour); cpu and api nodes stay on `provider`."""
    p = FakeProvider(db)
    p.name = "nebius"

    async def pick(resources):
        return p, GPUSpec(gpu_type="H100")

    monkeypatch.setattr("api.services.provider_selector.pick_provider", pick)
    # a gpu pod's bill has a session of its own, on the test's database (never the module's engine)
    monkeypatch.setattr("api.database.AsyncSessionLocal", async_sessionmaker(db.bind, class_=AsyncSession,
                                                                             expire_on_commit=False))
    return p


@pytest.fixture
def nebius_cli(tmp_path, monkeypatch):
    """`nebius` on the API host's PATH: `iam get-access-token` prints a token; `calls` lists each run's arguments."""
    cli = tmp_path / "bin" / "nebius"
    cli.parent.mkdir()
    cli.write_text(f'#!/bin/sh\necho "$@" >> {tmp_path / "calls"}\necho "Note: a newer CLI is out"\necho " iam-token-1 "\n')
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", f"{cli.parent}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("NEBIUS_IAM_TOKEN", raising=False)  # hosted: blank, so the CLI signs one
    monkeypatch.delenv("STUB", raising=False)
    return SimpleNamespace(path=cli, calls=tmp_path / "calls")


@pytest.fixture
def docker_cli(tmp_path, monkeypatch):
    """`docker` on the API host's PATH, so no test reaches the real daemon (other APIs' and projects' containers): `ps`
    prints the lines of `listing`; every call's arguments are appended to `calls`."""
    cli, listing, calls = tmp_path / "bin" / "docker", tmp_path / "ps", tmp_path / "docker-calls"
    cli.parent.mkdir(exist_ok=True)
    listing.write_text("")
    cli.write_text(f'#!/bin/sh\necho "$@" >> {calls}\nif [ "$1" = ps ]; then cat {listing}; fi\n')
    cli.chmod(0o755)
    monkeypatch.setenv("PATH", f"{cli.parent}{os.pathsep}{os.environ['PATH']}")
    return SimpleNamespace(path=cli, listing=listing, calls=calls)


EVERY_RUNTIME = """
name: g
nodes:
  - {id: prep, type: data-prep, inputs: {dataset: "hf://x"}}
  - {id: finetune, type: tf-finetune, needs: [prep], inputs: {train_data: "r2://b/train"}}
  - {id: serve, type: vllm-serve, needs: [finetune], inputs: {model: m}}
  - {id: train, type: unsloth-train, needs: [serve], inputs: {train_data: "r2://b/train"}}
"""


@pytest.fixture
def endpoint_node(monkeypatch):
    """vllm-serve as ml-w4 registers it: an api node (LocalDocker) whose container creates a Nebius endpoint."""
    from packages.workflow_schema.models import NODE_REGISTRY, NodeType
    monkeypatch.setitem(NODE_REGISTRY[NodeType.VLLM_SERVE], "runtime", "api")
    monkeypatch.setitem(NODE_REGISTRY[NodeType.VLLM_SERVE], "rents_gpu", True)


async def seed(db, yaml=CHAIN, inputs=None, status=RunStatus.PROVISIONING_GPU, **run_fields):
    wf = Workflow(user_id=uuid.uuid4(), name="t", yaml=yaml, graph_json={})
    db.add(wf)
    await db.flush()
    run = Run(workflow_id=wf.id, user_id=wf.user_id, inputs=inputs or {"dataset": "hf://x"}, status=status, **run_fields)
    db.add(run)
    await db.commit()
    return run


async def nodes(db, run):
    rows = (await db.scalars(select(NodeRun).where(NodeRun.run_id == run.id))).all()
    for n in rows:
        await db.refresh(n)
    return {n.node_id: n for n in rows}


def events(broadcast):
    return [c.args[1] for c in broadcast.await_args_list]


async def drain():
    """Wait for background provisions and pod terminations."""
    while ex._inflight:
        await asyncio.wait(set().union(*ex._inflight.values()))


async def test_success_resolves_refs_and_records_lineage(db, provider, monkeypatch):
    monkeypatch.delenv("ORCHAPOD_IMAGE_PREFIX", raising=False)
    provider.script = {"a": {"outputs": {"train_jsonl": "r2://bk/runs/r/a/train_jsonl"}},
                       "b": {"outputs": {"train_jsonl": "r2://bk/runs/r/b/train_jsonl"}}}
    run = await seed(db)
    broadcast = AsyncMock()

    await ex.run_workflow(run.id, db, broadcast, 1.0)

    await db.refresh(run)
    rows = await nodes(db, run)
    assert run.status == RunStatus.SUCCEEDED
    assert {n.status for n in rows.values()} == {NodeStatus.SUCCEEDED}
    assert rows["b"].inputs == {"dataset": "r2://bk/runs/r/a/train_jsonl", "format": "qa"}  # resolved lineage
    assert json.loads(provider.envs["a"]["ORCHAPOD_NODE_INPUTS"]) == {"dataset": "hf://x"}
    assert (rows["b"].gpu_provider, rows["b"].gpu_pod_id) == ("local-docker", "b")
    assert provider.provisioned == [(n, "ghcr.io/bangadpurva/data-prep:latest") for n in "abc"]
    assert provider.terminated == ["a", "b", "c"]
    assert {"type": "node_status", "node_id": "a", "status": "succeeded",
            "outputs": {"train_jsonl": "r2://bk/runs/r/a/train_jsonl"}} in events(broadcast)
    assert events(broadcast)[-1] == {"type": "run_status", "status": "succeeded"}


async def test_failed_node_fails_run_with_last_error_line(db, provider):
    provider.script = {"a": {"outputs": {"train_jsonl": "r2://bk/a"}}, "b": {"exit": 3, "error": "0 rows after cleaning"}}
    run = await seed(db)
    broadcast = AsyncMock()

    await ex.run_workflow(run.id, db, broadcast, 1.0)

    await db.refresh(run)
    rows = await nodes(db, run)
    assert run.status == RunStatus.FAILED
    assert [rows[i].status for i in "abc"] == [NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.PENDING]
    assert rows["b"].error == "exit 3: 0 rows after cleaning"
    assert events(broadcast)[-2:] == [
        {"type": "node_status", "node_id": "b", "status": "failed", "error": "exit 3: 0 rows after cleaning"},
        {"type": "run_status", "status": "failed", "error": "exit 3: 0 rows after cleaning"},
    ]


async def test_unresolved_ref_fails_the_node_before_provisioning(db, provider):
    run = await seed(db)  # a writes no train_jsonl

    await ex.run_workflow(run.id, db, AsyncMock(), 1.0)

    rows = await nodes(db, run)
    assert rows["b"].status == NodeStatus.FAILED
    assert rows["b"].error == "unresolved ref ${{ nodes.a.outputs.train_jsonl }}"
    assert [n for n, _ in provider.provisioned] == ["a"]


async def test_api_runtime_runs_on_local_docker_and_gpu_needs_a_provider(db, provider, monkeypatch):
    from packages.workflow_schema.models import NODE_REGISTRY, NodeType
    monkeypatch.setitem(NODE_REGISTRY[NodeType.DATA_PREP], "runtime", "api")
    provider.script = {"a": {"outputs": {"train_jsonl": "r2://bk/a"}}, "b": {"outputs": {"train_jsonl": "r2://bk/b"}}}
    run = await seed(db)
    await ex.run_workflow(run.id, db, AsyncMock(), 1.0)
    await db.refresh(run)
    assert run.status == RunStatus.SUCCEEDED

    gpu = await seed(db, yaml="name: g\nnodes:\n  - id: t\n    type: unsloth-train\n    inputs: {model: m}\n")
    await ex.run_workflow(gpu.id, db, AsyncMock(), 1.0)
    rows = await nodes(db, gpu)
    assert rows["t"].error == "no gpu provider: NEBIUS_PROJECT_ID not set"


async def test_timeout_terminates_the_pod(db, provider, monkeypatch):
    monkeypatch.setenv("ORCHAPOD_NODE_TIMEOUT_S", "0.05")
    provider.script = {"a": {"exit": None}}
    run = await seed(db)

    await asyncio.wait_for(ex.run_workflow(run.id, db, AsyncMock(), 1.0), 5)

    rows = await nodes(db, run)
    assert rows["a"].error == "timeout after 0.05 s"
    assert provider.terminated == ["a"]


async def test_container_stdout_becomes_log_events(db, provider):
    provider.logs = ["[2026-10-20T10:00:00+00:00] [INFO] already posted by the SDK", "pip noise"]
    provider.script = {"a": {"exit": 1}}
    run = await seed(db)
    broadcast = AsyncMock()

    await ex.run_workflow(run.id, db, broadcast, 1.0)

    logs = [e for e in events(broadcast) if e["type"] == "log"]
    assert [(e["node_id"], e["level"], e["message"]) for e in logs] == [("a", "STDOUT", "pip noise")]
    assert logs[0]["ts"]


async def test_build_env_forwards_exactly_the_contract_vars(db, monkeypatch):
    from api.routes.internal import INTERNAL_SECRET
    for k in ("NEBIUS_BASE_URL", "ORCHAPOD_R2_REGION", "ORCHAPOD_CONTROL_URL", "STUB"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-y")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-z")
    monkeypatch.setenv("NEBIUS_IAM_TOKEN", "iam-x")  # only a node that rents a GPU gets one (test below)
    nr = NodeRun(run_id=uuid.uuid4(), node_id="train", node_type="unsloth-train", inputs={"model": "m"},
                 outputs={"checkpoint_step_000100": "r2://b/100", "checkpoint_step_000200": "r2://b/200"})

    env = ex._build_env(nr, 1.25)

    assert set(env) == {
        "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "TAVILY_API_KEY", "HF_TOKEN", "NEBIUS_PROJECT_ID",
        "ORCHAPOD_ENDPOINT_TOKEN", "ORCHAPOD_R2_ENDPOINT", "ORCHAPOD_R2_REGION", "ORCHAPOD_R2_ACCESS_KEY",
        "ORCHAPOD_R2_SECRET_KEY", "ORCHAPOD_R2_BUCKET", "ORCHAPOD_CONTROL_URL", "ORCHAPOD_INTERNAL_SECRET",
        "ORCHAPOD_MAX_COST_USD", "STUB", "ORCHAPOD_NODE_INPUTS", "ORCHAPOD_NODE_OUTPUTS_DIR", "ORCHAPOD_RUN_ID",
        "ORCHAPOD_NODE_ID", "ORCHAPOD_RESUME_CHECKPOINT_URI", "ORCHAPOD_ATTEMPT",
    }
    assert env["TAVILY_API_KEY"] == "tvly-z"
    assert env["NEBIUS_BASE_URL"] == "https://api.tokenfactory.nebius.com/v1"
    assert (env["ORCHAPOD_R2_REGION"], env["ORCHAPOD_CONTROL_URL"]) == ("auto", "http://localhost:8001")
    assert env["ORCHAPOD_INTERNAL_SECRET"] == INTERNAL_SECRET and INTERNAL_SECRET
    assert env["ORCHAPOD_MAX_COST_USD"] == "1.2500"
    assert env["ORCHAPOD_RESUME_CHECKPOINT_URI"] == "r2://b/200"  # retry reuses the row: newest checkpoint


async def test_only_an_api_node_that_creates_endpoints_gets_a_fresh_iam_token(db, provider, gpu, nebius_cli,
                                                                              endpoint_node, caplog, monkeypatch):
    """The API host's nebius CLI signs a token at each start of vllm-serve (rents_gpu, api), whose container creates the
    endpoint (the hosted VM sets no NEBIUS_IAM_TOKEN, and node images have no CLI). No other node gets one: not cpu or
    api nodes, and not gpu nodes, which run third-party model code as Nebius Jobs; nor does any log, input or meta."""
    run = await seed(db, EVERY_RUNTIME)

    await ex.run_workflow(run.id, db, AsyncMock(), 1.0)

    assert provider.envs["serve"]["NEBIUS_IAM_TOKEN"] == "iam-token-1"
    assert [n for n, env in {**provider.envs, **gpu.envs}.items() if "NEBIUS_IAM_TOKEN" in env] == ["serve"]
    assert set(gpu.envs) == {"train"} and set(provider.envs) == {"prep", "finetune", "serve"}  # every runtime ran
    assert nebius_cli.calls.read_text() == "iam get-access-token\n"  # once per start of vllm-serve
    rows = await nodes(db, run)
    assert "iam-token-1" not in caplog.text + json.dumps([r.inputs for r in rows.values()])

    monkeypatch.setenv("NEBIUS_IAM_TOKEN", "iam-set")  # a fresh token from the CLI beats a static one, which may be stale
    again = await seed(db, EVERY_RUNTIME)
    await ex.run_workflow(again.id, db, AsyncMock(), 1.0)
    assert provider.envs["serve"]["NEBIUS_IAM_TOKEN"] == "iam-token-1"
    assert nebius_cli.calls.read_text() == "iam get-access-token\n" * 2
    nebius_cli.path.unlink()  # a host without the CLI uses the static token
    last = await seed(db, EVERY_RUNTIME)
    await ex.run_workflow(last.id, db, AsyncMock(), 1.0)
    assert [(n, env["NEBIUS_IAM_TOKEN"]) for n, env in {**provider.envs, **gpu.envs}.items()
            if "NEBIUS_IAM_TOKEN" in env] == [("serve", "iam-set")]


SERVE_ONLY = "name: s\nnodes:\n  - {id: serve, type: vllm-serve, inputs: {model: m}}\n"


@pytest.mark.parametrize("cli, timeout, error", [
    (None, None, "no Nebius IAM token: the API host has no nebius CLI, and NEBIUS_IAM_TOKEN is blank or malformed"),
    # stderr can name profiles, tenants, projects or a federation URL, and node errors are public: never shown
    ('echo "profile /home/sa/.nebius tenant-e00secret" >&2\nexit 3', None,
     "no Nebius IAM token: nebius iam get-access-token exited 3"),
    ('echo "token: x"\necho "Warning: rotate soon"', None, "no Nebius IAM token: nebius iam get-access-token printed no token"),
    ("exec sleep 5", 0, "no Nebius IAM token: nebius iam get-access-token took over 0 s"),
])
async def test_an_endpoint_node_without_a_token_fails_before_it_starts(db, provider, nebius_cli, endpoint_node,
                                                                       monkeypatch, cli, timeout, error):
    """No wall clock decides a case: a CLI that exits is waited for without a timer (one of 0.2 s lost to a loaded
    machine's process start), and the hung one meets a timeout of 0, which asyncio.wait_for raises at once."""
    monkeypatch.setattr(ex, "IAM_TIMEOUT_S", timeout)
    if cli is None:
        nebius_cli.path.unlink()
    else:
        nebius_cli.path.write_text(f"#!/bin/sh\n{cli}\n")
    run = await seed(db, SERVE_ONLY)

    await ex.run_workflow(run.id, db, AsyncMock(), 1.0)

    assert ((await nodes(db, run))["serve"].error, provider.provisioned) == (error, [])
    monkeypatch.setenv("STUB", "1")  # STUB never creates a Nebius resource, so it needs no token
    stub = await seed(db, SERVE_ONLY)
    await ex.run_workflow(stub.id, db, AsyncMock(), 1.0)
    assert (await nodes(db, stub))["serve"].status == NodeStatus.SUCCEEDED


async def test_why_the_provider_ended_a_pod_is_the_node_error(db, provider, gpu):
    """A Nebius job that never ran its container (no capacity, preempted) ends with no ERROR line from the node: the
    provider's reason says more than "exit 1". A node's own last ERROR line still wins."""
    one = "name: t\nnodes:\n  - {id: train, type: unsloth-train, inputs: {train_data: r2://b/t}}\n"
    reason = "FAILED NotEnoughResources: no gpu-h100-sxm capacity within 30 min"
    gpu.script = {"train": {"exit": 1, "pod_error": reason}}
    capacity = await seed(db, one)
    await ex.run_workflow(capacity.id, db, AsyncMock(), 1.0)
    assert (await nodes(db, capacity))["train"].error == reason

    gpu.script = {"train": {"exit": 1, "pod_error": "FAILED ContainerFailed: exit 1", "error": "CUDA out of memory"}}
    oom = await seed(db, one)
    await ex.run_workflow(oom.id, db, AsyncMock(), 1.0)
    assert (await nodes(db, oom))["train"].error == "exit 1: CUDA out of memory"


ONE_GPU = "name: t\nnodes:\n  - {id: train, type: unsloth-train, inputs: {train_data: r2://b/t}}\n"


def cost_json(run, node_id: str, usd: float, seq: int, attempt: str | None = None) -> dict:
    """POST /internal/artifact's body for a node's cost_json, as the SDK sends it (it echoes ORCHAPOD_ATTEMPT)."""
    return {"run_id": str(run.id), "node_id": node_id, "artifact": {
        "name": "cost_json", "uri": f"r2://bk/runs/x/{node_id}/cost_json", "kind": "metrics",
        "metadata": {"usd": usd, "seq": seq, **({"attempt": attempt} if attempt else {})}}}


async def test_a_gpu_attempt_costs_its_wall_time_or_what_its_node_reported_whichever_is_more(client, db, provider, gpu,
                                                                                            monkeypatch):
    """Once a gpu pod is gone the executor bills its wall time (H100, 30 min: $2.25). A Nebius job's SIGTERM flush usually
    lands later (terminate returns once cancel and delete are acknowledged), and a node may also report first. Either
    way the attempt totals max(the bill, what the node reported), and the summary agrees with Run.cost_usd."""
    clock = [0.0]
    monkeypatch.setattr(ex, "monotonic", lambda: clock.append(clock[-1] + 1800) or clock[-1])  # 30 min a pod
    gpu.client = client

    async def cost(run):
        await db.refresh(run)
        return float(run.cost_usd), (await client.get(f"/runs/{run.id}/summary")).json()["nodes"][0]["usd"]

    gpu.script = {"train": {"exit": 1, "pod_error": "FAILED Preempted: the VM was reclaimed"}}
    killed, broadcast = await seed(db, ONE_GPU), AsyncMock()
    await ex.run_workflow(killed.id, db, broadcast, 1.0)
    bill = await db.scalar(select(Artifact).where(Artifact.name == "cost_json"))
    assert (bill.meta, bill.uri) == ({"usd": 2.25, "wall_usd": 2.25, "gpu_hours": 0.5, "billed_by": "executor",
                                      "attempt": gpu.envs["train"]["ORCHAPOD_ATTEMPT"]}, "nebius:train")
    assert await cost(killed) == (2.25, 2.25) and {"type": "run_cost", "cost_usd": 2.25} in events(broadcast)
    for usd, seq, total in ((1.0, 1, 2.25), (2.0, 2, 3.0),  # late flushes add only what the node reported beyond the bill
                            (2.0, 2, 3.0),                   # a re-send of seq 2 (its POST broke after it landed): once
                            (2.5, 2, 3.5)):                  # seq 2 sent again with more spend: only the difference
        r = await client.post("/internal/artifact", json=cost_json(killed, "train", usd, seq))
        assert (r.status_code, await cost(killed)) == (201, (total, total))
    rows = (await db.scalars(select(Artifact).where(Artifact.name == "cost_json"))).all()
    assert len(rows) == 4  # the bill and three reports: the re-send of seq 2 is not stored
    for posing in ({"usd": -1.0}, {"usd": 0.0, "seq": 4, "billed_by": "executor", "wall_usd": 0.0}):
        body = cost_json(killed, "train", 0, 0)
        body["artifact"]["metadata"] = posing  # a node (gpu Jobs run third-party code) lowering its cost, or posing as the bill
        await client.post("/internal/artifact", json=body)
    assert await cost(killed) == (3.5, 3.5)
    assert [a.meta.get("billed_by") for a in await db.scalars(select(Artifact).where(Artifact.name == "cost_json"))
            ].count("executor") == 1

    gpu.script = {"train": {"exit": None}}  # a long training job, then Cancel
    gpu.started.clear()
    cancelled = await seed(db, ONE_GPU)
    task = asyncio.create_task(ex.run_workflow(cancelled.id, db, AsyncMock(), 1.0))
    await asyncio.wait_for(gpu.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await cost(cancelled), (await nodes(db, cancelled))["train"].error) == ((2.25, 2.25), "cancelled")

    gpu.script = {"train": {"exit": 1, "cost": 0.4}}  # the node reports first (it may stop at its budget, say)
    early = await seed(db, ONE_GPU)
    await ex.run_workflow(early.id, db, AsyncMock(), 1.0)
    assert await cost(early) == (2.25, 2.25)  # the bill adds only $1.85 above the node's $0.40

    gpu.script = {"train": {"exit": 1}}  # Retry node: the first attempt's cost_json does not cover the second
    await ex.run_workflow(early.id, db, AsyncMock(), 1.0)
    assert await cost(early) == (4.5, 4.5)


@pytest.mark.parametrize("stub, placed, usd", [(None, {"local-docker": 0, "nebius": 1}, 2.25),
                                               ("1", {"local-docker": 1, "nebius": 0}, 0.0)])
async def test_stub_runs_a_gpu_node_on_local_docker_and_bills_nothing(db, provider, gpu, monkeypatch, stub, placed, usd):
    """Under STUB no node touches a GPU (unsloth-train writes a fake adapter), so a gpu node runs on LocalDocker like a cpu
    node and its wall time is not billed. Without STUB it lands on the GPU provider and bills its 30 min of H100, as before."""
    monkeypatch.delenv("STUB", raising=False)
    if stub:
        monkeypatch.setenv("STUB", stub)
    clock = [0.0]
    monkeypatch.setattr(ex, "monotonic", lambda: clock.append(clock[-1] + 1800) or clock[-1])  # 30 min a pod
    run = await seed(db, ONE_GPU)

    await ex.run_workflow(run.id, db, AsyncMock(), 1.0)

    await db.refresh(run)
    assert run.status == RunStatus.SUCCEEDED
    assert ({p.name: len(p.provisioned) for p in (provider, gpu)}, float(run.cost_usd or 0)) == (placed, usd)


async def test_a_cost_json_racing_the_executors_bill_is_counted_once(client, provider, gpu, tmp_path, monkeypatch):
    """The node's flush lands while the executor bills, between its read of the attempt and its insert: one lock
    orders them, so the attempt still totals max(the bill, the report), not their sum. A file database gives each
    session its own connection, as production has (the in-memory one shares one connection between all of them)."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel import SQLModel
    from api.database import get_session
    from api.main import app
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def per_request():  # its own session, as in production: never the executor's
        async with sessions() as session:
            yield session
            await session.commit()

    app.dependency_overrides[get_session] = per_request
    monkeypatch.setattr("api.database.AsyncSessionLocal", sessions)  # the bill's own session
    monkeypatch.setattr(ex, "monotonic", lambda: 0.0 if not gpu.provisioned else 1800.0)
    gpu.script = {"train": {"exit": 1}}
    read, landed = budget.attempt_costs, []

    async def racing(*args):
        if not landed:  # the executor's read: the node's POST arrives now
            landed.append(asyncio.create_task(client.post("/internal/artifact", json=cost_json(run, "train", 1.0, 1))))
            for _ in range(20):
                await asyncio.sleep(0)  # let the POST run as far as it can (to the lock, or into the database)
        return await read(*args)

    monkeypatch.setattr(budget, "attempt_costs", racing)
    try:
        async with sessions() as db:
            run = await seed(db, ONE_GPU)
            await ex.run_workflow(run.id, db, AsyncMock(), 1.0)
            assert (await landed[0]).status_code == 201
            await db.refresh(run)
            assert float(run.cost_usd) == 2.25  # max($2.25 billed, $1.00 reported)
    finally:
        await engine.dispose()


async def test_an_attempts_reports_add_up_to_at_most_twice_the_run_cap(client, db, seeded_node_run):
    """Three $6 reports under new seqs once put $18 on one run: an attempt's reported total is capped at 2 x $3."""
    run, _ = seeded_node_run
    for usd, seq, status in ((4.0, 1, 201), (2.0, 2, 201), (0.01, 3, 422), (2.0, 2, 201)):  # the last: a re-send
        assert (await client.post("/internal/artifact", json=cost_json(run, "node", usd, seq))).status_code == status
    await db.refresh(run)
    assert float(run.cost_usd) == 6.0


async def test_a_late_flush_counts_toward_its_own_attempt_after_a_quick_retry(client, db, provider, gpu, monkeypatch):
    """Arrival time used to split the attempts, so attempt 1's flush landing after Retry had started attempt 2 was
    reconciled against attempt 2. The SDK echoes ORCHAPOD_ATTEMPT, so it counts toward its own attempt."""
    clock = iter([0.0, 1800.0, 0.0, 3600.0])  # attempt 1: 30 min, $2.25; attempt 2: 60 min, $4.50
    monkeypatch.setattr(ex, "monotonic", lambda: next(clock))
    gpu.client, gpu.script = client, {"train": {"exit": 1}}
    run = await seed(db, ONE_GPU)
    await ex.run_workflow(run.id, db, AsyncMock(), 1.0)
    first = gpu.envs["train"]["ORCHAPOD_ATTEMPT"]
    late = cost_json(run, "train", 3.0, 1, first)  # attempt 1 reported more than its bill (Token Factory calls, say)

    gpu.script = {"train": {"exit": 1, "during": lambda: client.post("/internal/artifact", json=late)}}
    await ex.run_workflow(run.id, db, AsyncMock(), 1.0)  # Retry node: attempt 2, while attempt 1's flush lands

    await db.refresh(run)
    assert (gpu.envs["train"]["ORCHAPOD_ATTEMPT"] != first, float(run.cost_usd)) == (True, 7.5)  # $3.00 + $4.50


GPU_THEN_CPU = """
name: g
nodes:
  - {id: train, type: unsloth-train, inputs: {train_data: "r2://b/t"}}
  - {id: prep, type: data-prep, needs: [train], inputs: {dataset: "hf://x"}}
"""


async def test_a_failed_bill_never_strands_the_run(db, provider, gpu, monkeypatch, caplog):
    """The bill has its own session: when it fails, the executor's session (its run and NodeRuns) is untouched, so the
    run goes on to its next node instead of stopping RUNNING."""
    def blip(*_):  # after the bill's first query, so its transaction has begun
        raise RuntimeError("database blip")

    monkeypatch.setattr(budget, "attempt_cost", blip)
    run = await seed(db, GPU_THEN_CPU)

    await ex.run_workflow(run.id, db, AsyncMock(), 1.0)

    await db.refresh(run)
    rows = await nodes(db, run)
    assert (run.status, rows["train"].status, rows["prep"].status) == (RunStatus.SUCCEEDED,) + (NodeStatus.SUCCEEDED,) * 2
    assert "gpu time of nebius train not billed" in caplog.text


async def test_a_second_cancel_in_the_grace_still_bills_the_gpu_pod(db, provider, gpu, monkeypatch):
    """The bill is part of the shielded teardown task: a second click on Cancel inside the 30 s SIGTERM grace stops the
    executor waiting, never the teardown or the bill."""
    clock = [0.0]
    monkeypatch.setattr(ex, "monotonic", lambda: clock.append(clock[-1] + 1800) or clock[-1])  # 30 min: $2.25
    gpu.script, gpu.terminate_gate = {"train": {"exit": None}}, asyncio.Event()
    run = await seed(db, ONE_GPU)
    task = asyncio.create_task(ex.run_workflow(run.id, db, AsyncMock(), 1.0))
    await asyncio.wait_for(gpu.started.wait(), 5)

    task.cancel()
    await asyncio.wait_for(gpu.terminating.wait(), 5)  # SIGTERM sent, grace running
    task.cancel()                                      # a second click
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    gpu.terminate_gate.set()
    await drain()

    await db.refresh(run)
    assert run.cost_usd == Decimal("2.25")


async def test_one_node_run_per_run_and_node(db):
    run = await seed(db)
    db.add(NodeRun(run_id=run.id, node_id="a", node_type="data-prep"))
    db.add(NodeRun(run_id=run.id, node_id="a", node_type="data-prep"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_startup_sweep_fails_orphaned_runs(db, provider, docker_cli):
    run = await seed(db, status=RunStatus.RUNNING)
    for node_id, status, pod in [("a", NodeStatus.SUCCEEDED, None), ("b", NodeStatus.RUNNING, "b"), ("c", NodeStatus.PENDING, None)]:
        db.add(NodeRun(run_id=run.id, node_id=node_id, node_type="data-prep", status=status,
                       gpu_provider=pod and "local-docker", gpu_pod_id=pod))
    between = await seed(db, status=RunStatus.RUNNING)  # stopped between nodes: a succeeded, b not started
    db.add(NodeRun(run_id=between.id, node_id="a", node_type="data-prep", status=NodeStatus.SUCCEEDED))
    db.add(NodeRun(run_id=between.id, node_id="b", node_type="data-prep"))
    done = await seed(db, status=RunStatus.SUCCEEDED)
    stale = await seed(db, yaml="name: s\nnodes:\n  - id: x\n    type: retired-node\n", status=RunStatus.RUNNING)
    await db.commit()

    await ex.sweep(db)  # a workflow that no longer compiles must not stop the API from starting
    assert provider.terminated == []  # terminations run after startup, once the API can take the nodes' last posts
    await drain()

    for r in (run, between, done, stale):
        await db.refresh(r)
    assert (run.status, between.status, done.status, stale.status) == (
        RunStatus.FAILED, RunStatus.FAILED, RunStatus.SUCCEEDED, RunStatus.FAILED)
    rows, rows2 = await nodes(db, run), await nodes(db, between)
    assert [rows[i].status for i in "abc"] == [NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.PENDING]
    assert rows["b"].error == rows2["b"].error == "control plane restarted"
    assert provider.terminated == ["b"]


async def test_the_startup_sweep_stops_this_apis_containers_of_runs_that_are_over_or_unknown(db, docker_cli, monkeypatch):
    """A teardown in flight dies with the API (qa-w6: a cancel mid-provision, then a shutdown), and a stub e2e's database is
    thrown away. Only containers LocalDocker labelled for this API are touched: never another project's, nor those of
    another API on this host (its runs are unknown here)."""
    monkeypatch.setenv("ORCHAPOD_CONTROL_URL", "http://localhost:8002")
    mid, over, waiting = [await seed(db, status=s) for s in (RunStatus.RUNNING, RunStatus.CANCELLED, RunStatus.PENDING)]
    db.add(NodeRun(run_id=mid.id, node_id="a", node_type="data-prep", status=NodeStatus.RUNNING,
                   gpu_provider="local-docker", gpu_pod_id="c-recorded"))
    await db.commit()
    unknown, ours, other_api = uuid.uuid4(), "http://localhost:8002", "http://127.0.0.1:8003"
    docker_cli.listing.write_text("".join(f"{cid}\t{run_id}\t{url}\n" for cid, run_id, url in [
        ("c-recorded", mid.id, ours),     # the running node's pod: terminated once, by the sweep's first half
        ("c-over", over.id, ours),        # cancelled mid-provision, then the API stopped
        ("c-unknown", unknown, ours),     # a run this database never had
        ("c-waiting", waiting.id, ours),  # a run that is neither over nor unknown
        ("c-other-api", unknown, other_api),
        ("c-unlabelled", "", ""),         # what docker prints for a container without the labels
    ]))

    await ex.sweep(db)
    await drain()

    calls = docker_cli.calls.read_text().splitlines()
    assert [c.split(" ")[:5] for c in calls if c.startswith("ps ")] == [["ps", "-a", "--no-trunc", "--filter",
                                                                         "label=orchapod.run_id"]]
    assert sorted(c for c in calls if not c.startswith("ps ")) == sorted(
        f"{verb} {cid}" for cid in ("c-recorded", "c-over", "c-unknown") for verb in ("stop -t 30", "rm -f"))


async def test_a_docker_that_hangs_never_holds_up_the_api_start(db, provider, docker_cli, monkeypatch, caplog):
    docker_cli.path.write_text("#!/bin/sh\nexec sleep 5\n")  # Docker Desktop half up
    monkeypatch.setattr(ex, "DOCKER_PS_TIMEOUT_S", 0.2)
    run = await seed(db, status=RunStatus.RUNNING)

    await asyncio.wait_for(ex.sweep(db), 3)

    await db.refresh(run)
    assert run.status == RunStatus.FAILED and "docker ps took over 0.2 s" in caplog.text


async def test_startup_runs_the_sweep_and_creates_the_bucket(monkeypatch):
    import threading
    from api import main
    swept, resumed, bucket = AsyncMock(), AsyncMock(), threading.Event()
    monkeypatch.setattr(main, "sweep", swept)
    monkeypatch.setattr(main.internal, "resume_ttls", resumed)  # endpoint expiries (tests/api/test_internal.py)
    monkeypatch.setattr(main, "create_tables", AsyncMock())
    monkeypatch.setattr(main, "register_providers", lambda **_: None)
    monkeypatch.setattr(main.storage, "ensure_bucket_exists", bucket.set)  # MinIO in dev starts without the bucket
    monkeypatch.setattr(main.event_bus, "connect", AsyncMock())
    monkeypatch.setattr(main.event_bus, "disconnect", AsyncMock())

    async with main.lifespan(main.app):
        pass

    swept.assert_awaited_once()
    resumed.assert_awaited_once()
    assert await asyncio.to_thread(bucket.wait, 5)  # off the event loop: a slow store never delays startup


async def test_cancel_during_provision_terminates_the_pod_once_it_exists(db, provider):
    provider.provision_gate = asyncio.Event()
    run = await seed(db)
    task = asyncio.create_task(ex.run_workflow(run.id, db, AsyncMock(), 1.0))
    await asyncio.wait_for(provider.provisioning.wait(), 5)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert run.id in budget._granted  # the container may still come up and spend: its grant stays
    provider.provision_gate.set()  # the container comes up after the cancel
    await asyncio.wait_for(provider.terminating.wait(), 5)
    await drain()

    assert provider.terminated == ["a"] and run.id not in budget._granted
    rows = await nodes(db, run)
    assert (rows["a"].status, rows["a"].error) == (NodeStatus.FAILED, "cancelled")
    assert rows["a"].inputs == {"dataset": "hf://x"}  # resolved: stored with running, so the cancel's rollback keeps it


async def test_a_second_cancel_cannot_interrupt_teardown(db, provider):
    provider.script = {"a": {"exit": None}}
    provider.terminate_gate = asyncio.Event()
    run = await seed(db)
    task = asyncio.create_task(ex.run_workflow(run.id, db, AsyncMock(), 1.0))
    await asyncio.wait_for(provider.started.wait(), 5)

    task.cancel()
    await asyncio.wait_for(provider.terminating.wait(), 5)  # SIGTERM sent, grace running
    task.cancel()                                            # a second click on Cancel
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert ex.busy(run.id)                                   # the executor is gone, the teardown is not
    assert run.id in budget._granted                         # and the node may still spend in its grace
    provider.terminate_gate.set()
    await drain()

    assert provider.terminated == ["a"] and not ex.busy(run.id) and run.id not in budget._granted
    rows = await nodes(db, run)
    assert (rows["a"].status, rows["a"].error) == (NodeStatus.FAILED, "cancelled")


@pytest.fixture
async def sqlite_file(tmp_path):
    """An engine on a SQLite file, a connection per session as in dev and the stub e2e, set up as the API sets up its own; a
    0.5 s busy timeout (5 s in the API) keeps a lock failure quick."""
    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel import SQLModel
    from api import database

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}", connect_args={"timeout": 0.5})
    event.listen(engine.sync_engine, "connect", database.sqlite_wal)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    await engine.dispose()


A_CANCELLED = {"a": (NodeStatus.FAILED, "cancelled"), "b": (NodeStatus.PENDING, None), "c": (NodeStatus.PENDING, None)}


@pytest.mark.parametrize("statement, reading, left", [
    ("sum(run.cost_usd)", False, A_CANCELLED),  # qa-w6: the budget check's read
    ("sum(run.cost_usd)", True, A_CANCELLED),   # the same, once SQLite has run it and its row is being read
    ("UPDATE noderun", False, A_CANCELLED),     # the flush that marks a running
    ("INSERT INTO noderun", False, {}),         # the first commit: no row exists yet, as for a run cancelled before it started
])
async def test_a_cancel_that_lands_mid_statement_still_ends_the_run_cancelled(provider, sqlite_file, monkeypatch, statement,
                                                                             reading, left):
    """qa-w6 (SQLite, a cancel within ms of start). SQLAlchemy invalidates a connection whose statement a cancel interrupts,
    or rolls the flush back, and the session refuses to write until it is rolled back: the executor recorded the cancel
    anyway (PendingRollbackError, the node left pending). And a read cut off while its rows are fetched stays open (sqlite3
    closes the connection only once the cursor is gone): in SQLite's default journal mode its lock failed every commit,
    the executor's record of the cancel included, with "database is locked"; WAL lets a writer past readers."""
    import aiosqlite
    from sqlalchemy import event

    sessions = async_sessionmaker(sqlite_file, class_=AsyncSession, expire_on_commit=False)
    async with sessions() as s:
        run = await seed(s)
    armed, reached, fetchall = asyncio.Event(), asyncio.Event(), aiosqlite.Cursor.fetchall

    def before(conn, cursor, sql, *_):
        if statement in sql:
            (armed if reading else reached).set()

    async def fetching(cursor):
        if armed.is_set():  # SQLite has run the statement and holds its read open until the cursor ends
            armed.clear()
            reached.set()
            await asyncio.Event().wait()
        return await fetchall(cursor)

    monkeypatch.setattr(aiosqlite.Cursor, "fetchall", fetching)
    event.listen(sqlite_file.sync_engine, "before_cursor_execute", before)
    async with sessions() as db:
        task = asyncio.create_task(ex.run_workflow(run.id, db, AsyncMock(), 1.0))
        await asyncio.wait_for(reached.wait(), 5)
        task.cancel()  # lands while the executor awaits that statement
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)

    async with sessions() as s:
        assert (await s.get(Run, run.id)).status == RunStatus.CANCELLED
        rows = await s.scalars(select(NodeRun).where(NodeRun.run_id == run.id))
        assert {n.node_id: (n.status, n.error) for n in rows} == left


async def test_a_failing_setup_broadcast_still_fails_the_run(db, provider):
    run = await seed(db)

    async def broadcast(run_id, event):
        if event == {"type": "run_status", "status": "running"}:
            raise ConnectionError("redis down")

    await ex.run_workflow(run.id, db, broadcast, 1.0)

    await db.refresh(run)
    rows = await nodes(db, run)
    assert run.status == RunStatus.FAILED  # not stuck in provisioning_gpu
    assert (rows["a"].status, rows["a"].error) == (NodeStatus.FAILED, "internal: redis down")
    assert provider.provisioned == []


async def test_a_bad_node_timeout_fails_before_provisioning(db, provider, monkeypatch):
    monkeypatch.setenv("ORCHAPOD_NODE_TIMEOUT_S", "90m")
    run = await seed(db)

    await ex.run_workflow(run.id, db, AsyncMock(), 1.0)

    rows = await nodes(db, run)
    assert rows["a"].status == NodeStatus.FAILED and rows["a"].error.startswith("internal: ")
    assert provider.provisioned == []  # no container left running without a timeout


async def test_pod_is_terminated_even_if_recording_it_fails(db, provider, monkeypatch):
    run = await seed(db)
    real_commit, failed = db.commit, []

    async def commit():
        if provider.provisioned and not failed:  # the commit that records the pod
            failed.append(True)
            raise RuntimeError("db down")
        await real_commit()

    monkeypatch.setattr(db, "commit", commit)
    await ex.run_workflow(run.id, db, AsyncMock(), 1.0)

    rows = await nodes(db, run)
    assert provider.terminated == ["a"] and rows["a"].error == "internal: db down"


async def test_an_error_between_nodes_still_leaves_one_failed_node(db, provider):
    provider.script = {"a": {"outputs": {"train_jsonl": "r2://bk/a"}}}
    run = await seed(db)

    async def broadcast(run_id, event):
        if event.get("node_id") == "a" and event["status"] == "succeeded":
            raise ConnectionError("redis down")

    await ex.run_workflow(run.id, db, broadcast, 1.0)

    await db.refresh(run)
    rows = await nodes(db, run)
    assert run.status == RunStatus.FAILED  # retryable: exactly one failed node, the first unfinished one
    assert [rows[i].status for i in "abc"] == [NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.PENDING]
    assert rows["b"].error == "internal: redis down"


# --- run control API ---------------------------------------------------------

@pytest.fixture
async def launched(db, monkeypatch):
    """Executor tasks started by the routes; they get their own sessions on the test database. The report writers their
    ends start (routes/agent.report_later) finish before that database goes."""
    from api.routes import agent
    monkeypatch.setattr("api.database.AsyncSessionLocal",
                        async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False))
    tasks, real = [], ex.launch
    monkeypatch.setattr(ex, "launch", lambda run_id, scale: tasks.append(real(run_id, scale)) or tasks[-1])
    yield tasks
    while agent._reporting:
        await asyncio.wait(set(agent._reporting.values()))


@pytest.fixture
def admin(monkeypatch):
    """The X-Orchapod-Admin header: the admin cancels any run, with no cancel token."""
    monkeypatch.setenv("ORCHAPOD_ADMIN_TOKEN", "s3cret")
    return {"X-Orchapod-Admin": "s3cret"}


def owner(started) -> dict:
    """The cancel token header from a start reply: only the caller who started a run (or the admin) cancels it."""
    return {"X-Orchapod-Cancel-Token": started.json()["cancel_token"]}


def published():
    from api.services.events import event_bus
    return [c.args[1] for c in event_bus.publish.await_args_list]


async def test_cancel_terminates_the_pod_and_ends_cancelled(client, db, provider, launched):
    provider.script = {"a": {"exit": None}}  # a long-polling node
    run = await seed(db, status=RunStatus.PENDING)

    started = await client.post(f"/runs/{run.id}/start")
    assert (started.status_code, started.json()["status"]) == (200, "provisioning_gpu")
    await asyncio.wait_for(provider.started.wait(), 5)

    r = await client.post(f"/runs/{run.id}/cancel", headers=owner(started))

    assert (r.status_code, r.json()["status"]) == (200, "cancelled")
    assert provider.terminated == ["a"]
    rows = await nodes(db, run)
    assert (rows["a"].status, rows["a"].error, rows["b"].status) == (NodeStatus.FAILED, "cancelled", NodeStatus.PENDING)
    ev = published()
    assert ev.index({"type": "node_status", "node_id": "a", "status": "failed", "error": "cancelled"}) \
        < ev.index({"type": "run_status", "status": "cancelled", "error": "cancelled"})
    assert run.id not in ex.running_tasks
    assert (await client.post(f"/runs/{run.id}/cancel", headers=owner(started))).status_code == 409


async def test_cancel_a_run_that_never_started(client, db, admin):
    run = await seed(db, status=RunStatus.PENDING)
    r = await client.post(f"/runs/{run.id}/cancel", headers=admin)  # no token exists until a start
    assert (r.status_code, r.json()["status"]) == (200, "cancelled")


async def test_cancel_rereads_the_run_before_deciding(client, db, admin):
    run = await seed(db, status=RunStatus.RUNNING)
    async with async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)() as other:
        (await other.get(Run, run.id)).status = RunStatus.SUCCEEDED  # finished meanwhile, elsewhere
        await other.commit()
    r = await client.post(f"/runs/{run.id}/cancel", headers=admin)
    assert r.json()["status"] == "succeeded"


async def test_retry_reruns_the_failed_node_and_continues(client, db, provider, launched):
    provider.script = {"a": {"outputs": {"train_jsonl": "r2://bk/a"}}, "b": {"exit": 2}}
    run = await seed(db)
    await ex.run_workflow(run.id, db, AsyncMock(), 1.0)

    assert (await client.post(f"/runs/{run.id}/nodes/a/retry")).status_code == 409   # succeeded node
    assert (await client.post(f"/runs/{run.id}/nodes/zz/retry")).status_code == 404
    assert (await client.post(f"/runs/{uuid.uuid4()}/nodes/b/retry")).status_code == 404

    provider.script = {"b": {"outputs": {"train_jsonl": "r2://bk/b"}}}
    r = await client.post(f"/runs/{run.id}/nodes/b/retry")
    assert (r.status_code, r.json()["status"]) == (202, "provisioning_gpu")
    await asyncio.wait_for(launched[-1], 5)

    await db.refresh(run)
    rows = await nodes(db, run)
    assert run.status == RunStatus.SUCCEEDED
    assert {n.status for n in rows.values()} == {NodeStatus.SUCCEEDED}
    assert [n for n, _ in provider.provisioned] == ["a", "b", "b", "c"]  # a is not re-run
    assert (await client.post(f"/runs/{run.id}/nodes/b/retry")).status_code == 409   # run succeeded


async def test_retry_waits_for_a_provision_still_in_flight(client, db, provider, launched):
    provider.provision_gate = asyncio.Event()
    run = await seed(db, status=RunStatus.PENDING)
    started = await client.post(f"/runs/{run.id}/start")
    await asyncio.wait_for(provider.provisioning.wait(), 5)
    assert (await client.post(f"/runs/{run.id}/cancel", headers=owner(started))).json()["status"] == "cancelled"

    r = await client.post(f"/runs/{run.id}/nodes/a/retry")
    assert r.status_code == 409  # the cancelled node's container is still coming up
    provider.provision_gate.set()
    await drain()
    assert provider.terminated == ["a"]

    provider.script = {"a": {"exit": 1}}
    assert (await client.post(f"/runs/{run.id}/nodes/a/retry")).status_code == 202
    await asyncio.wait_for(launched[-1], 5)
    assert [n for n, _ in provider.provisioned] == ["a", "a"]  # one container per attempt


def other_session(db):
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)()


async def test_start_and_retry_are_conditional_updates(client, db, launched):
    run = await seed(db, status=RunStatus.PENDING)  # this session still holds it as pending
    async with other_session(db) as other:
        (await other.get(Run, run.id)).status = RunStatus.CANCELLED  # cancelled meanwhile, elsewhere
        await other.commit()
    assert (await client.post(f"/runs/{run.id}/start")).status_code == 409

    failed = await seed(db, status=RunStatus.FAILED)
    db.add(NodeRun(run_id=failed.id, node_id="a", node_type="data-prep", status=NodeStatus.FAILED, error="exit 1"))
    await db.commit()
    async with other_session(db) as other:
        (await other.get(Run, failed.id)).status = RunStatus.PROVISIONING_GPU  # another worker's retry won
        await other.commit()
    assert (await client.post(f"/runs/{failed.id}/nodes/a/retry")).status_code == 409
    assert launched == []


async def test_concurrent_retries_launch_one_executor(client, db, provider, launched):
    from api.database import get_session
    from api.main import app
    provider.script = {"a": {"outputs": {"train_jsonl": "r2://bk/a"}}, "b": {"exit": 2}}
    run = await seed(db)
    await ex.run_workflow(run.id, db, AsyncMock(), 1.0)
    provider.script = {"b": {"outputs": {"train_jsonl": "r2://bk/b"}}}
    sessions = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)

    async def per_request():  # one session per request, as in production
        async with sessions() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = per_request
    r1, r2 = await asyncio.gather(*(client.post(f"/runs/{run.id}/nodes/b/retry") for _ in range(2)))
    await asyncio.wait(set(launched))

    assert sorted([r1.status_code, r2.status_code]) in ([202, 202], [202, 409])
    assert [n for n, _ in provider.provisioned] == ["a", "b", "b", "c"]  # b re-ran once
    task = ex.launch(run.id, 1.0)
    assert ex.launch(run.id, 1.0) is task  # a double-click joins the running executor
    await task


async def test_summary_rolls_up_nodes_cost_and_artifacts(client, db):
    run = await seed(db, status=RunStatus.FAILED, cost_usd=Decimal("0.5"))
    a = NodeRun(run_id=run.id, node_id="a", node_type="data-prep", status=NodeStatus.SUCCEEDED)
    b = NodeRun(run_id=run.id, node_id="b", node_type="data-prep", status=NodeStatus.FAILED, error="exit 1: boom")
    c = NodeRun(run_id=run.id, node_id="c", node_type="data-prep")
    db.add_all([c, b, a])
    await db.flush()
    arts = [
        Artifact(node_run_id=a.id, name="cost_json", kind=ArtifactKind.METRICS, uri="r2://bk/runs/x/a/cost_json", meta={"usd": 0.1}),
        Artifact(node_run_id=a.id, name="dataset", kind=ArtifactKind.DATASET, uri="r2://bk/runs/x/a/dataset", meta={"rows": 9}),
        Artifact(node_run_id=b.id, name="cost_json", kind=ArtifactKind.METRICS, uri="r2://bk/runs/x/b/cost_json", meta={"usd": 0.15}),
        Artifact(node_run_id=b.id, name="cost_json", kind=ArtifactKind.METRICS, uri="r2://bk/runs/x/b/cost_json", meta={"usd": 0.25}),
        Artifact(node_run_id=b.id, name="endpoint_url", kind=ArtifactKind.ENDPOINT, uri="https://e.example/v1", meta={}),
    ]
    db.add_all(arts)
    await db.commit()

    s = (await client.get(f"/runs/{run.id}/summary")).json()

    assert (s["run_id"], s["status"], s["cost_usd"], s["error"]) == (str(run.id), "failed", 0.5, "exit 1: boom")
    assert [(n["node_id"], n["type"], n["status"], n["usd"]) for n in s["nodes"]] == [
        ("a", "data-prep", "succeeded", 0.1), ("b", "data-prep", "failed", 0.4), ("c", "data-prep", "pending", 0)]
    assert {k for k in s["nodes"][0]} == {"node_id", "type", "status", "usd", "error", "started_at", "finished_at",
                                          "provider", "resource"}
    by_name = {(x["node_id"], x["name"]): x for x in s["artifacts"]}
    assert by_name[("a", "dataset")]["download_url"] == f"/artifacts/{arts[1].id}/download"
    assert by_name[("a", "dataset")]["meta"] == {"rows": 9}
    assert by_name[("b", "endpoint_url")]["download_url"] is None
    assert (await client.get(f"/runs/{uuid.uuid4()}/summary")).status_code == 404


class Serverless:
    """NebiusServerless as the summary reads it (contracts "NebiusServerless"): jobs.get(id) and endpoints.get(id) answer
    {"state": states[id]}, and an id with no state raises; endpoints.list() answers `listing` (and records "list");
    `gate` (a threading.Event) holds every call until it is set."""

    def __init__(self):
        self.calls, self.states, self.listing, self.gate = [], {}, [], None
        self.jobs = self.endpoints = self

    def get(self, id):
        self.calls.append(id)
        if self.gate:
            self.gate.wait(10)
        return {"id": id, "state": self.states[id]}

    def list(self):
        self.calls.append("list")
        if self.gate:
            self.gate.wait(10)
        return self.listing


@pytest.fixture
def nebius(monkeypatch):
    from api.routes import runs
    fake, clock = Serverless(), [1000.0]
    fake.clock = clock
    monkeypatch.setattr(runs, "_serverless", lambda: fake)
    monkeypatch.setattr(runs, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runs, "_states", {})
    return fake


async def train_state(client, db):
    """A run whose train node runs as Nebius job aijob-1 → a coroutine function reading that node's state from the summary."""
    run = await seed(db, status=RunStatus.RUNNING)
    db.add(NodeRun(run_id=run.id, node_id="train", node_type="unsloth-train", status=NodeStatus.RUNNING,
                   gpu_provider="nebius", gpu_pod_id="aijob-1"))
    await db.commit()

    async def state():
        return (await client.get(f"/runs/{run.id}/summary")).json()["nodes"][0]["resource"]["state"]
    return state


async def test_summary_says_where_each_node_runs(client, db, nebius):
    """provider = the NodeRun's gpu_provider. resource: a gpu node on nebius → its Job; a node with an endpoint_url artifact
    → the newest endpoint_id; the live state only for a node that is running."""
    run = await seed(db, status=RunStatus.RUNNING)
    prep, train, serve, judge = (NodeRun(run_id=run.id, node_id=i, node_type=t, status=s, gpu_provider=p, gpu_pod_id=pod)
                                 for i, t, s, p, pod in (
        ("prep", "data-prep", NodeStatus.SUCCEEDED, "local-docker", "c1"),
        ("train", "unsloth-train", NodeStatus.RUNNING, "nebius", "aijob-1"),
        ("serve", "vllm-serve", NodeStatus.SUCCEEDED, "local-docker", "c2"),
        ("evaluate", "judge-eval", NodeStatus.PENDING, None, None)))
    db.add_all([prep, train, serve, judge])
    await db.flush()
    db.add_all(Artifact(node_run_id=serve.id, name="endpoint_url", kind=ArtifactKind.ENDPOINT, uri="https://ep.example",
                        meta=meta, created_at=datetime(2026, 10, 25, 10, 0, minute))  # a retry registered a newer one
               for minute, meta in ((0, {"endpoint_id": "aiendpoint-0"}), (1, {"endpoint_id": "aiendpoint-1"}), (2, {})))
    await db.commit()
    nebius.states["aijob-1"] = "IMAGE_PULLING"

    s = (await client.get(f"/runs/{run.id}/summary")).json()

    assert {n["node_id"]: (n["provider"], n["resource"]) for n in s["nodes"]} == {
        "prep": ("local-docker", None),
        "train": ("nebius", {"kind": "job", "id": "aijob-1", "state": "IMAGE_PULLING"}),
        "serve": ("local-docker", {"kind": "endpoint", "id": "aiendpoint-1", "state": None}),  # done, and no expiry: not asked
        "evaluate": (None, None)}
    assert nebius.calls == ["aijob-1"]


async def test_a_live_state_is_cached_per_id_for_30_s(client, db, nebius):
    state = await train_state(client, db)
    nebius.states["aijob-1"] = "IMAGE_PULLING"
    assert [await state(), await state()] == ["IMAGE_PULLING"] * 2

    nebius.states["aijob-1"] = "RUNNING"
    nebius.clock[0] += 29
    assert await state() == "IMAGE_PULLING"  # read 29 s ago: cached
    nebius.clock[0] += 2
    assert await state() == "RUNNING"        # 31 s: read again
    assert nebius.calls == ["aijob-1"] * 2


async def test_a_state_that_cannot_be_read_is_null_and_not_asked_again_for_30_s(client, db, nebius):
    state = await train_state(client, db)
    assert await state() is None  # jobs.get raised: the summary answers all the same
    nebius.states["aijob-1"] = "RUNNING"
    assert await state() is None  # the failure is cached too, so a Nebius that hangs costs one worker thread per 30 s
    nebius.clock[0] += 31
    assert await state() == "RUNNING"
    assert nebius.calls == ["aijob-1"] * 2


async def test_the_summary_does_not_wait_longer_than_STATE_WAIT_S_for_nebius(client, db, nebius, monkeypatch):
    from api.routes import runs
    assert (runs.STATE_WAIT_S, runs.STATE_TTL_S) == (3, 30)  # the contract's bounds
    monkeypatch.setattr(runs, "STATE_WAIT_S", 0.05)  # patched down to keep the test fast
    nebius.gate, nebius.states["aijob-1"] = threading.Event(), "RUNNING"
    state = await train_state(client, db)
    try:
        assert await asyncio.wait_for(state(), 5) is None  # answered while the call is still held at the gate
        for _ in range(200):  # the worker thread reaches the gate a moment after the wait gave up
            if nebius.calls:
                break
            await asyncio.sleep(0.01)
        assert await asyncio.wait_for(state(), 5) is None and nebius.calls == ["aijob-1"]  # cached: no second thread
    finally:
        nebius.gate.set()


async def test_no_live_state_is_read_under_stub(client, db, nebius, monkeypatch):
    nebius.states["aijob-1"] = "RUNNING"
    state = await train_state(client, db)
    monkeypatch.setenv("STUB", "1")
    assert await state() is None and nebius.calls == []


async def test_a_serving_node_that_has_not_registered_is_found_by_the_name_vllm_serve_gives_its_endpoint(client, db, nebius):
    """While vllm-serve waits for its endpoint (about nine minutes) it has registered nothing: its endpoint is the one Nebius
    lists under the node's name, from the one function the node names it with (an id with a capital and an underscore, so a
    name derived any other way would not match)."""
    from orchapod.names import endpoint_name
    from tests.containers.conftest import load_container
    assert load_container("vllm-serve").endpoint_name is endpoint_name  # one function: the node and the API never differ
    run = await seed(db, status=RunStatus.RUNNING)
    node = NodeRun(run_id=run.id, node_id="Serve_8B", node_type="vllm-serve", status=NodeStatus.RUNNING,
                   gpu_provider="local-docker", gpu_pod_id="c1")
    db.add(node)
    await db.commit()
    name = endpoint_name(str(run.id), "Serve_8B")
    assert name == f"orchapod-{str(run.id)[:8]}-serve-8b"  # lowercased, "_" → "-": a name derived by hand would differ

    async def resource():
        return (await client.get(f"/runs/{run.id}/summary")).json()["nodes"][0]["resource"]

    nebius.listing = [{"id": "aiendpoint-x", "name": "orchapod-12345678-serve", "state": "RUNNING"}]  # another run's
    assert await resource() is None  # not created yet (the null is cached, like any read)
    nebius.listing.append({"id": "aiendpoint-9", "name": name, "state": "PROVISIONING"})
    assert await resource() is None
    nebius.clock[0] += 31
    assert await resource() == {"kind": "endpoint", "id": "aiendpoint-9", "state": "PROVISIONING"}
    nebius.listing[-1]["state"] = "IMAGE_PULLING"
    assert (await resource())["state"] == "PROVISIONING"  # read 0 s ago
    nebius.clock[0] += 31
    assert await resource() == {"kind": "endpoint", "id": "aiendpoint-9", "state": "IMAGE_PULLING"}
    assert nebius.calls == ["list"] * 3

    nebius.states["aiendpoint-9"] = "RUNNING"  # it registered: by id from now on, while the node still runs
    db.add(Artifact(node_run_id=node.id, name="endpoint_url", kind=ArtifactKind.ENDPOINT, uri="https://ep.example",
                    meta={"endpoint_id": "aiendpoint-9"}))
    await db.commit()
    nebius.clock[0] += 31
    assert await resource() == {"kind": "endpoint", "id": "aiendpoint-9", "state": "RUNNING"}
    assert nebius.calls[3:] == ["aiendpoint-9"]


async def test_a_lookup_by_name_waits_at_most_STATE_WAIT_S_and_never_runs_under_stub(client, db, nebius, monkeypatch):
    from api.routes import runs
    run = await seed(db, status=RunStatus.RUNNING)
    db.add(NodeRun(run_id=run.id, node_id="serve", node_type="vllm-serve", status=NodeStatus.RUNNING))
    await db.commit()

    async def resource():
        return (await asyncio.wait_for(client.get(f"/runs/{run.id}/summary"), 5)).json()["nodes"][0]["resource"]

    monkeypatch.setenv("STUB", "1")
    assert await resource() is None and nebius.calls == []  # a STUB endpoint registers as stub-*; nothing exists at Nebius
    monkeypatch.delenv("STUB")
    monkeypatch.setattr(runs, "STATE_WAIT_S", 0.05)
    nebius.gate = threading.Event()
    try:
        assert await resource() is None  # the listing hangs at the gate: the summary answers all the same
    finally:
        nebius.gate.set()


async def test_a_registered_endpoint_is_read_until_its_artifact_expires_or_is_deleted(client, db, nebius):
    """The keep-alive window: the node is done, the endpoint serves /compare for keep_alive_min. Its state is read until
    meta.expires_at passes or meta.deleted_at is set (the TTL task sets it)."""
    run = await seed(db, status=RunStatus.RUNNING)
    now = datetime.now(timezone.utc)
    metas = {"live": {"endpoint_id": "ep-live", "expires_at": (now + timedelta(minutes=10)).isoformat()},
             "expired": {"endpoint_id": "ep-old", "expires_at": (now - timedelta(minutes=1)).isoformat()},
             "deleted": {"endpoint_id": "ep-gone", "expires_at": (now + timedelta(minutes=10)).isoformat(),
                         "deleted_at": now.isoformat()},
             "unreadable": {"endpoint_id": "ep-odd", "expires_at": "soon"}}
    for node_id, meta in metas.items():
        node = NodeRun(run_id=run.id, node_id=node_id, node_type="vllm-serve", status=NodeStatus.SUCCEEDED,
                       gpu_provider="local-docker")
        db.add(node)
        await db.flush()
        db.add(Artifact(node_run_id=node.id, name="endpoint_url", kind=ArtifactKind.ENDPOINT, uri="https://ep.example", meta=meta))
    await db.commit()
    nebius.states.update({meta["endpoint_id"]: "RUNNING" for meta in metas.values()})

    s = (await client.get(f"/runs/{run.id}/summary")).json()

    assert {n["node_id"]: (n["resource"]["id"], n["resource"]["state"]) for n in s["nodes"]} == {
        "live": ("ep-live", "RUNNING"), "expired": ("ep-old", None), "deleted": ("ep-gone", None),
        "unreadable": ("ep-odd", None)}
    assert nebius.calls == ["ep-live"]  # the others are not asked
    nebius.states["ep-live"] = "STOPPING"
    nebius.clock[0] += 31
    assert [n["resource"]["state"] for n in (await client.get(f"/runs/{run.id}/summary")).json()["nodes"]
            if n["node_id"] == "live"] == ["STOPPING"]  # same cache as the rest: read again after 30 s


async def test_a_runs_gpu_provider_is_its_first_gpu_nodes_else_null(client, db):
    """RunOut.gpu_provider was whatever the last node set (the run header read "GPU: local-docker"); it is now the provider
    of the first node that rents a GPU (by start time), whatever Run.gpu_provider says, else null."""
    gpu, cpu = [await seed(db, gpu_provider="local-docker") for _ in range(2)]  # the column: the last node's
    for run, rows in ((gpu, (("prep", "data-prep", "local-docker"), ("train", "unsloth-train", "nebius"),
                             ("serve", "vllm-serve", "local-docker"), ("evaluate", "judge-eval", "local-docker"))),
                      (cpu, (("prep", "data-prep", "local-docker"), ("evaluate", "judge-eval", "local-docker")))):
        db.add_all(NodeRun(run_id=run.id, node_id=i, node_type=t, status=NodeStatus.SUCCEEDED, gpu_provider=p,
                           started_at=datetime(2026, 10, 25, 10, 0, n)) for n, (i, t, p) in enumerate(rows))
    await db.commit()

    assert (await client.get(f"/runs/{gpu.id}")).json()["gpu_provider"] == "nebius"
    assert (await client.get(f"/runs/{cpu.id}")).json()["gpu_provider"] is None
    assert {r["id"]: r["gpu_provider"] for r in (await client.get("/runs")).json()} == {
        str(gpu.id): "nebius", str(cpu.id): None}


async def test_artifact_download_redirects_to_a_presigned_url(client, db, seeded_node_run):
    _, node_run = seeded_node_run
    file = Artifact(node_run_id=node_run.id, name="dataset", kind=ArtifactKind.DATASET,
                    uri="r2://orchapod-artifacts/runs/r/n/dataset")
    url = Artifact(node_run_id=node_run.id, name="endpoint_url", kind=ArtifactKind.ENDPOINT, uri="https://e.example/v1")
    db.add_all([file, url])
    await db.commit()

    r = await client.get(f"/artifacts/{file.id}/download")
    assert r.status_code == 307
    assert "runs/r/n/dataset" in r.headers["location"] and "Signature" in r.headers["location"]
    assert (await client.get(f"/artifacts/{url.id}/download")).status_code == 404


async def test_internal_routes_require_the_secret(client):
    body = {"run_id": str(uuid.uuid4()), "node_id": "n", "ts": "t", "level": "INFO", "message": "m"}
    assert (await client.post("/internal/log", json=body, headers={"X-Orchapod-Secret": ""})).status_code == 403
    assert (await client.post("/internal/log", json=body, headers={"X-Orchapod-Secret": "wrong"})).status_code == 403
    assert (await client.post("/internal/log", json=body)).status_code == 204  # the client sends the real one


async def test_error_log_line_is_kept_for_the_node_error(client, db, seeded_node_run):
    run, node_run = seeded_node_run
    for level, message in [("ERROR", "tavily quota 432: out of credits"), ("INFO", "still going")]:
        await client.post("/internal/log", json={"run_id": str(run.id), "node_id": "node", "ts": "t",
                                                 "level": level, "message": message})
    await db.refresh(node_run)
    assert node_run.error == "tavily quota 432: out of credits"

    node_run.status, node_run.error = NodeStatus.FAILED, "cancelled"
    await db.commit()
    await client.post("/internal/log", json={"run_id": str(run.id), "node_id": "node", "ts": "t",
                                             "level": "ERROR", "message": "late line after SIGTERM"})
    await db.refresh(node_run)
    assert node_run.error == "cancelled"


async def test_cost_json_adds_to_run_cost(client, db, seeded_node_run):
    run, _ = seeded_node_run
    for _ in range(2):
        r = await client.post("/internal/artifact", json={"run_id": str(run.id), "node_id": "node", "artifact": {
            "name": "cost_json", "uri": "r2://b/runs/x/node/cost_json", "kind": "metrics", "metadata": {"usd": 0.25}}})
        assert r.status_code == 201
    await db.refresh(run)
    assert run.cost_usd == Decimal("0.5")
    assert [e for e in published() if e["type"] == "run_cost"] == [
        {"type": "run_cost", "cost_usd": 0.25}, {"type": "run_cost", "cost_usd": 0.5}]


async def test_events_fire_only_after_their_change_is_committed(client, tmp_path, monkeypatch, admin):
    """A client re-reads /runs/{id}/summary on run_cost, artifact and run_status: it must see the change."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel import SQLModel
    from api.database import get_session
    from api.main import app
    from api.services.events import event_bus

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'events.db'}")  # its own connections
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sessions() as s:
        run, idle = Run(user_id=uuid.uuid4(), status=RunStatus.RUNNING), Run(user_id=uuid.uuid4())
        s.add_all([run, idle])
        await s.flush()
        s.add(NodeRun(run_id=run.id, node_id="n", node_type="data-prep", status=NodeStatus.RUNNING))
        await s.commit()
    monkeypatch.setattr("api.database.AsyncSessionLocal", sessions)
    app.dependency_overrides.pop(get_session)  # production's session: commits when the request ends

    seen = []

    async def reread(run_id, event):  # what another connection sees when the event fires
        async with sessions() as s:
            r = await s.get(Run, run_id)
            names = [a.name for a in await s.scalars(select(Artifact))]
            seen.append((event["type"], r.status.value, float(r.cost_usd or 0), names))

    event_bus.publish.side_effect = reread
    await client.post("/internal/artifact", json={"run_id": str(run.id), "node_id": "n", "artifact": {
        "name": "cost_json", "uri": "r2://b/runs/x/n/cost_json", "kind": "metrics", "metadata": {"usd": 0.25}}})
    await client.post(f"/runs/{idle.id}/cancel", headers=admin)
    await engine.dispose()

    assert seen == [("run_cost", "running", 0.25, ["cost_json"]), ("artifact", "running", 0.25, ["cost_json"]),
                    ("run_status", "cancelled", 0.0, ["cost_json"])]


async def test_deploy_launches_through_the_one_launcher_with_the_callers_caps(client, monkeypatch):
    launched = []
    monkeypatch.setattr(ex, "launch", lambda run_id, scale: launched.append((run_id, scale)))  # cancel finds its task
    r = await client.post("/inference/deploy", json={"model": "Qwen/Qwen3-4B-Instruct", "mode": "quantize-gguf"})
    assert r.status_code == 202  # GGUF runs on CPU; serve (vllm-serve, a GPU) is admin-only
    assert launched == [(uuid.UUID(r.json()["run_id"]), 0.1)]  # anonymous: caps x ORCHAPOD_ANON_SCALE
    monkeypatch.setenv("ORCHAPOD_KILL_SWITCH", "1")
    assert (await client.post("/inference/deploy", json={"model": "m", "mode": "serve"})).status_code == 503


def test_a_launch_without_the_callers_scale_fails_loudly():
    import inspect
    for fn in (ex.launch, ex.run_workflow):  # never a silent default to the full caps
        assert inspect.signature(fn).parameters["scale"].default is inspect.Parameter.empty


def test_sqlite_runs_in_wal_mode():
    """WAL keeps a read a cancel cut off from failing the commits after it (backend-w6); the race test attaches it itself."""
    from sqlalchemy import event
    from api import database
    if database.engine.url.get_backend_name() == "sqlite":
        assert event.contains(database.engine.sync_engine, "connect", database.sqlite_wal)
