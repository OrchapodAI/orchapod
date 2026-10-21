"""
apps/api/agent/planner.py

The Orchapod Agent (docs/contracts.md "Agent API"): Nemotron 3 Super turns an intent into a plan (a workflow spec as
JSON), review() validates and prices it, and Nemotron 3.5 Lightning writes the report once the run ends. Every model
call goes through Token Factory and the control-plane day ledger (services/budget.control_plane). With STUB=1 the
plan is the closest canonical template (templates/*.json) and the report is the deterministic template.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import HTTPException
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from api.executor.dag import compile_dag
from api.executor.run_workflow import _REF as REF
from api.models.db import AgentRun
from api.services import budget
from api.services.provider_selector import get_providers
from orchapod.prices import PRICES
from packages.providers.base import ProviderError
from packages.providers.tokenfactory import LIGHTNING, SUPER, TF_BASE, ULTRA
from packages.workflow_schema.models import NODE_REGISTRY, ResourceSpec

log = logging.getLogger("api.agent")

Intent = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
TEMPLATES = Path(__file__).parent / "templates"

# Typical $ and minutes per node type, for the estimate and the catalog the planner reads. Nodes whose inputs say how
# much they spend are priced from PRICES in estimate(). ponytail: rough until spikes 1–3 measure real runs.
TYPICAL = {
    "web-research": (0.10, 3), "synth-distilabel": (0.30, 6), "data-prep": (0.0, 2), "tf-finetune": (0.50, 30),
    "tf-deploy": (0.0, 6), "judge-eval": (0.30, 15), "hf-download": (0.0, 5), "quantize": (0.0, 15),
    "unsloth-train": (1.88, 25), "vllm-serve": (0.91, 8),
}
# docs/agent_knowledge.md "Constraints": what Token Factory fine-tunes, and the per-token LoRA bases spike 1 tests.
TF_FINETUNE_BASES = re.compile(r"llama-3\.1-(8b|70b)|llama-3\.2-(1b|3b)|llama-3\.3-70b|qwen3|qwen2\.5|gpt-oss|deepseek|gemma-4",
                               re.IGNORECASE)
SERVERLESS_LORA_BASES = {"meta-llama/Meta-Llama-3.1-8B-Instruct", "meta-llama/Llama-3.1-8B-Instruct"}
_ID = re.compile(r"^[a-z][a-z0-9_]*$")


class PlanNode(BaseModel):
    id: str
    type: str
    needs: list[str] = []
    inputs: dict[str, Any] = {}


class Plan(BaseModel):
    """A workflow spec as JSON (docs/WORKFLOW_SPEC.md) without resources: defaults apply."""
    name: str = Field(min_length=1)
    nodes: list[PlanNode] = Field(min_length=1)


def templates() -> list[dict]:
    """The three canonical intents: {slug, title, intent, rationale, plan}."""
    return [json.loads(p.read_text()) for p in sorted(TEMPLATES.glob("*.json"))]


def visible() -> dict[str, dict]:
    """The node catalog the planner may use: NODE_REGISTRY rows not marked hidden."""
    return {getattr(t, "value", t): meta for t, meta in NODE_REGISTRY.items() if not meta.get("hidden")}


def _values(node: dict) -> dict:
    """A node's inputs over its schema's defaults."""
    meta = NODE_REGISTRY.get(node["type"])
    fields = meta["inputs_schema"].model_fields if meta else {}
    defaults = {k: f.get_default(call_default_factory=True) for k, f in fields.items() if not f.is_required()}
    return {**defaults, **(node.get("inputs") or {})}


# ---------------------------------------------------------------------------
# Estimate and validation
# ---------------------------------------------------------------------------

def estimate(plan: dict) -> tuple[dict, list[str]]:
    """{"usd", "minutes", "by_node": {id: {"usd", "minutes"}}} and its warnings for a well-formed plan (see Plan);
    nodes run one after another."""
    tf, gpu = PRICES["token_factory"], PRICES["nebius_serverless"]
    by_node, warnings = {}, []
    for n in plan["nodes"]:
        t, v = n["type"], _values(n)
        usd, minutes = TYPICAL.get(t, (0.0, 5))
        try:
            if t == "synth-distilabel":  # ~250 tokens in and out per row; the node stops at max_usd
                p, rows = tf.get(v.get("teacher_model"), tf[SUPER]), int(v.get("n_samples") or 1000)
                usd, minutes = min(float(v.get("max_usd") or 1.0), rows * 250 * (p["in"] + p["out"]) / 1e6), 2 + rows / 200
            elif t == "web-research":  # 2 credits per advanced search, 1 per 5 extracted URLs
                usd = (2 * len(v.get("queries") or []) + -(-len(v.get("seed_urls") or []) // 5)) * PRICES["tavily"]["credit"]
            elif t == "judge-eval":  # both answer orders per judged row, ~1,500 tokens in and 300 out each
                p, rows = tf.get(v.get("judge_model"), tf[ULTRA]), int(v.get("n_judge") or v.get("max_samples") or 60)
                usd, minutes = 2 * rows * (1500 * p["in"] + 300 * p["out"]) / 1e6, 5 + rows / 6
            elif t == "vllm-serve":  # the endpoint bills keep_alive_min of GPU time
                usd = int(v.get("keep_alive_min") or 30) / 60 * gpu.get(v.get("platform"), gpu["gpu-l40s-a"])
        except (TypeError, ValueError):
            pass  # a ref or a bad value: review() reports it; the typical cost stands
        if t == "tf-finetune" and str(v.get("model")) not in PRICES["token_factory_finetune"]:
            warnings.append(f"{n['id']}: no fine-tune price for {v.get('model')} yet (spike 1); "
                            f"the estimate assumes ${usd:.2f}")
        if t == "tf-deploy":
            warnings.append(f"{n['id']}: per-token LoRA deploy is unverified until spike 1; "
                            f"if it fails, serve the lora_adapter with vllm-serve")
        by_node[n["id"]] = {"usd": round(usd, 4), "minutes": round(minutes, 1)}
    return {"usd": round(sum(x["usd"] for x in by_node.values()), 4),
            "minutes": round(sum(x["minutes"] for x in by_node.values()), 1), "by_node": by_node}, warnings


def review(plan: Any, budget_left: tuple[float, str, float] | None = None) -> tuple[list[str], list[str], dict]:
    """(errors, warnings, estimate). Errors read "<node_id>: <problem>"; budget_left = budget.left(...) adds the
    check that the estimate fits."""
    try:
        p = Plan.model_validate(plan)
    except ValidationError as e:
        return [f"plan: {_where(x)}{x['msg']}" for x in e.errors()], [], estimate({"nodes": []})[0]
    est, warnings = estimate(p.model_dump())
    nodes = {n.id: n for n in p.nodes}
    errors = [] if len(nodes) == len(p.nodes) else [f"plan: node ids must be unique ({', '.join(_dupes(p))})"]
    catalog = visible()
    for n in p.nodes:
        errors += [f"{n.id}: {problem}" for problem in _node_problems(n, nodes, catalog)]
    if not errors:
        try:
            compile_dag(yaml.safe_dump(p.model_dump()), {}).topological_order()
        except ValueError as e:
            errors.append(f"plan: {e}")
    if budget_left and est["usd"] > budget_left[0]:
        left, which, cap = budget_left
        errors.append(f"plan: the estimate ${est['usd']:.2f} is more than the ${max(left, 0):.2f} left "
                      f"({which} cap ${cap:g})")
    return errors, warnings, est


def _where(err: dict) -> str:
    return ".".join(map(str, err["loc"])) + ": " if err["loc"] else ""


def _dupes(p: Plan) -> list[str]:
    ids = [n.id for n in p.nodes]
    return sorted({i for i in ids if ids.count(i) > 1})


def _node_problems(n: PlanNode, nodes: dict[str, PlanNode], catalog: dict[str, dict]) -> list[str]:
    problems = [] if _ID.match(n.id) else ["id must be snake_case ([a-z][a-z0-9_]*)"]
    meta = catalog.get(n.type)
    if meta is None:
        return problems + [f"unknown node type {n.type!r}"]
    problems += [f"needs unknown node {d!r}" for d in n.needs if d not in nodes]
    schema = meta["inputs_schema"]
    problems += [f"unknown input {k!r}" for k in n.inputs if k not in schema.model_fields]
    try:
        schema.model_validate(n.inputs)
    except ValidationError as e:
        problems += [f"{_where(x) or 'inputs: '}{x['msg']}" for x in e.errors()]
    for k, value in n.inputs.items():
        problems += [f"{k}: {p}" for p in _input_problems(value, n, nodes, catalog)]
    problems += _constraint_problems(n, nodes)
    pref = ResourceSpec().provider_pref  # plans carry no resources, so the executor picks from the default list
    if meta["runtime"] == "gpu" and not set(pref) & set(get_providers()):
        problems.append(f"no GPU provider in provider_pref {pref} is configured (nebius needs NEBIUS_PROJECT_ID)")
    return problems


def _input_problems(value: Any, n: PlanNode, nodes: dict[str, PlanNode], catalog: dict[str, dict]) -> list[str]:
    if not isinstance(value, str):
        problems = ["refs resolve only at the top level of inputs"] if "${{" in json.dumps(value, default=str) else []
        if isinstance(value, dict) and "base_url" in value:
            problems += _model_ref_problems(value)
        return problems
    if "${{" not in value:
        return []
    m = REF.fullmatch(value.strip())
    if not m:
        return ["a ref must be exactly one ${{ nodes.<id>.outputs.<name> }}"]
    if m[1]:
        return [f"plans have no workflow inputs ({value})"]
    if m[2] not in n.needs:
        return [f"refs node {m[2]!r}, which is not in needs"]
    source = nodes.get(m[2])
    outputs = catalog.get(source.type, {}).get("outputs_schema") if source else None
    if outputs is not None and m[3] not in outputs.model_fields:
        return [f"{m[2]} ({source.type}) has no output {m[3]!r}"]
    return []


def _model_ref_problems(ref: dict) -> list[str]:
    """Inline ModelRefs pair NEBIUS_API_KEY only with Token Factory; endpoint refs come only from a vllm-serve
    model_ref output (contracts "ModelRef"), so a plan never sends our keys to a URL it chose."""
    tf_base = (os.environ.get("NEBIUS_BASE_URL") or TF_BASE).strip().rstrip("/")
    if ref.get("api_key_env") == "NEBIUS_API_KEY" and str(ref.get("base_url") or "").strip().rstrip("/") == tf_base:
        return []
    return [f"refused ModelRef: an inline ref may only pair NEBIUS_API_KEY with {tf_base}; "
            "endpoint refs come from a vllm-serve model_ref output"]


def _constraint_problems(n: PlanNode, nodes: dict[str, PlanNode]) -> list[str]:
    """docs/agent_knowledge.md "Constraints every plan must respect"."""
    v = _values(n.model_dump())
    nemotron = sorted(m for m in PRICES["token_factory"] if "nemotron" in m.lower())
    problems = [f"{k} must be a Nemotron model on Token Factory ({', '.join(nemotron)}), not {v[k]}"
                for k in ("teacher_model", "judge_model") if k in v and v[k] not in nemotron]
    if n.type == "tf-finetune":
        model = str(v.get("model"))
        if "nemotron" in model.lower() or not TF_FINETUNE_BASES.search(model):
            problems.append(f"Token Factory does not fine-tune {model}: use Llama 3.1 8B/70B, 3.2 1B/3B, 3.3 70B, Qwen3, "
                            "Qwen2.5, gpt-oss, DeepSeek or Gemma 4 (a Nemotron student trains with unsloth-train)")
    if n.type == "tf-deploy":
        job = v.get("job")
        m = REF.fullmatch(job.strip()) if isinstance(job, str) else None
        source = nodes.get(m[2]) if m and m[2] else None
        base = job.get("model") if isinstance(job, dict) else _values(source.model_dump()).get("model") if source else None
        if base and str(base) not in SERVERLESS_LORA_BASES:
            problems.append(f"Token Factory has no per-token LoRA deploy for {base}: "
                            "serve the tf-finetune lora_adapter with vllm-serve")
    return problems


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

PROMPT = """You are the Orchapod Agent's planner. Turn the user's intent into a workflow plan that runs on Nebius:
Token Factory for Nemotron calls and LoRA fine-tunes, AI Cloud for GPU jobs and endpoints.
Answer with JSON {"rationale": str, "plan": {"name": str, "nodes": [{"id": str, "type": str, "needs": [str], "inputs": {}}]}}.

