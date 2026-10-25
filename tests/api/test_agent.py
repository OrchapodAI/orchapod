"""Orchapod Agent API per contracts "Agent API": plan, run, report, templates, and /workflows/from-prompt."""

from __future__ import annotations

import asyncio
import copy
import functools
import json
import re
import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import yaml
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlmodel import select

from api.agent import planner
from api.executor import run_workflow as ex
from api.routes import agent as agent_routes
from api.models.db import AgentRun, Artifact, ArtifactKind, NodeRun, NodeStatus, Run, RunStatus, Spend, Workflow, utcnow
from api.services import budget
from orchapod.prices import PRICES
from packages.providers.tokenfactory import SUPER, TokenFactory
from packages.workflow_schema.models import NODE_REGISTRY, ResourceSpec, SynthDistilabelInputs
from tests.api.test_executor import launched, provider  # noqa: F401 (fixtures)

INTENTS = [  # the /agent page's examples (apps/web/app/agent/page.tsx)
    "Fine-tune Llama 3B on US real-estate compliance: Fair Housing Act, RESPA, TILA/TRID, state licensing",
    "Generate synthetic data of movie likes, shares and subscribes",
    "Quantize a model which is an expert in maths",
]
DOCS = ("Distill a Nebius docs specialist: fine-tune NVIDIA Nemotron Nano 8B on the Nebius AI Cloud and Token Factory "
        "docs")  # golden path
DOCS_CPU = ("Distill a Nebius docs specialist and judge it on CPU without an endpoint: train Nemotron Nano 8B, then compare "
            "base and tuned")  # its variant without a GPU endpoint
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
        if isinstance(content, Exception):  # no reply: a timeout, a dropped connection
            raise content
        if isinstance(content, dict):  # a raw reply body, e.g. a malformed one
            return httpx.Response(status, json=content)
        if status != 200:
            return httpx.Response(status, json={"detail": content})
        return httpx.Response(200, json={"model": "m", "usage": {"prompt_tokens": 5000, "completion_tokens": 800},
                                         "choices": [{"index": 0, "finish_reason": "stop",
                                                      "message": {"role": "assistant", "content": content}}]})

    class SpyTF(TokenFactory):
        def chat(self, messages, model=SUPER, **kw):
            fake.calls.append(dict(kw))
            return super().chat(messages, model, **kw)

    http = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(budget, "TokenFactory", functools.partial(SpyTF, http=http))
    return fake


def answer(plan, rationale="r"):
    return 200, json.dumps({"rationale": rationale, "plan": plan})


# --- templates and STUB ----------------------------------------------------------

async def test_templates_are_the_three_canonical_intents_and_the_two_docs_specialists(client):
    templates = (await client.get("/agent/templates")).json()

    assert [t["intent"] for t in templates] == INTENTS + [DOCS, DOCS_CPU]
    for t in templates:
        assert {"slug", "title", "intent", "plan", "estimate"} <= set(t)
        assert set(t["estimate"]["by_node"]) == {n["id"] for n in t["plan"]["nodes"]}
    assert 0 < templates[1]["estimate"]["usd"] <= 0.3  # intent #2 fits the anonymous run cap ($3 x 0.1)
    assert all(t["estimate"]["usd"] < 3 for t in templates)  # the run cap


async def test_run_it_yourself_clones_each_template_at_reduced_scale(client, monkeypatch):
    templates = (await client.get("/agent/templates")).json()

    for t in templates:
        small = t["reduced"]
        assert set(small) == {"plan", "estimate"} and small["plan"]["name"] == t["plan"]["name"]
        for full, cut in zip(t["plan"]["nodes"], small["plan"]["nodes"], strict=True):  # the same pipeline ...
            assert {**full, "inputs": {}} == {**cut, "inputs": {}}
            assert cut["inputs"] == {**full["inputs"], **t["reduced_inputs"].get(full["id"], {})}  # ... smaller inputs
        assert set(t["reduced_inputs"]) <= {n["id"] for n in t["plan"]["nodes"]}
        assert 0 < small["estimate"]["usd"] < t["estimate"]["usd"]
    # gpu-l40s-a at $1.55/h for vllm-serve's ~5 min start + keep_alive_min (real-estate was $0.83 before the start was
    # billed); the docs specialist (Lane B) is mostly unsloth-train's typical 25 min of H100 ($1.88) plus that endpoint,
    # and its CPU variant the same training with no endpoint
    assert [round(t["reduced"]["estimate"]["usd"], 2) for t in templates] == [0.96, 0.03, 0.02, 2.32, 1.93]
    # fits: the reduced plan's estimate within the caller's run cap ($3 x ORCHAPOD_ANON_SCALE 0.1 when anonymous)
    assert [t["fits"] for t in templates] == [False, True, True, False, False]  # GPU templates: admin-only by default
    monkeypatch.setenv("ORCHAPOD_ADMIN_TOKEN", "s3cret")
    admin = (await client.get("/agent/templates", headers={"X-Orchapod-Admin": "s3cret"})).json()
    assert [t["fits"] for t in admin] == [True] * 5

    launched = []  # intent #2 at reduced scale runs for an anonymous caller ($3 x 0.1 run cap)
    monkeypatch.setattr(ex, "launch", lambda run_id, scale: launched.append(scale))
    r = await client.post("/agent/run", json={"intent": templates[1]["intent"], "plan": templates[1]["reduced"]["plan"]})
    assert (r.status_code, launched) == (201, [0.1])


