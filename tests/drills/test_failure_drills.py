"""Failure drills (PLAN A6 D5), from faked provider responses and with no Docker.

A node's own run.py runs in this process under the env the executor built, with the real SDK: its uploads land in an
in-memory bucket and its /internal posts go through the API. Each run recovers, or fails with the exact error the run
page shows verbatim (GET /runs/{id}/summary `error`). Then the refusals a visitor of the public app can hit."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import urllib.request
from collections import deque
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.agent import planner
from api.executor import run_workflow as ex
from api.models.db import Spend
from orchapod import checkpoint, cost, io, log
from orchapod.prices import PRICES
from packages.providers.base import GPUSpec, Pod
from packages.providers.nebius import NebiusProvider
from packages.providers.tavily import Tavily
from packages.providers.tokenfactory import SUPER, ULTRA, TokenFactory
from tests.containers.conftest import load_container

from api.services import ratelimit

BUCKET, LLAMA, STUDENT = "orchapod-artifacts", "meta-llama/Llama-3.1-8B-Instruct", "nvidia/Llama-3.1-Nemotron-Nano-8B-v1"
ADMIN = {"X-Orchapod-Admin": "drill-admin"}
INTENT_2 = "Create synthetic data of movie likes, shares and subscribes."
MOVIE_ROW = {  # intent #2's row_schema, from the contract
    "type": "object", "additionalProperties": False, "required": ["user_id", "movie_title", "action", "timestamp", "device"],
    "properties": {"user_id": {"type": "string"}, "movie_title": {"type": "string"},
                   "action": {"enum": ["like", "share", "subscribe"]},
                   "timestamp": {"type": "string", "format": "date-time"}, "device": {"enum": ["mobile", "tv", "web", "tablet"]}}}
CHAT_ROW = {"messages": [{"role": "user", "content": "Which GPU does gpu-l40s-a run?"},
                         {"role": "assistant", "content": "An NVIDIA L40S with an Intel CPU."}]}


class Nodes:
    """In place of containers. provision() keeps the env the executor built; wait() runs the node in this process with that
    env and the real SDK (`bodies[type]`, else containers/<type>/run.py main()), sends what the SDK posted to the API and
    returns the exit code. As the gpu provider it is a Serverless Job (contracts "NebiusProvider"): the real NebiusProvider
    reads the Job's end from a recorded reply, so 0 when COMPLETED, else 1 with the cause in Pod.error."""

    def __init__(self, name: str, client, tmp_path: Path):
        self.name, self.client, self.tmp = name, client, tmp_path
        self.bodies: dict = {}
        self.started: dict[str, tuple[str, dict]] = {}  # pod id → (node type, env)
        self.sleeps: list[float] = []  # time.sleep in the node: the clients' backoff, the fine-tune poll

    async def provision(self, gpu_spec, image: str, env: dict) -> Pod:
        pod = Pod(provider=self.name, pod_id=f"{env['ORCHAPOD_NODE_ID']}-{len(self.started) + 1}")
        self.started[pod.pod_id] = (image.rsplit("/", 1)[1].split(":")[0], env)
        return pod

    async def stream_logs(self, pod):
        return
        yield

    async def terminate(self, pod) -> None:
        pass

    async def quote(self, gpu_spec):  # the executor bills a gpu pod's wall time at the provider's quote
        return await NebiusProvider().quote(gpu_spec)

    async def wait(self, pod) -> int:
        node_type, env = self.started[pod.pod_id]
        sent, now = [], [0.0]

        def sleep(seconds):
            self.sleeps.append(seconds)
            now[0] += seconds

        with pytest.MonkeyPatch.context() as m:
            for k, v in {**env, "ORCHAPOD_NODE_OUTPUTS_DIR": str(self.tmp / pod.pod_id)}.items():
                m.setenv(k, v)
            m.setattr(cost, "_items", {})
            m.setattr(log, "lines", deque(maxlen=5000))
            m.setattr(urllib.request, "urlopen", lambda req, timeout=None: sent.append(req) or contextlib.nullcontext())
            m.setattr(time, "sleep", sleep)
            m.setattr(time, "monotonic", lambda: now[0])
            body = self.bodies.get(node_type)
            if body is None:
                module = load_container(node_type)
                for name, sdk in (("io", io), ("log", log), ("cost", cost)):
                    # a module first loaded under tests/containers' mocks still holds them; quantize has no cost
                    m.setattr(module, name, sdk, raising=False)
                body = module.main
            try:
                body()
                code = 0
            except SystemExit as e:
                code = 0 if e.code is None else e.code if isinstance(e.code, int) else 1
            except Exception as e:
                io._excepthook(type(e), e, e.__traceback__)  # the SDK logs an uncaught exception as ERROR
                code = 1
            io._at_exit()  # cost_json, then logs
        for req in sent:  # in the order the SDK sent them
            r = await self.client.post(req.full_url.removeprefix(env["ORCHAPOD_CONTROL_URL"]), content=req.data,
                                       headers=dict(req.header_items()))
            assert r.is_success, (req.full_url, r.status_code, r.text)
        return code if self.name == "local-docker" else await self.job_ends(pod, code)

    async def job_ends(self, pod: Pod, code: int) -> int:
        """GET /jobs/<id> as Nebius would answer once the node exited `code` (the shape tests/providers/test_nebius.py records; the
        cause's wording is a fake until G2): COMPLETED, or FAILED with a code, a message and a console link. NebiusProvider.wait
        turns that into 0 or 1 and Pod.error."""
        status = {"state": "COMPLETED"} if code == 0 else {"state": "FAILED", "stateDetails": {
            "code": "ContainerFailed", "message": f"exit code {code}, see https://console.nebius.com/jobs/{pod.pod_id}"}}
        job = {"metadata": {"id": pod.pod_id}, "status": status}
        http = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=job)))
        return await NebiusProvider(http=http).wait(pod)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """Default caps, no STUB; the keys are fakes that only reach the in-process fakes below."""
    for name in ("STUB", "NEBIUS_BASE_URL", "ORCHAPOD_KILL_SWITCH", "ORCHAPOD_ANON_SCALE", "ORCHAPOD_MAX_RUN_USD",
                 "ORCHAPOD_MAX_DAY_USD", "ORCHAPOD_NODE_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {"NEBIUS_API_KEY": "tf-key", "TAVILY_API_KEY": "tvly-key", "ORCHAPOD_ADMIN_TOKEN": "drill-admin",
                        "NEBIUS_IAM_TOKEN": "iam-drill"}.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def bucket(monkeypatch) -> dict[str, bytes]:
    """Object storage in memory: the SDK uploads into it and downloads from it. read_inputs() arms no atexit or SIGTERM
    hook in pytest; Nodes.wait runs the exit hook itself."""
    objects: dict[str, bytes] = {}

    def upload(local_path: Path, r2_key: str) -> None:
        for f in [p for p in local_path.rglob("*") if p.is_file()] if local_path.is_dir() else [local_path]:
            objects[f"{r2_key}/{f.relative_to(local_path)}" if local_path.is_dir() else r2_key] = f.read_bytes()

    monkeypatch.setattr(io, "_upload_to_r2", upload)
    monkeypatch.setattr(io, "_download_from_r2", lambda r2_key, dest: Path(dest).write_bytes(objects[r2_key]))
    monkeypatch.setattr(io, "_arm", lambda: None)
    return objects


