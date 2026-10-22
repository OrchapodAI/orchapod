"""The canonical intents and the golden path through the Orchapod Agent, through the API only: all four on stubs ($0), or ONE for real.

    python scripts/e2e_agent.py --stub                       # intents 1, 2, 3 and the golden path (4); `make check E2E=1` runs it
    python scripts/e2e_agent.py --stub --intent 2            # one of the four (4, the golden path, is for stub runs only), or any
                                                             # text: the STUB planner answers with the closest canonical plan
    python scripts/e2e_agent.py --intent 2 --max-cost 0.5    # real: one intent (1, 2, 3 or any text), `make agent-e2e INTENT=2 MAX_COST=0.5`

Per canonical intent (1 to 3): POST /agent/plan (the STUB planner must return that intent's canonical plan, error-free, estimate
under the $3 run cap, with the shape docs/agent_knowledge.md gives it: #1 ends in judge-eval, #2 trains nothing, #3 runs quantize
before judge-eval) -> POST /agent/run -> GET /agent/runs/{id}/report every 2 s until `ready`. The golden path (4, R25: research,
synth, prep, unsloth-train, vllm-serve, judge-eval) has no planner matching: a stub run posts template 4's plan straight to
/agent/run, no /agent/plan, at full scale (the stub caps). Asserted: the run succeeded in under 5 minutes with every node's
contract artifacts and a cost_json, cost $0, the report names the plan, the data-prep dataset downloads (intent #2: rows with
exactly the schema's fields), judge-eval's eval_summary has the contract's shape, quantize keep_f16 registers the f16 baseline, and
a vllm-serve node registered a stub-* endpoint (no Nebius call under STUB). It reuses e2e_demo.py: its stack (own API, STUB=1,
throwaway DB, no paid key), image builds (unsloth-train from its slim `stub` stage) and run checks; the images it builds are the
shared orchapod/<node>:dev, so it is opt-in like e2e_demo.py.

Any plan error is a FAIL: a canonical plan that names a node or an input that does not exist is a regression, never a skip.

A real run (--max-cost) spends money, so only the Orchestrator runs it, after a merge, with `.env` loaded (`set -a; . ./.env; set +a`)
and `make up`. The same stack, but the API runs without STUB and the live Nemotron planner answers, so the plan is not the
template's. Its env: ORCHAPOD_MAX_RUN_USD = ORCHAPOD_MAX_DAY_USD = --max-cost, ORCHAPOD_ANON_SCALE = 1, and of e2e_demo.PAID only
NEBIUS_API_KEY, TAVILY_API_KEY and HF_TOKEN, each when set (no VASTAI, RunPod, Anthropic or OpenAI key, no Nebius project id);
the rest of the shell reaches it as it does any non-secret setting, except that NEBIUS_BASE_URL, where the providers send the key,
passes only when it is blank or Token Factory's URL.
- Refused before anything starts, one line: no --max-cost, one at or under 0 or over the $3 run cap, no --intent, `--intent 4` (the
  golden path is a stub run; its real run is e2e_demo.py --max-cost), no NEBIUS_API_KEY, a NEBIUS_BASE_URL that is neither blank nor
  Token Factory's (its value is never shown: a URL can carry userinfo), E2E_BIND_HOST set (the API holds a key, so it listens on
  127.0.0.1 only; it needs Docker Desktop's loopback forwarding).
- Refused before POST /agent/run, one line each: a plan with an error; an estimate over --max-cost; an estimate longer than the hour
  a real run waits (REAL_LIMIT_S); a node that rents a GPU (the golden run, e2e_demo.py --max-cost, owns those and needs G2 quota);
  a node whose key is unset (web-research: TAVILY_API_KEY).
- The run must end within REAL_LIMIT_S, an hour (a stub run keeps e2e_demo.LIMIT_S); past it, it is cancelled. Asserted besides the
  stub's checks: 0 < cost_usd <= --max-cost (a real run that cost $0 called nothing); a structured synth node's dataset (intent #2)
  holds at least 90 % of its n_samples; judge-eval's eval_summary says stub false. e2e_demo.check_run also wants a data-prep node.
- Output: the PASS or FAIL line of the stub (run id, wall time, cost, estimate, report chars; a real PASS line goes on with
  `; eval <node>: n, judged, win_rate, exact_match` for each judge-eval, the numbers LOG.md and the README quote), then the report's first 5 lines, then
  `total $X (run $Y + planner/reporter $Z)`: the PASS line's cost is Run.cost_usd only, and Z, the planner's and the report writer's
  calls, is read from the Spend table of the throwaway DB (main gives the API its own, so it can). X is what to record in
  hackathon/LOG.md, with the run id.
"""

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import e2e_demo as demo
import httpx