Rules:
- Node ids are snake_case and unique; "needs" lists the nodes that must finish first.
- Use only the node types in the catalog below, and only the inputs their JSON Schema lists.
- An input is a literal value or exactly one reference "${{ nodes.<id>.outputs.<name> }}" to an output of a node in
  "needs". Plans have no workflow inputs and no resources.
- Every teacher and judge is a Nemotron model on Token Factory. Respect the constraints and caps in the knowledge below,
  and keep the estimate within the budget.
- For the canonical intents, follow the expected plans in the knowledge below.
- rationale: two to four sentences: why these nodes and models, the cost and time, and what the plan leaves out
  (for example: no training).

Knowledge (docs/agent_knowledge.md):
"""


def _system_prompt() -> str:
    catalog = []
    for t, meta in visible().items():
        usd, minutes = TYPICAL.get(t, (0.0, 5))
        schema = json.dumps(meta["inputs_schema"].model_json_schema(), separators=(",", ":"))
        catalog.append(f"- {t} ({meta['runtime']}; typically ${usd:.2f}, {minutes:g} min): {meta['description']}\n"
                       f"  inputs (JSON Schema): {schema}\n  outputs: {', '.join(meta['outputs_schema'].model_fields)}")
    return PROMPT + _knowledge() + "\nNode catalog:\n" + "\n".join(catalog)


def _knowledge() -> str:
    """docs/agent_knowledge.md, read on every request: from the repo root, or /app in the API image."""
    for root in Path(__file__).resolve().parents:
        if (root / "docs/agent_knowledge.md").exists():
            return (root / "docs/agent_knowledge.md").read_text()
    raise FileNotFoundError("docs/agent_knowledge.md (apps/api/Dockerfile.dev copies it to /app/docs)")


def _answer_schema() -> dict:
    """Guided JSON for the planner's answer: the rationale first, so the model explains before it plans."""
    node = {"type": "object", "additionalProperties": False, "required": ["id", "type", "needs", "inputs"],
            "properties": {"id": {"type": "string"}, "type": {"enum": sorted(visible())},
                           "needs": {"type": "array", "items": {"type": "string"}}, "inputs": {"type": "object"}}}
    plan = {"type": "object", "additionalProperties": False, "required": ["name", "nodes"],
            "properties": {"name": {"type": "string"}, "nodes": {"type": "array", "items": node}}}
    return {"type": "object", "additionalProperties": False, "required": ["rationale", "plan"],
            "properties": {"rationale": {"type": "string"}, "plan": plan}}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