@pytest.fixture
def drill(db, client, bucket, monkeypatch, tmp_path):
    """run(nodes, inputs, headers) and retry(run_id, node_id, headers) through the API, each to the run's end → its summary.
    cpu and api nodes run on `local`, gpu nodes on `gpu`."""
    monkeypatch.setattr("api.database.AsyncSessionLocal", async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False))
    tasks, launch = [], ex.launch
    monkeypatch.setattr(ex, "launch", lambda run_id, scale: tasks.append(launch(run_id, scale)) or tasks[-1])
    local, gpu = Nodes("local-docker", client, tmp_path), Nodes("nebius", client, tmp_path)

    async def pick_local(resources):
        return local, None

    async def pick_gpu(resources):
        return gpu, GPUSpec(gpu_type="H100")

    monkeypatch.setattr("api.services.provider_selector.pick_local_docker", pick_local)
    monkeypatch.setattr("api.services.provider_selector.pick_provider", pick_gpu)

    async def to_the_end(r: httpx.Response, run_id: str) -> dict:
        assert r.status_code in (200, 202), r.text
        await asyncio.wait_for(tasks[-1], 30)
        return (await client.get(f"/runs/{run_id}/summary")).json()

    async def run(nodes: list[dict], inputs: dict | None = None, headers: dict | None = None) -> dict:
        wf = await client.post("/workflows", json={"name": "drill", "yaml": yaml.safe_dump({"name": "drill", "nodes": nodes})})
        run_id = (await client.post("/runs", json={"workflow_id": wf.json()["id"], "inputs": inputs or {}})).json()["id"]
        return await to_the_end(await client.post(f"/runs/{run_id}/start", headers=headers), run_id)

    async def retry(run_id: str, node_id: str, headers: dict | None = None) -> dict:
        return await to_the_end(await client.post(f"/runs/{run_id}/nodes/{node_id}/retry", headers=headers), run_id)

    return SimpleNamespace(local=local, gpu=gpu, run=run, retry=retry)


