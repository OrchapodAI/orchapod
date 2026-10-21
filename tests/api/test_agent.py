"""Orchapod Agent API per contracts "Agent API": plan, run, report, templates, and /workflows/from-prompt."""

from __future__ import annotations

import functools
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import yaml
from pydantic import BaseModel
from sqlmodel import select

from api.agent import planner
from api.executor import run_workflow as ex
from api.models.db import AgentRun, Artifact, ArtifactKind, NodeRun, NodeStatus, Run, RunStatus, Spend, Workflow
from api.services import budget
from packages.providers.tokenfactory import LIGHTNING, SUPER, TokenFactory
from packages.workflow_schema.models import NODE_REGISTRY, SynthDistilabelInputs

INTENTS = [  # the /agent page's examples (apps/web/app/agent/page.tsx)
    "Fine-tune Llama 3B on US real-estate compliance: Fair Housing Act, RESPA, TILA/TRID, state licensing",
    "Generate synthetic data of movie likes, shares and subscribes",
    "Quantize a model which is an expert in maths",
]
GOOD = {"name": "qa-data", "nodes": [  # valid with the nodes on this branch's base
    {"id": "synth", "type": "synth-distilabel", "needs": [], "inputs": {"pipeline_template": "self-instruct", "n_samples": 100}},
    {"id": "prep", "type": "data-prep", "needs": ["synth"], "inputs": {"dataset": "${{ nodes.synth.outputs.dataset }}"}},
]}
TF_BASE = "https://api.tokenfactory.nebius.com/v1"


def node(id, type, needs=(), **inputs):
    return {"id": id, "type": type, "needs": list(needs), "inputs": inputs}


def errors_of(plan):
    return planner.review(plan)[0]


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k in ("STUB", "ORCHAPOD_KILL_SWITCH", "ORCHAPOD_ADMIN_TOKEN", "ORCHAPOD_ANON_SCALE", "ORCHAPOD_MAX_RUN_USD",
              "ORCHAPOD_MAX_DAY_USD", "NEBIUS_BASE_URL", "NEBIUS_PROJECT_ID", "NEBIUS_IAM_TOKEN", "VASTAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NEBIUS_API_KEY", "test-key")


@pytest.fixture
def tf(monkeypatch):
    """Token Factory on httpx.MockTransport: `replies` answer in order; `requests` (bodies) and `calls`
    (chat kwargs) record what went out."""
    fake = SimpleNamespace(replies=[], requests=[], calls=[])

    def handler(request):
        fake.requests.append(json.loads(request.content))
        status, content = fake.replies.pop(0)
        if status != 200:
            return httpx.Response(status, json={"detail": content})
        return httpx.Response(200, json={"model": "m", "usage": {"prompt_tokens": 5000, "completion_tokens": 800},
                                         "choices": [{"index": 0, "finish_reason": "stop",
                                                      "message": {"role": "assistant", "content": content}}]})

    class SpyTF(TokenFactory):
        def chat(self, messages, model=SUPER, **kw):
            fake.calls.append(dict(kw))
            kw.pop("read_timeout", None)  # platform-w2 makes it a client option; until then keep it out of the body
            return super().chat(messages, model, **kw)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(budget, "TokenFactory", functools.partial(SpyTF, http=http))
    return fake


def answer(plan, rationale="r"):
    return 200, json.dumps({"rationale": rationale, "plan": plan})


# --- templates and STUB ----------------------------------------------------------

async def test_templates_are_the_three_canonical_intents(client):
    templates = (await client.get("/agent/templates")).json()

    assert [t["intent"] for t in templates] == INTENTS
    for t in templates:
        assert {"slug", "title", "intent", "plan", "estimate"} <= set(t)
        assert set(t["estimate"]["by_node"]) == {n["id"] for n in t["plan"]["nodes"]}
    assert 0 < templates[1]["estimate"]["usd"] <= 0.3  # intent #2 fits the anonymous run cap ($3 x 0.1)
    assert templates[0]["estimate"]["usd"] < 3


@pytest.mark.skipif("structured" not in json.dumps(SynthDistilabelInputs.model_json_schema()["properties"]["pipeline_template"]),
                    reason="waits for data-w2's synth-distilabel `structured` template")