@pytest.mark.skipif("structured" not in json.dumps(SynthDistilabelInputs.model_json_schema()["properties"]["pipeline_template"]),
                    reason="waits for data-w2's synth-distilabel `structured` template")
def test_intent_2_runs_on_the_nodes_that_exist():
    assert planner.review(planner.templates()[1]["plan"])[:2] == ([], [])


def test_the_docs_specialist_validates_at_both_scales_on_10_to_20_docs_pages(monkeypatch):
    monkeypatch.setattr(planner, "get_providers", lambda: {"nebius": object()})  # unsloth-train needs a GPU provider
    t = planner.templates()[3]
    for plan in (t["plan"], planner.reduced(t)["plan"]):
        assert planner.review(plan)[0] == []
    # Lane B (R25): NVIDIA's student, served beside its adapter on one endpoint kept 15 min (R14), no 16 GB merge
    nodes = {n["id"]: n for n in t["plan"]["nodes"]}
    assert [n["type"] for n in t["plan"]["nodes"]] == ["web-research", "synth-distilabel", "data-prep", "unsloth-train",
                                                       "vllm-serve", "judge-eval"]
    assert nodes["train"]["inputs"]["model"] == nodes["serve"]["inputs"]["model"] == "nvidia/Llama-3.1-Nemotron-Nano-8B-v1"
    assert (nodes["serve"]["inputs"]["keep_alive_min"], nodes["serve"]["inputs"]["lora_adapter"]) == (
        15, "${{ nodes.train.outputs.lora_adapter }}")
    assert nodes["train"]["inputs"]["merge"] is False  # vllm-serve reads the adapter, not merged_model
    assert planner.estimate(t["plan"])[0]["usd"] == pytest.approx(2.6627, abs=1e-4)  # 25 min of H100 + 20 of L40S, R14
    seeds = t["plan"]["nodes"][0]["inputs"]["seed_urls"]
    assert 10 <= len(set(seeds)) == len(seeds) <= 20
    assert all(re.fullmatch(r"https://docs\.(tokenfactory\.)?nebius\.com(/[a-z0-9-]+)+", u) for u in seeds), seeds
    assert re.findall(r"https://docs\.[\w./-]*[\w-]", planner._knowledge()) == seeds  # the live planner's list, same order


def test_the_cpu_variant_judges_the_students_gguf_with_and_without_its_lora(monkeypatch):
    """R24's fallback on Lane B: no endpoint; base = the student's GGUF, tuned = the same GGUF plus its GGUF LoRA."""
    monkeypatch.setattr(planner, "get_providers", lambda: {"nebius": object()})
    docs, cpu = planner.templates()[3:5]
    for plan in (cpu["plan"], planner.reduced(cpu)["plan"]):
        assert planner.review(plan)[0] == []
    assert cpu["plan"]["nodes"][:4] == docs["plan"]["nodes"][:4]  # the same data and training as the GPU template
    quantize, evaluate = cpu["plan"]["nodes"][4:]
    assert (quantize["type"], quantize["inputs"]["model"], quantize["inputs"]["lora_adapter"]) == (
        "quantize", "nvidia/Llama-3.1-Nemotron-Nano-8B-v1", "${{ nodes.train.outputs.lora_adapter }}")
    gguf = "${{ nodes.quantize.outputs.gguf_file }}"
    assert (evaluate["inputs"]["base_model_ref"], evaluate["inputs"]["tuned_model_ref"], evaluate["inputs"]["tuned_lora"]) == (
        gguf, gguf, "${{ nodes.quantize.outputs.gguf_lora }}")