def fake(monkeypatch, node_type: str, client_class, answer) -> list[httpx.Request]:
    """The node's Token Factory or Tavily client, answered in-process by answer(request); returns the requests sent."""
    seen = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer(request)

    http = httpx.Client(transport=httpx.MockTransport(record))
    monkeypatch.setattr(load_container(node_type), client_class.__name__, lambda **kw: client_class(http=http, **kw))
    return seen


def completion(content: str, model: str, in_tokens: int, out_tokens: int) -> httpx.Response:
    return httpx.Response(200, json={
        "id": "chatcmpl-drill", "object": "chat.completion", "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": in_tokens, "completion_tokens": out_tokens, "total_tokens": in_tokens + out_tokens}})


def states(summary: dict) -> list[tuple]:
    return [(n["node_id"], n["status"], n["error"]) for n in summary["nodes"]]


# --- the run recovers or fails with a readable node error -------------------------------------------------------------

async def test_token_factory_429_then_success_recovers_and_bills_one_call(drill, monkeypatch):
    rows = [{"user_id": f"u{i}", "movie_title": f"Movie {i}", "action": "like", "timestamp": "2026-05-01T20:15:00Z",
             "device": "tv"} for i in range(10)]
    answers = iter([httpx.Response(429, headers={"Retry-After": "2"}, json={"detail": "Rate limit exceeded"}),
                    completion(json.dumps({"rows": rows}), SUPER, 900, 700)])
    seen = fake(monkeypatch, "synth-distilabel", TokenFactory, lambda request: next(answers))

    s = await drill.run([{"id": "synth", "type": "synth-distilabel", "inputs": {
        "pipeline_template": "structured", "n_samples": 10, "max_tokens": 2500, "row_schema": MOVIE_ROW}}])

    assert (s["status"], s["error"], states(s)) == ("succeeded", None, [("synth", "succeeded", None)])
    assert (len(seen), drill.local.sleeps) == (2, [2.0])  # the client waited the Retry-After, then sent it again
    assert s["cost_usd"] == pytest.approx((900 * 0.30 + 700 * 0.90) / 1e6)  # one call billed: a 429 costs nothing
    assert {a["name"] for a in s["artifacts"]} == {"dataset", "metrics_json", "cost_json", "logs"}