async def make_plan(intent: str, db: AsyncSession, scale: float) -> dict:
    """POST /agent/plan (and /workflows/from-prompt): Nemotron 3 Super drafts, and validation errors go back to it
    for up to 2 repairs. 503: kill switch or no NEBIUS_API_KEY; 402: no budget left today; 502: Token Factory failed."""
    if budget.kill_switch():
        raise HTTPException(status_code=503, detail="the kill switch is on (ORCHAPOD_KILL_SWITCH)")
    left = await budget.left(db, None, scale)
    if os.environ.get("STUB") == "1":  # the closest canonical template; no model call
        t = max(templates(), key=lambda t: len(_words(intent) & _words(f"{t['intent']} {t['title']}")))
        errors, warnings, est = review(t["plan"], left)
        return {"plan": t["plan"], "rationale": f"STUB=1: the canonical plan '{t['slug']}'. {t['rationale']}",
                "estimate": est, "warnings": warnings, "errors": errors}
    if not (os.environ.get("NEBIUS_API_KEY") or "").strip():
        raise HTTPException(status_code=503, detail="NEBIUS_API_KEY is not set")
    if left[0] <= 0:
        raise HTTPException(status_code=402, detail=f"{left[1]} cap ${left[2]:g}: nothing left")
    messages = [{"role": "system", "content": _system_prompt()}, {"role": "user", "content": intent}]
    for attempt in range(3):  # the draft, then up to 2 repairs
        try:
            out = await budget.control_plane(db, "planner", lambda tf: tf.chat(
                messages, SUPER, json_schema=_answer_schema(), temperature=0.0, max_tokens=4096, thinking=False,
                read_timeout=300))  # one slow call must not be re-sent and billed twice
        except ProviderError as e:
            raise HTTPException(status_code=502, detail=str(e))
        except Exception as e:  # a 2xx the client could not read (missing keys, wrong types)
            raise HTTPException(status_code=502, detail=f"token_factory unreadable reply: {e!r}")
        answer = out["parsed"] if isinstance(out["parsed"], dict) else {}
        plan = answer.get("plan") if isinstance(answer.get("plan"), dict) else {"name": "", "nodes": []}
        errors, warnings, est = review(plan, left)
        if not errors or attempt == 2:
            break
        messages += [{"role": "assistant", "content": out["text"]},
                     {"role": "user", "content": "Fix these errors and answer with the whole corrected JSON:\n"
                                                 + "\n".join(f"- {e}" for e in errors)}]
    return {"plan": plan, "rationale": str(answer.get("rationale") or ""), "estimate": est,
            "warnings": warnings, "errors": errors}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