sys.path.insert(0, str(demo.ROOT))  # a script's sys.path[0] is scripts/; the node registry is packages/ at the repo root
from packages.workflow_schema.models import NODE_REGISTRY, SynthDistilabelInputs  # noqa: E402

CAP_USD = 3.0  # ORCHAPOD_MAX_RUN_USD: a plan estimated above it can never run
TF_BASE = "https://api.tokenfactory.nebius.com/v1"  # NEBIUS_BASE_URL's default, where the providers send the key (a test pins it to theirs)
# The caps are pinned so a shell's ORCHAPOD_* cannot change the verdict; the UI is anonymous, so full scale is ANON_SCALE=1.
FULL_CAPS = {"ORCHAPOD_ANON_SCALE": "1", "ORCHAPOD_MAX_RUN_USD": f"{CAP_USD:g}", "ORCHAPOD_MAX_DAY_USD": "15"}
REAL_LIMIT_S = 3600  # a real run ends within an hour (intent #3 is estimated at 30 minutes: judge-eval answers on a CPU)
FORWARD = ("NEBIUS_API_KEY", "TAVILY_API_KEY", "HF_TOKEN")  # of e2e_demo.PAID, the only names a real run's API sees, each when set
NEEDS_KEY = {"web-research": "TAVILY_API_KEY"}  # a node type that cannot run without a key beyond NEBIUS_API_KEY (main checks that)
REAL_TIMEOUT_S = 600  # a real run's HTTP calls: the live planner is a model call (up to 300 s a call, with repairs); the stack's is 30 s
# number: (the slug of its template (apps/api/agent/templates/1-…, 2-…, 3-…, 4-…), a rule on the plan's node types in execution order,
# what the rule says). Other templates may exist (a fifth is the golden path's CPU variant), so a plan's shape cannot tell them
# apart, and the default run covers these four and no others. The rules are docs/agent_knowledge.md "Expected plans": a template
# edit that drops a step fails here.
GOLDEN = "4"  # the last of INTENTS: the golden path (R25), whose template is the plan: a stub run posts it to /agent/run, no planner
INTENTS = {
    "1": ("real-estate-compliance", lambda t: t[-1:] == ["judge-eval"], "ends in judge-eval"),
    "2": ("movie-engagement", lambda t: "tf-finetune" not in t, "has no tf-finetune: it trains nothing"),
    "3": ("maths-quantize", lambda t: "quantize" in t and "judge-eval" in t and t.index("quantize") < t.index("judge-eval"),
          "runs quantize before judge-eval"),
    GOLDEN: ("nebius-docs-specialist",
             lambda t: t == ["web-research", "synth-distilabel", "data-prep", "unsloth-train", "vllm-serve", "judge-eval"],
             "is research -> synth -> prep -> unsloth-train -> vllm-serve -> judge-eval (R25)"),
}
SLUGS = {number: slug for number, (slug, _, _) in INTENTS.items()}

EVAL_KEYS = ("n", "judged", "wins", "ties", "losses", "errors", "win_rate", "consistency", "exact_match", "base", "tuned",
             "judge_model", "decoding", "stub", "samples")  # contracts "judge-eval": eval_summary


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/e2e)
# ---------------------------------------------------------------------------

def real_env(max_cost: float, environ=os.environ) -> dict[str, str | None]:
    """api_env's `extra` for a real run: both caps = max_cost at full scale, STUB gone, and of e2e_demo.PAID only FORWARD, each
    when set. Anything else in the shell reaches the API as it does any non-secret setting; so does NEBIUS_BASE_URL, which main
    has already refused unless it is blank or Token Factory's."""
    return FULL_CAPS | {"ORCHAPOD_MAX_RUN_USD": str(max_cost), "ORCHAPOD_MAX_DAY_USD": str(max_cost), "STUB": None} | {
        k: environ[k] for k in FORWARD if environ.get(k, "").strip()}


