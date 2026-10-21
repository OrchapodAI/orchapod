"""Executor and run control API per contracts "Run state machine" and "Run control API"."""

from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.executor import run_workflow as ex
from api.models.db import Artifact, ArtifactKind, NodeRun, NodeStatus, Run, RunStatus, Workflow
from packages.providers.base import Pod

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
        self.envs, self.provisioned, self.terminated = {}, [], []
        self.started, self.provisioning, self.terminating = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.provision_gate = self.terminate_gate = None  # an asyncio.Event blocks that call until set

    async def provision(self, gpu_spec, image, env):
        self.provisioning.set()
        if self.provision_gate:
            await self.provision_gate.wait()  # docker run still pulling the image
        self.provisioned.append((env["ORCHAPOD_NODE_ID"], image))
        self.envs[env["ORCHAPOD_NODE_ID"]] = env
        return Pod(provider="local-docker", pod_id=env["ORCHAPOD_NODE_ID"])

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

    await ex.run_workflow(run.id, db, broadcast)

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

    await ex.run_workflow(run.id, db, broadcast)

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

    await ex.run_workflow(run.id, db, AsyncMock())

    rows = await nodes(db, run)
    assert rows["b"].status == NodeStatus.FAILED
    assert rows["b"].error == "unresolved ref ${{ nodes.a.outputs.train_jsonl }}"
    assert [n for n, _ in provider.provisioned] == ["a"]


async def test_api_runtime_runs_on_local_docker_and_gpu_needs_a_provider(db, provider, monkeypatch):
    from packages.workflow_schema.models import NODE_REGISTRY, NodeType
    monkeypatch.setitem(NODE_REGISTRY[NodeType.DATA_PREP], "runtime", "api")
    provider.script = {"a": {"outputs": {"train_jsonl": "r2://bk/a"}}, "b": {"outputs": {"train_jsonl": "r2://bk/b"}}}
    run = await seed(db)
    await ex.run_workflow(run.id, db, AsyncMock())
    await db.refresh(run)
    assert run.status == RunStatus.SUCCEEDED

    gpu = await seed(db, yaml="name: g\nnodes:\n  - id: t\n    type: unsloth-train\n    inputs: {model: m}\n")
    await ex.run_workflow(gpu.id, db, AsyncMock())
    rows = await nodes(db, gpu)
    assert rows["t"].error == "no gpu provider: NEBIUS_PROJECT_ID not set"


async def test_timeout_terminates_the_pod(db, provider, monkeypatch):
    monkeypatch.setenv("ORCHAPOD_NODE_TIMEOUT_S", "0.05")
    provider.script = {"a": {"exit": None}}
    run = await seed(db)

    await asyncio.wait_for(ex.run_workflow(run.id, db, AsyncMock()), 5)

    rows = await nodes(db, run)
    assert rows["a"].error == "timeout after 0.05 s"
    assert provider.terminated == ["a"]


async def test_container_stdout_becomes_log_events(db, provider):
    provider.logs = ["[2026-10-20T10:00:00+00:00] [INFO] already posted by the SDK", "pip noise"]
    provider.script = {"a": {"exit": 1}}
    run = await seed(db)
    broadcast = AsyncMock()

    await ex.run_workflow(run.id, db, broadcast)

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
    nr = NodeRun(run_id=uuid.uuid4(), node_id="train", node_type="unsloth-train", inputs={"model": "m"},
                 outputs={"checkpoint_step_000100": "r2://b/100", "checkpoint_step_000200": "r2://b/200"})

    env = ex._build_env(nr, 1.25)

    assert set(env) == {
        "NEBIUS_API_KEY", "NEBIUS_BASE_URL", "TAVILY_API_KEY", "HF_TOKEN", "NEBIUS_PROJECT_ID", "NEBIUS_IAM_TOKEN",
        "ORCHAPOD_ENDPOINT_TOKEN", "ORCHAPOD_R2_ENDPOINT", "ORCHAPOD_R2_REGION", "ORCHAPOD_R2_ACCESS_KEY",
        "ORCHAPOD_R2_SECRET_KEY", "ORCHAPOD_R2_BUCKET", "ORCHAPOD_CONTROL_URL", "ORCHAPOD_INTERNAL_SECRET",
        "ORCHAPOD_MAX_COST_USD", "STUB", "ORCHAPOD_NODE_INPUTS", "ORCHAPOD_NODE_OUTPUTS_DIR", "ORCHAPOD_RUN_ID",
        "ORCHAPOD_NODE_ID", "ORCHAPOD_RESUME_CHECKPOINT_URI",
    }
    assert env["TAVILY_API_KEY"] == "tvly-z"
    assert env["NEBIUS_BASE_URL"] == "https://api.tokenfactory.nebius.com/v1"
    assert (env["ORCHAPOD_R2_REGION"], env["ORCHAPOD_CONTROL_URL"]) == ("auto", "http://localhost:8001")
    assert env["ORCHAPOD_INTERNAL_SECRET"] == INTERNAL_SECRET and INTERNAL_SECRET
    assert env["ORCHAPOD_MAX_COST_USD"] == "1.2500"
    assert env["ORCHAPOD_RESUME_CHECKPOINT_URI"] == "r2://b/200"  # retry reuses the row: newest checkpoint