async def test_stub_plans_with_the_closest_template_and_calls_nothing(client, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.delenv("NEBIUS_API_KEY")
    monkeypatch.setattr(budget, "control_plane", None)  # a model call would crash
    templates = planner.templates()

    for intent, t in zip(INTENTS + [DOCS, DOCS_CPU], templates, strict=True):  # each intent maps to its own template
        r = await client.post("/agent/plan", json={"intent": intent})
        assert r.status_code == 200
        assert set(r.json()) == {"plan", "rationale", "estimate", "warnings", "errors", "admin_only"}
        assert r.json()["plan"] == t["plan"] and r.json()["rationale"].startswith("STUB=1")
    r = await client.post("/agent/plan", json={"intent": "make me a GGUF of a math model"})
    assert r.json()["plan"] == templates[2]["plan"]
    r = await client.post("/agent/plan", json={"intent": "Distill a docs specialist"})  # PLAN's name for the golden path
    assert r.json()["plan"] == templates[3]["plan"]


@pytest.mark.parametrize("intent, slug", [  # function words ("an", "in", "the", "which", "is") once outvoted the content
    ("Distill an expert in the Nebius documentation", "nebius-docs-specialist"),
    ("Distill an expert in Nebius", "nebius-docs-specialist"),
    ("A model which is an expert in US real-estate compliance", "real-estate-compliance"),
    ("Nebius docs specialist judged on CPU", "nebius-docs-specialist-cpu"),
])
async def test_stub_matching_ignores_stopwords(client, monkeypatch, intent, slug):
    monkeypatch.setenv("STUB", "1")
    r = await client.post("/agent/plan", json={"intent": intent})
    assert f"'{slug}'" in r.json()["rationale"]


async def test_plan_refuses_bad_intents_the_kill_switch_and_a_missing_key(client, monkeypatch):
    assert (await client.post("/agent/plan", json={"intent": "  "})).status_code == 422
    assert (await client.post("/agent/plan", json={"intent": "x" * 2001})).status_code == 422
    monkeypatch.setenv("ORCHAPOD_KILL_SWITCH", "1")
    assert (await client.post("/agent/plan", json={"intent": INTENTS[1]})).status_code == 503
    monkeypatch.delenv("ORCHAPOD_KILL_SWITCH")
    monkeypatch.setenv("NEBIUS_API_KEY", " ")
    r = await client.post("/agent/plan", json={"intent": INTENTS[1]})
    assert (r.status_code, r.json()["detail"]) == (503, "NEBIUS_API_KEY is not set; with no key, set STUB=1 in .env to run on stubs")  # what the plan card shows


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
    assert not any(c.get("create") for c in tf.calls)  # planning retries; only the report is sent once
    assert await budget.spent_today(db) == pytest.approx(2 * (5000 * 0.30 + 800 * 0.90) / 1e6)  # day ledger (R6)


async def test_the_planner_stops_after_two_repairs(client, tf):
    tf.replies = [answer({"name": "x", "nodes": [node("Bad-Id", "data-prep", dataset="hf://x")]})] * 3
    body = (await client.post("/agent/plan", json={"intent": "anything"})).json()
    assert len(tf.requests) == 3
    assert body["errors"] == ["Bad-Id: id must be snake_case ([a-z][a-z0-9_]*)"]


async def test_token_factory_failures_are_502_with_the_cause_only_in_the_log(client, tf, caplog):
    tf.replies = [(400, "model not found"), (200, {"model": "m", "choices": [{"index": 0}]})]  # the second: no message
    for _ in tf.replies[:]:
        r = await client.post("/agent/plan", json={"intent": "anything"})
        assert (r.status_code, r.json()) == (502, {"detail": planner.TF_FAILED})
    assert "model not found" in caplog.text  # the cause is logged, never sent to the client


def test_a_gpu_node_needs_a_configured_provider_it_prefers(monkeypatch):
    plan = {"name": "p", "nodes": [node("t", "unsloth-train", train_data="r2://b/train")]}
    monkeypatch.setattr(planner, "get_providers", lambda: {"runpod": object()})  # configured, but no plan prefers it
    assert errors_of(plan) == [f"t: no GPU provider in provider_pref {ResourceSpec().provider_pref} is configured "
                               "(nebius needs NEBIUS_PROJECT_ID)"]
    monkeypatch.setattr(planner, "get_providers", lambda: {"nebius": object()})
    assert errors_of(plan) == []


def test_stub_reviews_the_docs_specialist_with_no_gpu_provider_and_only_stub(monkeypatch):
    """STUB runs gpu nodes on LocalDocker (contracts "Run state machine"), so review skips its GPU-provider check."""
    monkeypatch.setattr(planner, "get_providers", dict)  # the stub e2e drops NEBIUS_PROJECT_ID
    t = next(t for t in planner.templates() if t["slug"] == "nebius-docs-specialist")
    plans = [t["plan"], planner.reduced(t)["plan"]]
    missing = [f"train: no GPU provider in provider_pref {ResourceSpec().provider_pref} is configured "
               "(nebius needs NEBIUS_PROJECT_ID)"]

    assert [errors_of(p) for p in plans] == [missing] * 2  # without STUB: the error, as before
    monkeypatch.setenv("STUB", "1")
    assert [errors_of(p) for p in plans] == [[]] * 2


async def test_stub_plans_the_docs_specialist_clean_but_only_the_admin_runs_it(client, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.setattr(planner, "get_providers", dict)
    monkeypatch.setenv("ORCHAPOD_ADMIN_TOKEN", "s3cret")
    admin, started = {"X-Orchapod-Admin": "s3cret"}, []
    monkeypatch.setattr(ex, "launch", lambda run_id, scale: started.append(scale))

    planned = (await client.post("/agent/plan", json={"intent": DOCS}, headers=admin)).json()
    body = {"intent": DOCS, "plan": planned["plan"]}

    assert (planned["errors"], planned["admin_only"]) == ([], [])
    public = (await client.post("/agent/plan", json={"intent": DOCS})).json()  # $2.66 against $0.30: its price is not its error
    assert (public["plan"], public["estimate"]) == (planned["plan"], planned["estimate"])
    assert (public["admin_only"], public["errors"]) == (["train", "serve"], [ADMIN_ONLY.format("train, serve")])
    assert (await client.post("/agent/run", json=body)).status_code == 403  # gpu_guard: unchanged, STUB or not
    assert (await client.post("/agent/run", json=body, headers=admin)).status_code == 201
    assert started == [1.0]


ADMIN_ONLY = "{} rent GPUs billed by the hour: on the public demo only the admin can start them."


def docs_plan():
    """The golden path's plan (template 4): unsloth-train (train) and vllm-serve (serve) rent GPUs, an estimate of $2.66."""
    return next(t for t in planner.templates() if t["slug"] == "nebius-docs-specialist")["plan"]


async def test_an_anonymous_gpu_plan_comes_back_as_drafted_with_admin_only_and_one_plain_line(client, tf, monkeypatch):
    """The public cannot start a GPU plan however it is cut, so its price is not sent back to Super: two repairs shrank the
    golden plan into a mangled one that never fit, under a rationale that said it did."""
    monkeypatch.setattr(planner, "get_providers", lambda: {"nebius": object()})
    plan = docs_plan()
    tf.replies = [answer(plan, "Fine-tune the student, serve it, judge it.")]

    body = (await client.post("/agent/plan", json={"intent": DOCS})).json()  # anonymous: a $0.30 run cap

    assert len(tf.requests) == 1  # no repair
    assert (body["plan"], body["rationale"]) == (plan, "Fine-tune the student, serve it, judge it.")
    assert (body["admin_only"], body["errors"]) == (["train", "serve"], [ADMIN_ONLY.format("train, serve")])
    assert body["estimate"] == planner.estimate(plan)[0] and body["estimate"]["usd"] > 2  # the plan's real price


async def test_the_other_errors_of_an_anonymous_gpu_plan_are_repaired_but_its_price_is_not(client, tf, monkeypatch):
    monkeypatch.setattr(planner, "get_providers", lambda: {"nebius": object()})
    plan, bad = docs_plan(), copy.deepcopy(docs_plan())
    next(n for n in bad["nodes"] if n["id"] == "synth")["inputs"]["teacher_model"] = "gpt-4o"
    tf.replies = [answer(bad), answer(plan)]

    body = (await client.post("/agent/plan", json={"intent": DOCS})).json()

    fix = tf.requests[1]["messages"][-1]["content"]  # what went back to the model
    assert len(tf.requests) == 2 and "synth: teacher_model" in fix and "estimate" not in fix and "GPU" not in fix
    assert (body["plan"], body["admin_only"], body["errors"]) == (plan, ["train", "serve"], [ADMIN_ONLY.format("train, serve")])

    tf.requests.clear()
    tf.replies = [answer(bad)] * 3  # never fixed: its errors, then the one line in place of the budget error
    body = (await client.post("/agent/plan", json={"intent": DOCS})).json()
    assert len(tf.requests) == 3 and body["errors"] == [*planner.review(bad)[0], ADMIN_ONLY.format("train, serve")]


async def test_an_admin_gpu_plan_over_budget_is_repaired_as_before(client, tf, monkeypatch):
    monkeypatch.setattr(planner, "get_providers", lambda: {"nebius": object()})
    monkeypatch.setenv("ORCHAPOD_ADMIN_TOKEN", "s3cret")
    monkeypatch.setenv("ORCHAPOD_MAX_RUN_USD", "1")  # the golden plan's $2.66 does not fit the admin's cap
    plan = docs_plan()
    tf.replies = [answer(plan)] * 3

    body = (await client.post("/agent/plan", json={"intent": DOCS}, headers={"X-Orchapod-Admin": "s3cret"})).json()

    assert len(tf.requests) == 3 and "estimate" in tf.requests[1]["messages"][-1]["content"]  # the budget went back
    est = planner.estimate(plan)[0]["usd"]
    assert (body["admin_only"], body["errors"]) == ([], [f"plan: the estimate ${est:.2f} is more than the $1.00 left (run cap $1)"])


async def test_a_reply_that_is_no_plan_has_no_admin_only_and_is_not_a_crash(client, tf):
    tf.replies = [answer({"name": "x", "nodes": "oops"})] * 3  # review() reports its shape; there are no nodes to rent a GPU

    r = await client.post("/agent/plan", json={"intent": "anything"})  # anonymous

    body = r.json()
    assert (r.status_code, len(tf.requests), body["admin_only"]) == (200, 3, [])
    assert body["errors"] and all(e.startswith("plan: ") for e in body["errors"])


async def test_an_anonymous_cpu_plan_over_budget_still_gets_the_repairs(client, tf):
    big = {**GOOD, "nodes": [node("synth", "synth-distilabel", pipeline_template="self-instruct", n_samples=10000),
                             GOOD["nodes"][1]]}  # synth's $1.00 cap against the public's $0.30
    tf.replies = [answer(big)] * 3

    body = (await client.post("/agent/plan", json={"intent": "Q&A pairs about sourdough baking"})).json()

    est = planner.estimate(big)[0]["usd"]
    assert len(tf.requests) == 3 and "estimate" in tf.requests[1]["messages"][-1]["content"]
    assert (body["admin_only"], body["errors"]) == ([], [f"plan: the estimate ${est:.2f} is more than the $0.30 left (run cap $0.3)"])


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
        node("i", "tf-deploy", job="j"),
    ]})

    for expected in [
        "b: dataset: a (data-prep) has no output 'nope'",
        "c: dataset: refs node 'a', which is not in needs",
        "d: needs unknown node 'zz'",
        "d: dataset: plans have no workflow inputs (${{ inputs.uri }})",
        "e: unknown input 'colour'",
        "e: dataset: a ref must be exactly one ${{ nodes.<id>.outputs.<name> }}",
        "f: unknown node type 'lm-eval'",  # hidden: the agent never plans it
        "i: unknown node type 'tf-deploy'",  # hidden: Token Factory retired per-token LoRA deploy (410, spike 1)
        "g: unknown node type 'nope'",
        "Bad: id must be snake_case ([a-z][a-z0-9_]*)",
        "h: seed_prompts: refs resolve only at the top level of inputs",
        f"t: no GPU provider in provider_pref {ResourceSpec().provider_pref} is configured (nebius needs NEBIUS_PROJECT_ID)",
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
    base_model_ref: str = ""
    gguf_file: str = ""
    gguf_f16: str = ""


class _Model(BaseModel):
    model: str = "m"


class _Finetune(BaseModel):
    model: str = "meta-llama/Llama-3.1-8B-Instruct"
    train_data: str


class _Judge(BaseModel):
    test_data: str
    base_model_ref: dict | str
    tuned_model_ref: dict | str
    judge_model: str = "nvidia/Nemotron-3-Ultra-550b-a55b"


def test_review_enforces_the_knowledge_constraints(monkeypatch):
    for t, schema in (("tf-finetune", _Finetune), ("judge-eval", _Judge)):
        monkeypatch.setitem(NODE_REGISTRY, t, {"description": t, "inputs_schema": schema, "outputs_schema": _Out,
                                               "runtime": "api"})
    tf_ref = {"base_url": TF_BASE, "model": "meta-llama/Llama-3.1-8B-Instruct", "api_key_env": "NEBIUS_API_KEY",
              "base_model": None}
    plan = {"name": "p", "nodes": [
        node("nemo", "tf-finetune", model="nvidia/Llama-3.1-Nemotron-Nano-8B-v1", train_data="r2://b/t"),
        node("small", "tf-finetune", model="meta-llama/Llama-3.2-3B-Instruct", train_data="r2://b/t"),
        node("big", "tf-finetune", train_data="r2://b/t"),
        node("judge", "judge-eval", test_data="r2://b/test", judge_model="meta-llama/Llama-3.3-70B-Instruct",
             base_model_ref={**tf_ref, "base_url": "https://attacker.example/v1"},
             tuned_model_ref={**tf_ref, "api_key_env": "ORCHAPOD_ENDPOINT_TOKEN", "base_url": "https://e.example/v1"}),
        node("fair", "judge-eval", test_data="r2://b/test", base_model_ref=tf_ref, tuned_model_ref="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"),
    ]}

    errors, warnings, _ = planner.review(plan)

    assert [e.split(":")[0] for e in errors] == ["nemo", "judge", "judge", "judge"]
    assert errors[0].startswith("nemo: Token Factory does not fine-tune nvidia/Llama-3.1-Nemotron-Nano-8B-v1")
    assert errors[1].startswith("judge: base_model_ref: refused ModelRef")
    assert errors[2].startswith("judge: tuned_model_ref: refused ModelRef")
    assert errors[3].startswith("judge: judge_model must be a Nemotron model on Token Factory")
    assert any(w.startswith("big: no fine-tune price") for w in warnings)


def test_review_refuses_a_bare_model_id_that_token_factory_does_not_price():
    """Super planned judge-eval's base_model_ref as the student's bare Hub id (hosted, 2026-10-25): it is not on Token
    Factory, so every base answer would have failed at the end of the run. A plain id must be a priced Token Factory model."""
    docs = next(t["plan"] for t in planner.templates() if t["plan"]["name"] == "nebius-docs-specialist-nemotron-nano-8b-cpu")
    judge = next(n for n in docs["nodes"] if n["type"] == "judge-eval")
    bare = {**docs, "nodes": [n if n is not judge else {**n, "inputs": {**n["inputs"], "base_model_ref": "nvidia/Llama-3.1-Nemotron-Nano-8B-v1"}}
                              for n in docs["nodes"]]}
    new = [e for e in errors_of(bare) if e not in errors_of(docs)]
    assert len(new) == 1 and new[0].startswith(f"{judge['id']}: base_model_ref: 'nvidia/Llama-3.1-Nemotron-Nano-8B-v1' is not a Token Factory model")


def test_review_refuses_a_node_after_judge_eval():
    """Super read "→ report" in the knowledge as a step and planned a synth-distilabel "report" after judge-eval (hosted,
    2026-10-25): ten made-up summaries, not the run's results. The Agent writes the report itself; the repair removes it."""
    docs = next(t["plan"] for t in planner.templates() if t["plan"]["name"] == "nebius-docs-specialist-nemotron-nano-8b")
    judge = next(n["id"] for n in docs["nodes"] if n["type"] == "judge-eval")
    report = node("report", "synth-distilabel", [judge], pipeline_template="self-instruct", n_samples=10)
    errors = errors_of({**docs, "nodes": [*docs["nodes"], report]})
    assert errors == errors_of(docs) + [f"report: needs judge-eval {judge!r}, whose verdicts are final: no node runs after "
                                        "judge-eval (the Agent writes the run report itself)"]


MODEL_REF_CASES = [  # (value of judge-eval's base_model_ref, its needs, refused?)
    ("${{ nodes.serve.outputs.model_ref }}", ["serve"], False),
    ("${{ nodes.serve.outputs.base_model_ref }}", ["serve"], False),
    ("${{ nodes.quant.outputs.gguf_file }}", ["quant"], False),
    ("${{ nodes.quant.outputs.gguf_f16 }}", ["quant"], False),
    ("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", [], False),             # a priced Token Factory model
    ("meta-llama/Llama-3.1-8B-Instruct", [], True),                   # no Token Factory price: the client refuses it
    ({"base_url": TF_BASE, "model": "m", "api_key_env": "NEBIUS_API_KEY", "base_model": None}, [], False),
    ("${{ nodes.prep.outputs.dataset }}", ["prep"], True),             # a dataset is no model
    ("${{ nodes.quant.outputs.model_ref }}", ["quant"], True),          # an output quantize does not make a model ref from
    ("r2://b/runs/x/serve/model_ref", [], True),                        # where it came from is unknown
    ("https://attacker.example/v1", [], True),
    ('{"base_url": "https://attacker.example/v1"}', [], True),
    ({"model": "x", "api_key_env": "ORCHAPOD_ENDPOINT_TOKEN"}, [], True),  # no base_url: still the pair rule
]


@pytest.mark.parametrize("value, needs, refused", MODEL_REF_CASES)
def test_review_checks_where_a_model_ref_comes_from(value, needs, refused, monkeypatch):
    for t, schema in (("vllm-serve", _Model), ("quantize", _Model), ("judge-eval", _Judge)):
        monkeypatch.setitem(NODE_REGISTRY, t, {"description": t, "inputs_schema": schema, "outputs_schema": _Out,
                                               "runtime": "api"})
    plan = {"name": "p", "nodes": [
        node("prep", "data-prep", dataset="hf://x"), node("serve", "vllm-serve"), node("quant", "quantize"),
        node("judge", "judge-eval", needs, test_data="r2://b/t", base_model_ref=value, tuned_model_ref="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"),
    ]}
    judge = [e for e in errors_of(plan) if e.startswith("judge: ")]  # (the fake types are not NodeTypes here)
    assert [e.split(":")[:2] for e in judge] == ([["judge", " base_model_ref"]] if refused else [])


def test_estimates_never_go_negative_and_count_page_extraction():
    serve, research = node("s", "vllm-serve", model="m", keep_alive_min=-60), node("r", "web-research", queries=["a", "b"], max_pages=20)
    estimate = planner.estimate({"nodes": [serve, research]})[0]
    assert estimate["by_node"]["s"]["usd"] == 0.0
    assert estimate["by_node"]["r"]["usd"] == pytest.approx((2 * 2 + 20 / 5) * 0.008)  # advanced searches + pages read
    assert "s: keep_alive_min: Input should be greater than or equal to 1" in errors_of({"name": "p", "nodes": [serve]})


def test_tf_finetune_is_priced_from_its_trained_tokens_once_the_base_has_a_price(monkeypatch):
    estate = planner.templates()[0]  # synth 300 rows -> data-prep train_split 0.8 -> tf-finetune 2 epochs on Llama 3.2 3B
    est, warnings = planner.estimate(estate["plan"])
    assert est["by_node"]["finetune"]["usd"] == 0.5  # TYPICAL until spike 1 fills the price ...
    assert "finetune: no fine-tune price for meta-llama/Llama-3.2-3B-Instruct yet (spike 1); the estimate assumes $0.50" in warnings

    monkeypatch.setitem(PRICES["token_factory_finetune"], "meta-llama/Llama-3.2-3B-Instruct", 0.4e-6)  # $0.40 per 1M
    est, warnings = planner.estimate(estate["plan"])
    assert est["by_node"]["finetune"]["usd"] == pytest.approx(300 * 0.8 * 250 * 2 * 0.4e-6)  # rows x tokens x epochs x $
    assert not [w for w in warnings if w.startswith("finetune:")]
    small = planner.reduced(estate)["estimate"]  # 40 rows, 1 epoch
    assert small["by_node"]["finetune"]["usd"] == pytest.approx(40 * 0.8 * 250 * 0.4e-6)

    plan = copy.deepcopy(estate["plan"])
    plan["nodes"][3]["inputs"]["hyperparameters"] = {"n_epochs": 3}  # wins over n_epochs, as in the node
    assert planner.estimate(plan)[0]["by_node"]["finetune"]["usd"] == pytest.approx(300 * 0.8 * 250 * 3 * 0.4e-6)
    hf = {"name": "p", "nodes": [node("prep", "data-prep", dataset="hf://x"),
                                 node("ft", "tf-finetune", ["prep"], model="meta-llama/Llama-3.2-3B-Instruct",
                                      train_data="${{ nodes.prep.outputs.train_jsonl }}")]}
    est, warnings = planner.estimate(hf)
    assert (est["by_node"]["ft"]["usd"], warnings) == (0.5, [
        "ft: the rows of train_data are unknown (not from synth-distilabel); the estimate assumes $0.50"])
    del hf["nodes"][0]["inputs"]["dataset"]  # a required input missing: review() reports it, the estimate never crashes
    assert planner.review(hf)[0] == ["prep: dataset: Field required"]


def test_vllm_serve_is_priced_from_the_endpoints_creation():
    """vllm-serve bills from creation (ml-w4): the typical start (5 min; 15 at most) plus keep_alive_min, at its rate."""
    est = planner.estimate({"nodes": [node("s", "vllm-serve", model="m", keep_alive_min=30),
                                      node("h", "vllm-serve", model="m", keep_alive_min=10, platform="gpu-h100-sxm")]})[0]
    assert (est["by_node"]["s"]["usd"], est["by_node"]["h"]["usd"]) == (round(35 / 60 * 1.55, 4), round(15 / 60 * 4.5, 4))


def test_review_reports_an_estimate_over_the_budget_left():
    errors, _, estimate = planner.review(GOOD, (0.01, "run", 0.3))
    assert errors == [f"plan: the estimate ${estimate['usd']:.2f} is more than the $0.01 left (run cap $0.3)"]


# --- run and report --------------------------------------------------------------

async def test_run_validates_again_and_launches(client, db, monkeypatch):
    launched = []
    monkeypatch.setattr(ex, "launch", lambda run_id, scale: launched.append((run_id, scale)))
    extra = {**GOOD, "owner": "x", "nodes": [{**GOOD["nodes"][0], "resources": {"gpu": "8xH100"}}, GOOD["nodes"][1]]}

    r = await client.post("/agent/run", json={"intent": "Q&A data", "plan": extra})

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
    r = await client.post("/agent/run", json={"intent": "x", "plan": {"name": "x", "nodes": []}})
    assert (r.status_code, r.json()["detail"], len(r.json()["errors"])) == (422, "the plan has errors", 1)
    assert r.json()["errors"][0].startswith("plan: nodes: ")
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
    db.add(Artifact(node_run_id=prep.id, name="logs", kind=ArtifactKind.LOG, uri="r2://b/runs/x/prep/logs"))
    db.add(AgentRun(run_id=run.id, intent="Q&A data", plan=GOOD, estimate={"usd": 0.03, "minutes": 4.5, "by_node": {}}))
    await db.commit()
    return run


@pytest.fixture
async def reports(db, monkeypatch):
    """The background report writer (routes/agent.report_later) on the test database; `await reports()` waits for it, as
    the teardown does."""
    monkeypatch.setattr("api.database.AsyncSessionLocal",
                        async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False))

    async def settle():
        while agent_routes._reporting:
            await asyncio.wait(set(agent_routes._reporting.values()))
    yield settle
    await settle()