def spend_line(db: Path) -> str:
    """What a real run cost in all, read from the throwaway DB the API wrote: Run.cost_usd (the PASS line's cost) plus the
    control plane's day ledger (the Spend table: the planner's and the report writer's calls), which the run's cost leaves out.
    This is the figure for hackathon/LOG.md."""
    try:
        with closing(sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=10)) as con:  # looking must not make a DB
            run = con.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM run").fetchone()[0]
            ledger = con.execute("SELECT COALESCE(SUM(usd), 0) FROM spend").fetchone()[0]
    except sqlite3.Error as e:
        return f"total spend unknown, the throwaway DB could not be read ({e}): the run's cost leaves out the planner and the reporter"
    return f"total ${run + ledger:.4f} (run ${run:.4f} + planner/reporter ${ledger:.4f})"


def refusals(plan: dict, environ=os.environ) -> list[str]:
    """Why a real run must not start this plan, a line each: a node that rents a GPU (runtime gpu, or rents_gpu: vllm-serve's
    endpoint), a node whose key is unset. They are refused before /agent/run, so nothing is spent on the nodes before them."""
    lines = []
    for n in plan["nodes"]:
        row = NODE_REGISTRY.get(n["type"], {})
        if row.get("runtime") == "gpu" or row.get("rents_gpu"):
            lines.append(f"{n['type']} {n['id']!r} rents a GPU: only the golden run (scripts/e2e_demo.py --max-cost) starts one, "
                         "and it needs G2 quota")
        if (key := NEEDS_KEY.get(n["type"])) and not environ.get(key, "").strip():
            lines.append(f"{n['type']} {n['id']!r} needs {key}, which is unset")
    return lines


def canonical(templates: list[dict], number: str) -> dict | None:
    """The template of canonical intent 1, 2 or 3, or of the golden path (4)."""
    return next((t for t in templates if t["slug"] == SLUGS[number]), None)


def label_of(number: str) -> str:
    return "golden path" if number == GOLDEN else f"intent #{number}"


def name_of(number: str) -> str:
    return "the golden path" if number == GOLDEN else f"canonical intent #{number}"


def plan_for(c: httpx.Client, intent: str, template: dict | None, number: str | None) -> tuple[dict, dict, list[str]]:
    """(plan, estimate, errors): the planner's answer for the intent, except for the golden path of a stub run, whose template is
    the plan (a real run has no template and asks the live planner). A plan with errors is refused by /agent/run, which is strict."""
    if template and number == GOLDEN:
        return template["plan"], template["estimate"], []
    reply = demo.call(c, "POST", "/agent/plan", json={"intent": intent})
    return reply["plan"], reply["estimate"], reply["errors"]


def node_types(plan: dict) -> list[str]:
    """The plan's node types in execution order: a node after the nodes it needs, ties in plan order."""
    done, order = set(), []
    while len(order) < len(plan["nodes"]):
        ready = next((n for n in plan["nodes"] if n["id"] not in done and set(n.get("needs", [])) <= done), None)
        if ready is None:
            break  # a cycle: the planner reports it
        done.add(ready["id"])
        order.append(ready["type"])
    return order


def check_eval_summary(s, exact_match: bool, stub: bool = True) -> list[str]:
    """The shape the eval view reads (contracts "judge-eval"): all keys, sane counts and rates, `stub` as the run is (a real
    run's summary says stub false), verdicts valid."""
    if not isinstance(s, dict):
        return ["eval_summary is not a JSON object"]
    if missing := [k for k in EVAL_KEYS if k not in s]:
        return [f"eval_summary has no {', '.join(missing)}"]
    problems = []
    counts = [s["n"], s["wins"], s["ties"], s["losses"], s["errors"]]
    if not all(type(x) is int and x >= 0 for x in counts):
        problems.append(f"n, wins, ties, losses and errors must be counts, not {counts}")
    elif s["wins"] + s["ties"] + s["losses"] > s["n"]:
        problems.append(f"{s['wins']} wins + {s['ties']} ties + {s['losses']} losses are more than the {s['n']} rows")
    for k in ("win_rate", "consistency"):
        if s[k] is not None and not (isinstance(s[k], (int, float)) and 0 <= s[k] <= 1):
            problems.append(f"{k} is {s[k]!r}, not a share in [0, 1]")
    if s["stub"] is not stub:
        problems.append(f"stub is {s['stub']!r} in a {'STUB' if stub else 'real'} run")
    if bool(s["exact_match"]) != exact_match:
        problems.append(f"exact_match is {s['exact_match']!r} but the plan asked for exact_match={exact_match}")
    if not isinstance(s["samples"], list) or any(
            not isinstance(v, dict) or v.get("verdict") not in ("win", "tie", "loss", None) for v in s["samples"]):
        problems.append("samples must be a list of verdicts with verdict win | tie | loss | null")
    return problems