async def test_one_node_run_per_run_and_node(db):
    run = await seed(db)
    db.add(NodeRun(run_id=run.id, node_id="a", node_type="data-prep"))
    db.add(NodeRun(run_id=run.id, node_id="a", node_type="data-prep"))
    with pytest.raises(IntegrityError):
        await db.commit()


async def test_startup_sweep_fails_orphaned_runs(db, provider):
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


async def test_startup_runs_the_sweep(monkeypatch):
    from api import main
    swept = AsyncMock()
    monkeypatch.setattr(main, "sweep", swept)
    monkeypatch.setattr(main, "create_tables", AsyncMock())
    monkeypatch.setattr(main, "register_providers", lambda **_: None)
    monkeypatch.setattr(main.event_bus, "connect", AsyncMock())
    monkeypatch.setattr(main.event_bus, "disconnect", AsyncMock())

    async with main.lifespan(main.app):
        pass

    swept.assert_awaited_once()


async def test_cancel_during_provision_terminates_the_pod_once_it_exists(db, provider):
    provider.provision_gate = asyncio.Event()
    run = await seed(db)
    task = asyncio.create_task(ex.run_workflow(run.id, db, AsyncMock()))
    await asyncio.wait_for(provider.provisioning.wait(), 5)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    provider.provision_gate.set()  # the container comes up after the cancel
    await asyncio.wait_for(provider.terminating.wait(), 5)
    await drain()

    assert provider.terminated == ["a"]
    rows = await nodes(db, run)
    assert (rows["a"].status, rows["a"].error) == (NodeStatus.FAILED, "cancelled")


async def test_a_second_cancel_cannot_interrupt_teardown(db, provider):
    provider.script = {"a": {"exit": None}}
    provider.terminate_gate = asyncio.Event()
    run = await seed(db)
    task = asyncio.create_task(ex.run_workflow(run.id, db, AsyncMock()))
    await asyncio.wait_for(provider.started.wait(), 5)

    task.cancel()
    await asyncio.wait_for(provider.terminating.wait(), 5)  # SIGTERM sent, grace running
    task.cancel()                                            # a second click on Cancel
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert ex.busy(run.id)                                   # the executor is gone, the teardown is not
    provider.terminate_gate.set()
    await drain()

    assert provider.terminated == ["a"] and not ex.busy(run.id)
    rows = await nodes(db, run)
    assert (rows["a"].status, rows["a"].error) == (NodeStatus.FAILED, "cancelled")


async def test_a_failing_setup_broadcast_still_fails_the_run(db, provider):
    run = await seed(db)

    async def broadcast(run_id, event):
        if event == {"type": "run_status", "status": "running"}:
            raise ConnectionError("redis down")

    await ex.run_workflow(run.id, db, broadcast)

    await db.refresh(run)
    rows = await nodes(db, run)
    assert run.status == RunStatus.FAILED  # not stuck in provisioning_gpu
    assert (rows["a"].status, rows["a"].error) == (NodeStatus.FAILED, "internal: redis down")
    assert provider.provisioned == []


async def test_a_bad_node_timeout_fails_before_provisioning(db, provider, monkeypatch):
    monkeypatch.setenv("ORCHAPOD_NODE_TIMEOUT_S", "90m")
    run = await seed(db)

    await ex.run_workflow(run.id, db, AsyncMock())

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
    await ex.run_workflow(run.id, db, AsyncMock())

    rows = await nodes(db, run)
    assert provider.terminated == ["a"] and rows["a"].error == "internal: db down"