async def polled(client, reports, run_id) -> dict:
    """The report as a poller sees it: a GET of the ended run starts the writer if none runs, a later GET reads it."""
    await client.get(f"/agent/runs/{run_id}/report")
    await reports()
    return (await client.get(f"/agent/runs/{run_id}/report")).json()


async def test_super_writes_the_report_in_the_background_once_the_run_ends(client, db, tf, reports):
    run = await agent_run(db, RunStatus.RUNNING)
    r = (await client.get(f"/agent/runs/{run.id}/report")).json()
    assert (r["ready"], r["markdown"], r["intent"], r["status"]) == (False, None, "Q&A data", "running")
    assert {"run_id", "cost_usd", "error", "nodes", "artifacts", "estimate"} <= set(r)

    run.status = RunStatus.SUCCEEDED
    await db.commit()
    tf.replies = [(200, "## What ran\nsynth, then prep")]
    assert (await client.get(f"/agent/runs/{run.id}/report")).json()["ready"] is False  # the GET never waits on Nemotron
    await reports()
    r = (await client.get(f"/agent/runs/{run.id}/report")).json()

    assert (r["ready"], r["markdown"]) == (True, "## qa-data: succeeded\n\n## What ran\nsynth, then prep")  # names the plan
    sent = tf.requests[0]
    assert (sent["model"], sent["chat_template_kwargs"]) == (SUPER, {"enable_thinking": False})
    assert "Q&A data" in sent["messages"][1]["content"] and (tf.calls[0]["read_timeout"], tf.calls[0]["create"]) == (30, True)
    assert (await polled(client, reports, run.id))["markdown"] == r["markdown"]
    assert len(tf.requests) == 1  # cached in the DB (R8)
    ledger = (await db.scalars(select(Spend).where(Spend.source == "reporter"))).all()
    assert [float(x.usd) for x in ledger] == [pytest.approx((5000 * 0.30 + 800 * 0.90) / 1e6)]  # day ledger (R6)
    assert (await client.get(f"/agent/runs/{uuid.uuid4()}/report")).status_code == 404