def check_report(report: dict, intent: str, plan: dict, max_cost: float | None = None) -> list[str]:
    """What is wrong with the finished run and its report; empty = fine. A real run (max_cost) is held to demo.check_run's real
    rule: more than $0 and at most max_cost."""
    problems = demo.check_run(report, max_cost)
    if report["status"] != "succeeded":
        return problems
    if report["intent"] != intent:
        problems.append(f"the report is for the intent {report['intent']!r}, not the one asked")
    text = (report["markdown"] or "").strip()
    title = " ".join(plan["name"].split())[:80]  # as the report titles it (backend-w7): whitespace collapsed, cut at 80 characters
    if not report["ready"] or not text:
        problems.append("the run ended but the report is not ready (ready, markdown)")
    elif title not in text:
        problems.append(f"the report never names the plan {title!r}")
    return problems


def check_row_count(c: httpx.Client, report: dict, plan: dict) -> list[str]:
    """A structured synth node (intent #2) asks for n_samples rows: the data-prep dataset holds at least 90 % of them."""
    synth = demo.synth_inputs(plan) or {}
    if synth.get("pipeline_template") != "structured":
        return []
    asked = int(synth.get("n_samples") or SynthDistilabelInputs.model_fields["n_samples"].default)
    prep = next(n["node_id"] for n in report["nodes"] if n["type"] == "data-prep")
    text, problem = demo.download(c, report, prep, "dataset")
    if problem:
        return [problem]
    rows = sum(1 for line in text.splitlines() if line.strip())
    return [f"the dataset has {rows} rows, under 90 % of the {asked} asked (n_samples)"] if rows * 10 < asked * 9 else []


def eval_numbers(node_id: str, s: dict) -> str:
    """A real run's judge as LOG.md and the README quote it: rows asked and judged, the pairwise win rate, the exact-match scores."""
    return f"; eval {node_id}: n {s['n']}, judged {s['judged']}, win_rate {json.dumps(s['win_rate'])}, exact_match {json.dumps(s['exact_match'])}"


def check_outputs(c: httpx.Client, report: dict, plan: dict, max_cost: float | None = None, evals: list | None = None) -> list[str]:
    """What a finished plan promised beyond its artifacts existing: data rows, the eval summary, the f16 baseline. `evals`, if given,
    collects (node id, eval_summary) of each judge-eval it read, for a real run's PASS line."""
    problems = demo.fetch_dataset(c, report, plan)
    if max_cost is not None and not problems:
        problems = check_row_count(c, report, plan)
    for node in plan["nodes"]:
        made = {a["name"] for a in report["artifacts"] if a["node_id"] == node["id"]}
        inputs = node.get("inputs") or {}
        if node["type"] == "quantize" and inputs.get("keep_f16") and "gguf_f16" not in made:
            problems.append(f"quantize {node['id']!r} has keep_f16 but did not register gguf_f16")
        if node["type"] == "vllm-serve" and max_cost is None:  # STUB makes no Nebius call: its endpoint is a stub-* id, never a real one
            ids = [a["meta"].get("endpoint_id") for a in report["artifacts"] if a["node_id"] == node["id"] and a["name"] == "endpoint_url"]
            if not any(str(i).startswith("stub-") for i in ids):
                problems.append(f"vllm-serve {node['id']!r} registered no stub-* endpoint (endpoint_url: {ids or 'none'})")
        if node["type"] == "judge-eval":
            text, problem = demo.download(c, report, node["id"], "eval_summary")
            try:
                summary = None if problem else json.loads(text)
            except ValueError:
                problem = f"{node['id']}.eval_summary is not JSON: {text[:60]!r}"
            problems += [problem] if problem else check_eval_summary(summary, bool(inputs.get("exact_match")), max_cost is None)
            if not problem and isinstance(summary, dict) and evals is not None:
                evals.append((node["id"], summary))
    return problems