REPORT_PROMPT = """You write the report of one Orchapod Agent run for the person who asked for it: Markdown, at most 250
words, with the sections "## What ran" (one line per node), "## Results" (the metrics that matter, such as win rate,
rows, loss), "## Cost" (spent against the estimate) and "## How to use it" (download links from the artifacts'
download_url, or the model to call). Use only the facts given. If the run failed, name the failed node and its error,
and say that Retry node resumes from it."""


async def write_report(agent_run: AgentRun, summary: dict, db: AsyncSession, scale: float) -> str:
    """Nemotron 3.5 Lightning writes the report; STUB=1, the kill switch, an empty day budget or a failed call fall back
    to the deterministic template."""
    if os.environ.get("STUB") != "1" and not budget.kill_switch() and (await budget.left(db, None, scale))[0] > 0:
        facts = json.dumps({"intent": agent_run.intent, "plan": agent_run.plan, "estimate": agent_run.estimate,
                            "run": summary}, default=str)[:20_000]
        try:
            out = await budget.control_plane(db, "reporter", lambda tf: tf.chat(
                [{"role": "system", "content": REPORT_PROMPT}, {"role": "user", "content": facts}],
                LIGHTNING, temperature=0.0, max_tokens=1200, thinking=False))
            if out["text"].strip():
                return out["text"].strip()
        except Exception as e:  # a ProviderError, or a reply the client could not read
            log.warning("report of run %s falls back to the template: %r", agent_run.run_id, e)
    return template_report(agent_run, summary)


def template_report(agent_run: AgentRun, s: dict) -> str:
    lines = [f"## {agent_run.plan.get('name') or 'Agent run'}: {s['status']}", "", f"**Intent:** {agent_run.intent}", "",
             f"**Cost:** ${s['cost_usd']:.4f} of ${agent_run.estimate.get('usd', 0):.2f} estimated.", ""]
    if s.get("error"):
        lines += [f"**Error:** {s['error']} (Retry node resumes from the failed node.)", ""]
    lines += ["| Node | Type | Status | $ |", "| --- | --- | --- | --- |"]
    lines += [f"| {n['node_id']} | {n['type']} | {n['status']} | {n['usd']:.4f} |" for n in s["nodes"]]
    files = [a for a in s["artifacts"] if a.get("download_url") and a["kind"] != "metrics"]
    if files:
        lines += ["", "**Results:**"] + [f"- [{a['node_id']}/{a['name']}]({a['download_url']})" for a in files]
    return "\n".join(lines)