async def test_the_report_is_written_as_the_run_ends(client, db, provider, launched, reports, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    provider.script = {"synth": {"outputs": {"dataset": "r2://b/d"}}}
    r = await client.post("/agent/run", json={"intent": "Q&A data", "plan": GOOD})
    await asyncio.wait_for(launched[-1], 5)
    await reports()

    stored = await db.get(AgentRun, uuid.UUID(r.json()["run_id"]))
    await db.refresh(stored)
    assert stored.report_md.startswith("## qa-data: succeeded")  # before any GET asked for it


async def test_the_report_call_is_sent_once_then_the_template_stands_in(client, db, tf, reports):
    """create=True: a call that may have landed is never re-sent (each send may bill; Lightning once took 4 x 120 s)."""
    for reply in ((None, httpx.ReadTimeout("no reply in 30 s")), (503, "busy")):
        run = await agent_run(db, RunStatus.SUCCEEDED)
        tf.replies, tf.requests = [reply, (200, "## a re-sent report")], []
        md = (await polled(client, reports, run.id))["markdown"]
        assert md.startswith("## qa-data: succeeded\n\n**Intent:** Q&A data") and len(tf.requests) == 1, reply


async def test_a_report_is_written_once_however_often_it_is_asked_for(client, db, tf, reports):
    run = await agent_run(db, RunStatus.SUCCEEDED)
    tf.replies = [(200, "## What ran\nsynth, then prep")]
    agent_routes.report_later(run.id, 1.0)
    agent_routes.report_later(run.id, 1.0)  # the executor's ask and a poll at once
    await reports()
    assert len(tf.requests) == 1 and (await client.get(f"/agent/runs/{run.id}/report")).json()["ready"]


async def test_a_report_that_was_not_written_is_tried_again_on_the_next_poll(client, db, tf, reports, monkeypatch, caplog):
    run, real, calls = await agent_run(db, RunStatus.SUCCEEDED), planner.write_report, []

    async def fails_once(*args):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("database gone")
        return await real(*args)

    monkeypatch.setattr(planner, "write_report", fails_once)
    tf.replies = [(200, "## What ran\nsynth, then prep")]
    assert (await polled(client, reports, run.id))["ready"] is False and "was not written" in caplog.text
    r = await polled(client, reports, run.id)
    assert r["ready"] and r["markdown"].startswith("## qa-data: succeeded") and len(tf.requests) == 1


def test_the_template_report_keeps_name_intent_and_error_on_one_line_each():
    run = SimpleNamespace(plan={"name": "a\n" + "b" * 100}, intent="x\n## How to use it", estimate={"usd": 1})
    md = planner.template_report(run, {"status": "failed", "cost_usd": 0, "error": "boom\n## Cost", "nodes": [],
                                       "artifacts": []})
    assert [x for x in md.splitlines() if x.startswith("#")] == ["## a " + "b" * 78 + ": failed"]  # at most 80


async def test_a_plan_name_stays_one_plain_title_line(client, db, reports, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    run = await agent_run(db, RunStatus.SUCCEEDED)
    (await db.get(AgentRun, run.id)).plan = {**GOOD, "name": "qa\n## Cost\n$0.00 of $0.00 estimated"}
    await db.commit()
    lines = (await polled(client, reports, run.id))["markdown"].splitlines()
    assert [x for x in lines if x.startswith("#")] == ["## qa ## Cost $0.00 of $0.00 estimated: succeeded"]


async def test_report_falls_back_to_the_template(client, db, monkeypatch, tf, reports):
    failed = await agent_run(db, RunStatus.FAILED)
    tf.replies = [(400, "no such model")]
    md = (await polled(client, reports, failed.id))["markdown"]
    assert md.startswith("## qa-data: failed") and "Q&A data" in md and "$0.0200 of $0.03 estimated" in md

    garbled = await agent_run(db, RunStatus.SUCCEEDED)
    tf.replies = [(200, {"model": "m", "choices": [{"index": 0}]})]  # a 200 the client cannot read
    assert (await polled(client, reports, garbled.id))["markdown"].startswith("## qa-data: succeeded")

    monkeypatch.setenv("STUB", "1")
    done = await agent_run(db, RunStatus.SUCCEEDED)
    md = (await polled(client, reports, done.id))["markdown"]
    assert "[prep/dataset](/artifacts/" in md and len(tf.requests) == 2  # STUB calls nothing
    assert "prep/logs" not in md  # results, not the node's log file


async def test_a_report_written_while_the_run_is_retried_is_dropped(client, db, monkeypatch, reports):
    run = await agent_run(db, RunStatus.FAILED)
    run.finished_at = utcnow()
    await db.commit()

    async def slow_super(agent_run_, summary, db_, scale):
        async with async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)() as other:
            retried = await other.get(Run, run.id)  # Retry node lands while Super writes
            retried.status, retried.finished_at = RunStatus.PROVISIONING_GPU, None
            await other.commit()
        return "## a report of the attempt that was retried"

    monkeypatch.setattr(planner, "write_report", slow_super)
    r = await polled(client, reports, run.id)
    await reports()

    assert (r["ready"], r["markdown"]) == (False, None)
    stored = await db.get(AgentRun, run.id)
    await db.refresh(stored)
    assert stored.report_md is None  # the retried run gets its own report when it ends


async def test_retry_clears_the_cached_report(client, db, monkeypatch, reports):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.setattr(ex, "launch", lambda run_id, scale: None)
    run = await agent_run(db, RunStatus.FAILED)
    prep = (await db.scalars(select(NodeRun).where(NodeRun.run_id == run.id, NodeRun.node_id == "prep"))).one()
    prep.status, prep.error = NodeStatus.FAILED, "exit 1: boom"
    await db.commit()
    assert "exit 1: boom" in (await polled(client, reports, run.id))["markdown"]

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


def test_every_shipped_template_plans_without_errors_at_both_scales(monkeypatch):
    """make check guards every template (not only the Docker e2e): an edit that breaks validation fails here."""
    from api.agent import planner
    monkeypatch.setattr(planner, "get_providers", lambda: {"nebius": object()})  # a gpu node needs a configured provider
    shipped = planner.templates()
    assert len(shipped) >= 4
    for t in shipped:
        for plan in (t["plan"], planner.reduced(t)["plan"]):
            errors, _, _ = planner.review(plan)
            assert errors == [], (t["slug"], errors)