# ---------------------------------------------------------------------------
# The run, through the API
# ---------------------------------------------------------------------------

def show(verb: str, label: str, lines: list[str], note: str = "") -> None:
    print("\n".join([f"e2e {verb} {label}{note}", *(f"  - {x}" for x in lines)]), flush=True)


def run_one(c: httpx.Client, label: str, intent: str, template: dict | None, number: str | None = None,
            max_cost: float | None = None) -> str:
    """One intent: PASS or FAIL. `number` is the canonical intent, None for free text. `max_cost` makes it a real run: the live
    planner answers, so there is no template to compare with, and a plan that would spend wrongly is refused before /agent/run."""
    limit = demo.LIMIT_S if max_cost is None else REAL_LIMIT_S
    demo.say(f"--- {label}: {intent!r}")
    plan, estimate, errors = plan_for(c, intent, template, number)
    problems = []
    if template and plan != template["plan"]:
        problems.append("the STUB planner did not answer this canonical intent with its canonical plan")
    if template and estimate != template["estimate"]:
        problems.append(f"the plan's estimate {estimate['usd']} differs from the template's {template['estimate']['usd']}")
    if number and not INTENTS[number][1](types := node_types(plan)):
        problems.append(f"the plan of {name_of(number)} {INTENTS[number][2]} (docs/agent_knowledge.md), but this one runs {types}")
    problems += errors
    if estimate["usd"] > (CAP_USD if max_cost is None else max_cost):
        cap = f"the ${CAP_USD:g} run cap" if max_cost is None else f"--max-cost ${max_cost:g}"
        problems.append(f"the estimate ${estimate['usd']} is over {cap}")
    if max_cost is not None:
        problems += refusals(plan)
        if estimate["minutes"] * 60 > REAL_LIMIT_S:  # a run the poll would cancel before it could end
            problems.append(f"the estimate takes {estimate['minutes']:g} min, over the {REAL_LIMIT_S / 60:g} min a real run waits")
    if not problems:
        demo.say(f"plan {plan['name']!r}: {[n['id'] for n in plan['nodes']]}, estimate ${estimate['usd']} / {estimate['minutes']} min")
        if stack := demo.preflight():
            problems = ["the stack is not ready:"] + [f"  {p}" for p in stack]
        elif err := demo.build_images([n["type"] for n in plan["nodes"]]):
            problems = [err]
    if problems:
        show("FAIL", label, problems)
        return "FAIL"
    started = demo.call(c, "POST", "/agent/run", json={"intent": intent, "plan": plan})  # run_id, cancel_token (once), ...
    run_id = started["run_id"]
    report, seconds = demo.poll_run(c, run_id, f"/agent/runs/{run_id}/report", done=lambda r: r["ready"],
                                    cancel_token=started["cancel_token"], limit=limit)
    problems = check_report(report, intent, plan, max_cost)
    if seconds >= limit:
        problems.append(f"the run did not end within {limit} s, so it was cancelled")
    evals = [] if max_cost is not None else None  # a stub's judge numbers are fake: only a real run quotes them
    if not problems:
        problems = check_outputs(c, report, plan, max_cost, evals)
    cost = "$0" if max_cost is None else f"${report['cost_usd']:.4f}"
    if problems:  # a real run's FAIL says what it cost: that is what the Orchestrator logs
        facts = f"run {run_id} after {seconds:.0f} s" + ("" if max_cost is None else f", cost {cost}, estimate ${estimate['usd']}")
        show("FAIL", label, problems, f" ({facts})")
    else:
        demo.say(f"PASS {label}: run {run_id} succeeded in {seconds:.0f} s (limit {limit} s), cost {cost}, "
                 f"estimate ${estimate['usd']}, report ready ({len(report['markdown'])} chars)" + "".join(eval_numbers(i, e) for i, e in evals or []))
    if max_cost is not None and report["markdown"]:
        demo.say("report, first 5 lines:")
        print("\n".join(report["markdown"].splitlines()[:5]), flush=True)
    return "FAIL" if problems else "PASS"