async def test_an_error_between_nodes_still_leaves_one_failed_node(db, provider):
    provider.script = {"a": {"outputs": {"train_jsonl": "r2://bk/a"}}}
    run = await seed(db)

    async def broadcast(run_id, event):
        if event.get("node_id") == "a" and event["status"] == "succeeded":
            raise ConnectionError("redis down")

    await ex.run_workflow(run.id, db, broadcast)

    await db.refresh(run)
    rows = await nodes(db, run)
    assert run.status == RunStatus.FAILED  # retryable: exactly one failed node, the first unfinished one
    assert [rows[i].status for i in "abc"] == [NodeStatus.SUCCEEDED, NodeStatus.FAILED, NodeStatus.PENDING]
    assert rows["b"].error == "internal: redis down"


# --- run control API ---------------------------------------------------------

@pytest.fixture
def launched(db, monkeypatch):
    """Executor tasks started by the routes; they get their own sessions on the test database."""
    monkeypatch.setattr("api.database.AsyncSessionLocal",
                        async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False))
    tasks, real = [], ex.launch
    monkeypatch.setattr(ex, "launch", lambda run_id, scale=1.0: tasks.append(real(run_id, scale)) or tasks[-1])
    return tasks


def published():
    from api.services.events import event_bus
    return [c.args[1] for c in event_bus.publish.await_args_list]


async def test_cancel_terminates_the_pod_and_ends_cancelled(client, db, provider, launched):
    provider.script = {"a": {"exit": None}}  # a long-polling node
    run = await seed(db, status=RunStatus.PENDING)

    r = await client.post(f"/runs/{run.id}/start")
    assert (r.status_code, r.json()["status"]) == (200, "provisioning_gpu")
    await asyncio.wait_for(provider.started.wait(), 5)

    r = await client.post(f"/runs/{run.id}/cancel")

    assert (r.status_code, r.json()["status"]) == (200, "cancelled")
    assert provider.terminated == ["a"]
    rows = await nodes(db, run)
    assert (rows["a"].status, rows["a"].error, rows["b"].status) == (NodeStatus.FAILED, "cancelled", NodeStatus.PENDING)
    ev = published()
    assert ev.index({"type": "node_status", "node_id": "a", "status": "failed", "error": "cancelled"}) \
        < ev.index({"type": "run_status", "status": "cancelled", "error": "cancelled"})
    assert run.id not in ex.running_tasks
    assert (await client.post(f"/runs/{run.id}/cancel")).status_code == 409


async def test_cancel_a_run_that_never_started(client, db):
    run = await seed(db, status=RunStatus.PENDING)
    r = await client.post(f"/runs/{run.id}/cancel")
    assert (r.status_code, r.json()["status"]) == (200, "cancelled")


async def test_cancel_rereads_the_run_before_deciding(client, db):
    run = await seed(db, status=RunStatus.RUNNING)
    async with async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)() as other:
        (await other.get(Run, run.id)).status = RunStatus.SUCCEEDED  # finished meanwhile, elsewhere
        await other.commit()
    r = await client.post(f"/runs/{run.id}/cancel")
    assert r.json()["status"] == "succeeded"


async def test_retry_reruns_the_failed_node_and_continues(client, db, provider, launched):
    provider.script = {"a": {"outputs": {"train_jsonl": "r2://bk/a"}}, "b": {"exit": 2}}
    run = await seed(db)
    await ex.run_workflow(run.id, db, AsyncMock())

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
    await client.post(f"/runs/{run.id}/start")
    await asyncio.wait_for(provider.provisioning.wait(), 5)
    assert (await client.post(f"/runs/{run.id}/cancel")).json()["status"] == "cancelled"

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
    await ex.run_workflow(run.id, db, AsyncMock())
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
    task = ex.launch(run.id)
    assert ex.launch(run.id) is task  # a double-click joins the running executor
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
    assert {k for k in s["nodes"][0]} == {"node_id", "type", "status", "usd", "error", "started_at", "finished_at"}
    by_name = {(x["node_id"], x["name"]): x for x in s["artifacts"]}
    assert by_name[("a", "dataset")]["download_url"] == f"/artifacts/{arts[1].id}/download"
    assert by_name[("a", "dataset")]["meta"] == {"rows": 9}
    assert by_name[("b", "endpoint_url")]["download_url"] is None
    assert (await client.get(f"/runs/{uuid.uuid4()}/summary")).status_code == 404


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


async def test_deploy_launches_through_the_one_launcher(client, monkeypatch):
    launched = []
    monkeypatch.setattr(ex, "launch", launched.append)  # launch() registers the task cancel looks up
    r = await client.post("/inference/deploy", json={"model": "Qwen/Qwen3-4B-Instruct", "mode": "serve"})
    assert r.status_code == 202
    assert launched == [uuid.UUID(r.json()["run_id"])]