def tf_job(status: str, **fields) -> dict:
    return {"id": "ftjob-1", "object": "fine_tuning.job", "model": LLAMA, "status": status, "error": None, **fields}


@pytest.mark.parametrize("ended, error", [
    (tf_job("failed", error={"code": "invalid_training_file",
                             "message": "train.jsonl line 3: the last message must be from the assistant"}),
     "exit 1: Token Factory job ftjob-1 failed: train.jsonl line 3: the last message must be from the assistant"),
    (tf_job("cancelled"), "exit 1: Token Factory job ftjob-1 cancelled: no message"),
], ids=["failed", "cancelled"])
async def test_a_fine_tune_job_that_ends_failed_or_cancelled_fails_its_node(drill, bucket, monkeypatch, ended, error):
    monkeypatch.setitem(PRICES["token_factory_finetune"], LLAMA, 1e-6)  # a placeholder: spike 1 brings the real rate
    bucket["runs/seed/prep/train_jsonl"] = (json.dumps(CHAT_ROW) + "\n").encode() * 3
    routes = {("GET", "/v1/fine_tuning/jobs"): {"data": []},  # R19: no earlier job of this node to adopt
              ("POST", "/v1/files"): {"id": "file-train"}, ("POST", "/v1/fine_tuning/jobs"): tf_job("validating_files"),
              ("GET", "/v1/fine_tuning/jobs/ftjob-1"): ended, ("GET", "/v1/fine_tuning/jobs/ftjob-1/events"): {"data": []}}
    seen = fake(monkeypatch, "tf-finetune", TokenFactory, lambda r: httpx.Response(200, json=routes[(r.method, r.url.path)]))

    s = await drill.run([
        {"id": "finetune", "type": "tf-finetune", "inputs": {"train_data": "${{ inputs.train }}"}},
        {"id": "deploy", "type": "tf-deploy", "needs": ["finetune"], "inputs": {"job": "${{ nodes.finetune.outputs.job }}"}},
    ], {"train": f"r2://{BUCKET}/runs/seed/prep/train_jsonl"})

    assert (s["status"], s["error"]) == ("failed", error)
    assert states(s) == [("finetune", "failed", error), ("deploy", "pending", None)]
    assert not [r for r in seen if r.url.path.endswith("/cancel")]  # it ended on Token Factory: nothing left to cancel