def run_all(c: httpx.Client, which: str | None, max_cost: float | None = None) -> int:
    if max_cost is not None:
        c.timeout = REAL_TIMEOUT_S  # the stack's client waits 30 s
    templates = demo.get_templates(c)
    todo = []  # (label, intent text, its canonical template and number, or None for free text)
    for number in [which] if which in INTENTS else [] if which else list(INTENTS):
        template = canonical(templates, number)
        if template is None:
            return demo.fail(f"{len(templates)} templates, none is {name_of(number)} (slug {SLUGS[number]!r})")
        todo.append((label_of(number), template["intent"], template if max_cost is None else None, number))
    if which and which not in INTENTS:
        todo.append(("free-text intent", which, None, None))
    results = {}
    for label, intent, template, number in todo:
        try:
            results[label] = run_one(c, label, intent, template, number, max_cost)
        except RuntimeError as e:  # an HTTP error from the API fails this intent, not the others
            show("FAIL", label, [str(e)])
            results[label] = "FAIL"
    count = {r: list(results.values()).count(r) for r in ("PASS", "FAIL")}
    demo.say(f"{count['PASS']} PASS, {count['FAIL']} FAIL: " + ", ".join(f"{label} {r}" for label, r in results.items()))
    return 1 if count["FAIL"] else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="E2E of the canonical intents and the golden path through the Agent, on stubs or one for real "
                                             "(see the module docstring).")
    ap.add_argument("--stub", action="store_true", help="STUB=1: $0, no keys, no network beyond the local stack")
    ap.add_argument("--intent", help="1, 2 or 3 (a canonical intent), or any text; 4 is the golden path, for stub runs only; "
                                     "stub default: the four; a real run needs one of the others")
    ap.add_argument("--max-cost", type=float, help=f"USD cap of a real run, above 0 and at most ${CAP_USD:g}; a real run is refused without it")
    args = ap.parse_args(argv)
    if args.stub:
        return demo.with_stack(lambda c: run_all(c, args.intent), FULL_CAPS)
    cost, intent = args.max_cost, (args.intent or "").strip()
    if cost is None or not cost > 0:  # `not > 0` also refuses nan
        ap.error("refusing to run without --max-cost: a real run spends money, so it needs a USD cap above 0")
    if cost > CAP_USD:
        ap.error(f"refusing --max-cost {cost:g}: the project caps a run at ${CAP_USD:g}")
    if not intent:
        ap.error("refusing to run without --intent: a real run takes one intent, 1, 2, 3 or any text")
    if intent == GOLDEN:  # it would spend a planner call and then meet the GPU refusal
        ap.error(f"refusing --intent {GOLDEN}: the golden path is a stub run (--stub --intent {GOLDEN}); its real run rents GPUs, "
                 "so it is e2e_demo.py --max-cost")
    if not os.environ.get("NEBIUS_API_KEY", "").strip():
        ap.error("refusing to run: NEBIUS_API_KEY is unset (the Agent plans with Nemotron on Token Factory; load .env: set -a; . ./.env; set +a)")
    if os.environ.get("NEBIUS_BASE_URL", "").strip().rstrip("/") not in ("", TF_BASE):  # the providers send the key where it points
        ap.error("refusing to run: NEBIUS_BASE_URL is not Token Factory's URL and the key would go there (unset it; its value is not shown)")
    if os.environ.get("E2E_BIND_HOST"):  # blank counts as unset, as in demo.bind_host
        ap.error("refusing to run: E2E_BIND_HOST is set, but the API of a real run holds your key and listens on 127.0.0.1 only (unset it)")
    with tempfile.TemporaryDirectory(prefix="orchapod-e2e-db-") as tmp:  # the API's DB is ours to read: its ledger is the spend
        db = Path(tmp) / "e2e.db"

        def go(c):
            try:
                return run_all(c, intent, cost)
            finally:  # also when interrupted: the API is still up, and its ledger holds the planner's and the reporter's calls
                demo.say(spend_line(db))

        return demo.with_stack(go, real_env(cost) | {"DATABASE_URL": f"sqlite+aiosqlite:///{db}"})


if __name__ == "__main__":
    sys.exit(main())