def test_intent_2_runs_on_the_nodes_that_exist():
    assert planner.review(planner.templates()[1]["plan"])[:2] == ([], [])


async def test_stub_plans_with_the_closest_template_and_calls_nothing(client, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.delenv("NEBIUS_API_KEY")
    monkeypatch.setattr(budget, "control_plane", None)  # a model call would crash
    templates = planner.templates()

    for intent, t in zip(INTENTS, templates):
        r = await client.post("/agent/plan", json={"intent": intent})
        assert r.status_code == 200
        assert set(r.json()) == {"plan", "rationale", "estimate", "warnings", "errors"}
        assert r.json()["plan"] == t["plan"] and r.json()["rationale"].startswith("STUB=1")
    r = await client.post("/agent/plan", json={"intent": "make me a GGUF of a math model"})
    assert r.json()["plan"] == templates[2]["plan"]


async def test_plan_refuses_bad_intents_the_kill_switch_and_a_missing_key(client, monkeypatch):
    assert (await client.post("/agent/plan", json={"intent": "  "})).status_code == 422
    assert (await client.post("/agent/plan", json={"intent": "x" * 2001})).status_code == 422
    monkeypatch.setenv("ORCHAPOD_KILL_SWITCH", "1")
    assert (await client.post("/agent/plan", json={"intent": INTENTS[1]})).status_code == 503
    monkeypatch.delenv("ORCHAPOD_KILL_SWITCH")
    monkeypatch.setenv("NEBIUS_API_KEY", " ")
    r = await client.post("/agent/plan", json={"intent": INTENTS[1]})
    assert r.status_code == 503 and "NEBIUS_API_KEY" in r.json()["detail"]


# --- the planner on Token Factory ---------------------------------------------

async def test_nemotron_super_plans_and_repairs_validation_errors(client, db, tf):
    bad = {**GOOD, "nodes": [node("synth", "synth-distilabel", teacher_model="gpt-4o", n_samples=100), GOOD["nodes"][1]]}
    tf.replies = [answer(bad), answer(GOOD, "Synthesise, then prepare.")]

    r = await client.post("/agent/plan", json={"intent": "Q&A pairs about sourdough baking"})

    body = r.json()
    assert (r.status_code, body["plan"], body["rationale"], body["errors"]) == (200, GOOD, "Synthesise, then prepare.", [])
    assert body["estimate"] == planner.estimate(GOOD)[0]
    first, repair = tf.requests
    assert (first["model"], first["temperature"], first["max_tokens"]) == (SUPER, 0.0, 4096)
    assert first["chat_template_kwargs"] == {"enable_thinking": False}
    assert first["response_format"]["type"] == "json_schema" and first["response_format"]["json_schema"]["strict"]
    system = first["messages"][0]["content"]
    assert "Expected plans for the canonical intents" in system  # docs/agent_knowledge.md, read per request
    assert "- data-prep (cpu" in system and "lm-eval" not in system  # NODE_REGISTRY, hidden rows left out
    assert "synth: teacher_model" in repair["messages"][-1]["content"]
    assert [c["read_timeout"] for c in tf.calls] == [300, 300]  # a slow plan is never re-sent and billed twice
    assert await budget.spent_today(db) == pytest.approx(2 * (5000 * 0.30 + 800 * 0.90) / 1e6)  # day ledger (R6)


async def test_the_planner_stops_after_two_repairs(client, tf):
    tf.replies = [answer({"name": "x", "nodes": [node("Bad-Id", "data-prep", dataset="hf://x")]})] * 3
    body = (await client.post("/agent/plan", json={"intent": "anything"})).json()
    assert len(tf.requests) == 3
    assert body["errors"] == ["Bad-Id: id must be snake_case ([a-z][a-z0-9_]*)"]


async def test_token_factory_failures_are_502(client, tf):
    tf.replies = [(400, "model not found")]
    r = await client.post("/agent/plan", json={"intent": "anything"})
    assert r.status_code == 502 and r.json()["detail"].startswith("token_factory bad_request 400")


async def test_planning_stops_when_the_day_budget_is_spent(client, db, tf):
    db.add(Spend(source="planner", usd=Decimal("1.5")))  # the anonymous day cap: $15 x 0.1
    await db.commit()
    assert (await client.post("/agent/plan", json={"intent": "anything"})).status_code == 402
    assert tf.requests == []


# --- validation ------------------------------------------------------------------

def test_review_checks_structure_refs_and_input_schemas():
    errors = errors_of({"name": "p", "nodes": [
        node("a", "data-prep", dataset="hf://x"),
        node("b", "data-prep", ["a"], dataset="${{ nodes.a.outputs.nope }}"),
        node("c", "data-prep", dataset="${{ nodes.a.outputs.dataset }}"),
        node("d", "data-prep", ["zz"], dataset="${{ inputs.uri }}"),
        node("e", "data-prep", ["a"], dataset="x ${{ nodes.a.outputs.dataset }}", colour="red", train_split="most"),
        node("f", "lm-eval"),
        node("g", "nope"),
        node("Bad", "data-prep", dataset="hf://x"),
        node("h", "synth-distilabel", ["a"], teacher_model="gpt-4o", seed_prompts=["${{ nodes.a.outputs.dataset }}"]),
        node("t", "unsloth-train", train_data="r2://b/train"),
    ]})

    for expected in [
        "b: dataset: a (data-prep) has no output 'nope'",
        "c: dataset: refs node 'a', which is not in needs",
        "d: needs unknown node 'zz'",
        "d: dataset: plans have no workflow inputs (${{ inputs.uri }})",
        "e: unknown input 'colour'",
        "e: dataset: a ref must be exactly one ${{ nodes.<id>.outputs.<name> }}",
        "f: unknown node type 'lm-eval'",  # hidden: the agent never plans it
        "g: unknown node type 'nope'",
        "Bad: id must be snake_case ([a-z][a-z0-9_]*)",
        "h: seed_prompts: refs resolve only at the top level of inputs",
        "t: no GPU provider is configured (set NEBIUS_PROJECT_ID)",
    ]:
        assert expected in errors
    assert any(e.startswith("e: train_split: ") for e in errors)
    assert any(e.startswith("h: teacher_model must be a Nemotron model on Token Factory") for e in errors)
    assert errors_of({"name": "p", "nodes": [node("a", "data-prep", ["b"], dataset="hf://x"),
                                             node("b", "data-prep", ["a"], dataset="hf://x")]}) == [
        "plan: Workflow YAML contains a cycle — DAGs must be acyclic."]
    assert errors_of({"name": "p", "nodes": [node("a", "data-prep", dataset="hf://x")] * 2}) == [
        "plan: node ids must be unique (a)"]
    assert errors_of({"name": "p", "nodes": []})[0].startswith("plan: nodes: ")
    assert errors_of("not a plan")[0].startswith("plan: ")
    assert errors_of(GOOD) == []


class _Out(BaseModel):
    job: str = ""
    lora_adapter: str = ""
    model_ref: str = ""


class _Finetune(BaseModel):
    model: str = "meta-llama/Llama-3.1-8B-Instruct"
    train_data: str


class _Deploy(BaseModel):
    job: dict | str


class _Judge(BaseModel):
    test_data: str
    base_model_ref: dict | str
    tuned_model_ref: dict | str
    judge_model: str = "nvidia/Nemotron-3-Ultra-550b-a55b"


def test_review_enforces_the_knowledge_constraints(monkeypatch):
    for t, schema in (("tf-finetune", _Finetune), ("tf-deploy", _Deploy), ("judge-eval", _Judge)):
        monkeypatch.setitem(NODE_REGISTRY, t, {"description": t, "inputs_schema": schema, "outputs_schema": _Out,
                                               "runtime": "api"})
    tf_ref = {"base_url": TF_BASE, "model": "meta-llama/Llama-3.1-8B-Instruct", "api_key_env": "NEBIUS_API_KEY",
              "base_model": None}
    plan = {"name": "p", "nodes": [
        node("nemo", "tf-finetune", model="nvidia/Llama-3.1-Nemotron-Nano-8B-v1", train_data="r2://b/t"),
        node("small", "tf-finetune", model="meta-llama/Llama-3.2-3B-Instruct", train_data="r2://b/t"),
        node("big", "tf-finetune", train_data="r2://b/t"),
        node("dep_small", "tf-deploy", ["small"], job="${{ nodes.small.outputs.job }}"),
        node("dep_big", "tf-deploy", ["big"], job="${{ nodes.big.outputs.job }}"),
        node("judge", "judge-eval", test_data="r2://b/test", judge_model="meta-llama/Llama-3.3-70B-Instruct",
             base_model_ref={**tf_ref, "base_url": "https://attacker.example/v1"},
             tuned_model_ref={**tf_ref, "api_key_env": "ORCHAPOD_ENDPOINT_TOKEN", "base_url": "https://e.example/v1"}),
        node("fair", "judge-eval", test_data="r2://b/test", base_model_ref=tf_ref, tuned_model_ref="meta-llama/x"),
    ]}

    errors, warnings, _ = planner.review(plan)

    assert [e.split(":")[0] for e in errors] == ["nemo", "dep_small", "judge", "judge", "judge"]
    assert errors[0].startswith("nemo: Token Factory does not fine-tune nvidia/Llama-3.1-Nemotron-Nano-8B-v1")
    assert errors[1] == ("dep_small: Token Factory has no per-token LoRA deploy for meta-llama/Llama-3.2-3B-Instruct: "
                         "serve the tf-finetune lora_adapter with vllm-serve")
    assert errors[2].startswith("judge: base_model_ref: refused ModelRef")
    assert errors[3].startswith("judge: tuned_model_ref: refused ModelRef")
    assert errors[4].startswith("judge: judge_model must be a Nemotron model on Token Factory")
    assert any(w.startswith("dep_big: per-token LoRA deploy is unverified") for w in warnings)
    assert any(w.startswith("big: no fine-tune price") for w in warnings)


def test_review_reports_an_estimate_over_the_budget_left():
    errors, _, estimate = planner.review(GOOD, (0.01, "run", 0.3))
    assert errors == [f"plan: the estimate ${estimate['usd']:.2f} is more than the $0.01 left (run cap $0.3)"]


# --- run and report --------------------------------------------------------------

async def test_run_validates_again_and_launches(client, db, monkeypatch):
    launched = []
    monkeypatch.setattr(ex, "launch", lambda run_id, scale=1.0: launched.append((run_id, scale)))

    r = await client.post("/agent/run", json={"intent": "Q&A data", "plan": GOOD})

    assert r.status_code == 201
    body = r.json()
    run, workflow = await db.get(Run, uuid.UUID(body["run_id"])), await db.get(Workflow, uuid.UUID(body["workflow_id"]))
    assert yaml.safe_load(workflow.yaml) == GOOD and len(workflow.graph_json["nodes"]) == 2  # opens on the canvas
    assert (run.workflow_id, run.status) == (workflow.id, RunStatus.PROVISIONING_GPU)
    stored = await db.get(AgentRun, run.id)
    assert (stored.intent, stored.plan, stored.estimate, stored.report_md) == ("Q&A data", GOOD, body["estimate"], None)
    assert launched == [(run.id, 0.1)]  # anonymous caller

    r = await client.post("/agent/run", json={"intent": "x", "plan": {"name": "x", "nodes": [node("a", "nope")]}})
    assert (r.status_code, r.json()) == (422, {"detail": "the plan has errors", "errors": ["a: unknown node type 'nope'"]})
    assert (await client.post("/agent/run", json={"intent": "x", "plan": {"name": "x", "nodes": []}})).status_code == 422
    monkeypatch.setenv("ORCHAPOD_KILL_SWITCH", "1")
    assert (await client.post("/agent/run", json={"intent": "x", "plan": GOOD})).status_code == 503
    monkeypatch.delenv("ORCHAPOD_KILL_SWITCH")
    monkeypatch.setenv("ORCHAPOD_ANON_SCALE", "0.001")  # a $0.003 run cap, below the plan's estimate
    assert (await client.post("/agent/run", json={"intent": "x", "plan": GOOD})).status_code == 402
    assert len(launched) == 1


async def agent_run(db, status):
    wf = Workflow(user_id=uuid.uuid4(), name="qa-data", yaml=yaml.safe_dump(GOOD), graph_json={})
    db.add(wf)
    await db.flush()
    run = Run(workflow_id=wf.id, user_id=wf.user_id, status=status, cost_usd=Decimal("0.02"))
    db.add(run)
    await db.flush()
    prep = NodeRun(run_id=run.id, node_id="prep", node_type="data-prep", status=NodeStatus.SUCCEEDED)
    db.add_all([NodeRun(run_id=run.id, node_id="synth", node_type="synth-distilabel", status=NodeStatus.SUCCEEDED), prep])
    await db.flush()
    db.add(Artifact(node_run_id=prep.id, name="dataset", kind=ArtifactKind.DATASET, uri="r2://b/runs/x/prep/dataset"))
    db.add(AgentRun(run_id=run.id, intent="Q&A data", plan=GOOD, estimate={"usd": 0.03, "minutes": 4.5, "by_node": {}}))
    await db.commit()
    return run


async def test_report_waits_for_a_terminal_run_then_lightning_writes_it_once(client, db, tf):
    run = await agent_run(db, RunStatus.RUNNING)
    r = (await client.get(f"/agent/runs/{run.id}/report")).json()
    assert (r["ready"], r["markdown"], r["intent"], r["status"]) == (False, None, "Q&A data", "running")
    assert {"run_id", "cost_usd", "error", "nodes", "artifacts", "estimate"} <= set(r)

    run.status = RunStatus.SUCCEEDED
    await db.commit()
    tf.replies = [(200, "## What ran\nsynth, then prep")]
    r = (await client.get(f"/agent/runs/{run.id}/report")).json()

    assert (r["ready"], r["markdown"]) == (True, "## What ran\nsynth, then prep")
    assert tf.requests[0]["model"] == LIGHTNING and "Q&A data" in tf.requests[0]["messages"][1]["content"]
    assert (await client.get(f"/agent/runs/{run.id}/report")).json()["markdown"] == r["markdown"]
    assert len(tf.requests) == 1  # cached in the DB (R8)
    ledger = (await db.scalars(select(Spend).where(Spend.source == "reporter"))).all()
    assert [float(x.usd) for x in ledger] == [pytest.approx((5000 * 0.06 + 800 * 0.24) / 1e6)]  # day ledger (R6)
    assert (await client.get(f"/agent/runs/{uuid.uuid4()}/report")).status_code == 404


async def test_report_falls_back_to_the_template(client, db, monkeypatch, tf):
    failed = await agent_run(db, RunStatus.FAILED)
    tf.replies = [(400, "no such model")]
    md = (await client.get(f"/agent/runs/{failed.id}/report")).json()["markdown"]
    assert md.startswith("## qa-data: failed") and "Q&A data" in md and "$0.0200 of $0.03 estimated" in md

    monkeypatch.setenv("STUB", "1")
    done = await agent_run(db, RunStatus.SUCCEEDED)
    md = (await client.get(f"/agent/runs/{done.id}/report")).json()["markdown"]
    assert "[prep/dataset](/artifacts/" in md and len(tf.requests) == 1  # STUB calls nothing


async def test_retry_clears_the_cached_report(client, db, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.setattr(ex, "launch", lambda run_id, scale=1.0: None)
    run = await agent_run(db, RunStatus.FAILED)
    prep = (await db.scalars(select(NodeRun).where(NodeRun.run_id == run.id, NodeRun.node_id == "prep"))).one()
    prep.status, prep.error = NodeStatus.FAILED, "exit 1: boom"
    await db.commit()
    assert "exit 1: boom" in (await client.get(f"/agent/runs/{run.id}/report")).json()["markdown"]

    assert (await client.post(f"/runs/{run.id}/nodes/prep/retry")).status_code == 202
    stored = await db.get(AgentRun, run.id)
    await db.refresh(stored)
    assert stored.report_md is None  # the next terminal status gets a new report


async def test_from_prompt_drafts_with_the_same_planner(client, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    r = await client.post("/workflows/from-prompt", json={"prompt": INTENTS[1]})
    assert r.status_code == 201
    assert yaml.safe_load(r.json()["yaml"]) == planner.templates()[1]["plan"]
    assert r.json()["name"] == "movie-engagement-synthetic-data"
    assert (await client.post("/workflows/from-prompt", json={"prompt": " "})).status_code == 422