async def test_a_judge_that_times_out_fails_its_node_after_writing_the_summary(drill, bucket, monkeypatch):
    monkeypatch.setitem(PRICES["token_factory"], LLAMA, {"in": 0.02, "out": 0.06})  # a placeholder: spike 1
    bucket["runs/seed/prep/test_jsonl"] = (json.dumps(CHAT_ROW) + "\n").encode() * 2

    def answer(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        if model == ULTRA:
            raise httpx.ReadTimeout("The read operation timed out", request=request)
        return completion(f"{model}: an L40S.", model, 300, 100)

    seen = fake(monkeypatch, "judge-eval", TokenFactory, answer)
    tuned = {"base_url": "https://api.tokenfactory.nebius.com/v1", "model": "orchapod-drill-lora",
             "api_key_env": "NEBIUS_API_KEY", "base_model": LLAMA}  # tf-deploy's model_ref

    s = await drill.run([{"id": "evaluate", "type": "judge-eval", "inputs": {
        "test_data": "${{ inputs.test }}", "base_model_ref": LLAMA, "tuned_model_ref": tuned, "max_samples": 2}}],
        {"test": f"r2://{BUCKET}/runs/seed/prep/test_jsonl"})

    error = ("exit 1: 2 of 2 rows failed (more than 10%); first: judge: token_factory server None: "
             "ReadTimeout('The read operation timed out')")
    assert (s["status"], s["error"], states(s)) == ("failed", error, [("evaluate", "failed", error)])
    summary = next(a["meta"] for a in s["artifacts"] if a["name"] == "eval_summary")  # written before it failed
    assert (summary["n"], summary["judged"], summary["errors"]) == (2, 0, 2)
    assert sum(json.loads(r.content)["model"] == ULTRA for r in seen) == 2 * 4  # per row: one order, the client's 4 tries
    assert s["cost_usd"] == pytest.approx(4 * (300 * 0.02 + 100 * 0.06) / 1e6)  # the 4 answers; a timeout bills nothing


TAVILY_OUT_OF_CREDITS = ('{"detail":{"error":"This request exceeds your plan\'s set usage limit. Please upgrade your plan '
                         'or contact support@tavily.com"}}')


async def test_tavily_out_of_credits_fails_research_with_tavilys_words(drill, monkeypatch):
    seen = fake(monkeypatch, "web-research", Tavily, lambda r: httpx.Response(432, content=TAVILY_OUT_OF_CREDITS.encode()))

    s = await drill.run([
        {"id": "research", "type": "web-research", "inputs": {"queries": ["Nebius Serverless Jobs"], "max_pages": 5}},
        {"id": "synth", "type": "synth-distilabel", "needs": ["research"],
         "inputs": {"pipeline_template": "grounded", "corpus": "${{ nodes.research.outputs.corpus }}"}},
    ])

    error = f"exit 1: tavily quota 432: {TAVILY_OUT_OF_CREDITS}"
    assert (s["status"], s["error"], s["cost_usd"]) == ("failed", error, 0)
    assert states(s) == [("research", "failed", error), ("synth", "pending", None)]
    assert len(seen) == 1  # out of credits is not retried


async def test_a_preempted_serverless_job_fails_the_run_and_retry_resumes_from_the_newest_checkpoint(drill):
    resumed_from = []

    def unsloth_train():  # Lane B's training Job, through the SDK as the container would call it
        if (resume := checkpoint.latest_checkpoint_uri()) is None:
            for step in (100, 200):
                (ckpt := io.local_path(f"checkpoint-{step}")).mkdir()
                (ckpt / "adapter_model.safetensors").write_bytes(b"weights")
                checkpoint.save_checkpoint(step, ckpt)
            raise SystemExit(143)  # preempted: SIGTERM, which the SDK raises as SystemExit(143); the Job ends FAILED
        resumed_from.append(resume)
        (adapter := io.local_path("lora_adapter")).mkdir()
        (adapter / "adapter_model.safetensors").write_bytes(b"weights")
        io.write_output("lora_adapter", adapter, kind="model", metadata={"format": "peft", "base_model": STUDENT})

    drill.gpu.bodies["unsloth-train"] = unsloth_train
    nodes = [{"id": "train", "type": "unsloth-train", "inputs": {"model": STUDENT, "train_data": "${{ inputs.train }}"}}]

    s = await drill.run(nodes, {"train": f"r2://{BUCKET}/runs/seed/prep/train_jsonl"}, ADMIN)  # gpu nodes: admin only
    # What the run page shows: NebiusProvider.wait's Pod.error ("<STATE> <code>: <message>", URLs hidden), which the executor
    # shows in place of "exit 1" when the node logged no ERROR line (a SIGTERM logs none).
    error = "FAILED ContainerFailed: exit code 143, see <hidden>"
    assert (s["status"], s["error"], states(s)) == ("failed", error, [("train", "failed", error)])

    s = await drill.retry(s["run_id"], "train", ADMIN)

    assert (s["status"], s["error"], states(s)) == ("succeeded", None, [("train", "succeeded", None)])
    assert resumed_from == [f"r2://{BUCKET}/runs/{s['run_id']}/train/checkpoint_step_000200"]


# --- refusals a visitor of the public app can hit (anonymous: ORCHAPOD_ANON_SCALE 0.1) --------------------------------

def one_node(node_type: str, **inputs) -> str:
    return yaml.safe_dump({"name": "visitor", "nodes": [{"id": "n", "type": node_type, "inputs": inputs}]})


async def a_run(client, yaml_text: str) -> tuple[str, str]:
    wf = (await client.post("/workflows", json={"name": "visitor", "yaml": yaml_text})).json()
    return wf["id"], (await client.post("/runs", json={"workflow_id": wf["id"], "inputs": {}})).json()["id"]


async def test_a_spent_day_share_refuses_plan_and_start_with_the_budget_sentence(client, db, monkeypatch):
    db.add(Spend(source="compare", usd=Decimal("1.5")))  # ORCHAPOD_MAX_DAY_USD $15 × ORCHAPOD_ANON_SCALE 0.1, spent
    await db.commit()
    monkeypatch.setattr(ex, "launch", lambda *_: pytest.fail("a refused run must not launch"))

    plan = await client.post("/agent/plan", json={"intent": INTENT_2})  # refused before Token Factory is called
    _, run_id = await a_run(client, one_node("data-prep", dataset="hf://openai/gsm8k"))
    start = await client.post(f"/runs/{run_id}/start")

    assert (plan.status_code, plan.json()["detail"]) == (402, "day cap $1.5: nothing left")
    assert (start.status_code, start.json()["detail"]) == (402, "day cap $1.5: $0.00 left")


async def test_a_plan_above_the_run_cap_is_refused_with_what_it_needs(client, monkeypatch):
    monkeypatch.setattr(ex, "launch", lambda *_: pytest.fail("a refused run must not launch"))
    plan = {"name": "big-qa", "nodes": [{"id": "synth", "type": "synth-distilabel", "needs": [], "inputs": {
        "pipeline_template": "self-instruct", "n_samples": 2000, "max_usd": 1.0}}]}  # no GPU node: that would be a 403
    need = planner.review(plan)[2]["usd"]
    assert need > 0.30, "the drill needs a plan above the anonymous run cap ($3 × 0.1)"

    r = await client.post("/agent/run", json={"intent": "Q&A pairs about sourdough baking", "plan": plan})

    assert (r.status_code, r.json()["detail"]) == (402, f"run cap $0.3: $0.30 left, the plan needs ${need:.2f}")


async def test_the_sixth_plan_from_one_address_gets_429_with_retry_after(client, monkeypatch):
    monkeypatch.setenv("STUB", "1")  # the planner answers with the canonical template: no model call
    monkeypatch.setattr(ratelimit, "monotonic", lambda: 1000.0)  # the six arrive in the same instant: no refill

    replies = [await client.post("/agent/plan", json={"intent": INTENT_2}) for _ in range(6)]

    assert [r.status_code for r in replies] == [200] * 5 + [429]
    assert replies[-1].headers["retry-after"] == "12"
    assert replies[-1].json()["detail"] == "too many requests from your address; try again in 12 s"


async def test_a_workflow_with_runs_is_read_only_to_visitors(client):
    workflow_id, _ = await a_run(client, one_node("data-prep", dataset="hf://openai/gsm8k"))

    put = await client.put(f"/workflows/{workflow_id}", json={"name": "renamed"})
    delete = await client.delete(f"/workflows/{workflow_id}")

    detail = "this workflow has runs, so it is read-only on the public app; save a copy as a new workflow"
    assert [(r.status_code, r.json()["detail"]) for r in (put, delete)] == [(409, detail)] * 2
    assert (await client.put(f"/workflows/{workflow_id}", json={"name": "renamed"}, headers=ADMIN)).status_code == 200


async def test_a_gpu_node_is_refused_to_visitors(client, monkeypatch):
    monkeypatch.setattr(ex, "launch", lambda *_: pytest.fail("a refused run must not launch"))
    _, run_id = await a_run(client, one_node("unsloth-train", model=STUDENT, train_data="r2://b/runs/x/prep/train_jsonl"))

    r = await client.post(f"/runs/{run_id}/start")

    assert (r.status_code, r.json()["detail"]) == (
        403, "unsloth-train runs on a rented GPU, billed by the hour: only the admin can start it on the public app")
