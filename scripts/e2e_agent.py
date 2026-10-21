"""Stub e2e of the three canonical intents through the Orchapod Agent, through the API only: $0.

    python scripts/e2e_agent.py --stub                       # all three; `make check E2E=1` runs it (a SKIP does not fail it)
    python scripts/e2e_agent.py --stub --intent 2            # one canonical intent (1, 2 or 3), or any text: the STUB planner
                                                             # answers with the closest canonical plan
    python scripts/e2e_agent.py --intent "..." --max-cost 3  # real (`make agent-e2e INTENT=...`): refuses without --max-cost

Per intent: POST /agent/plan (the STUB planner must return that intent's canonical plan, error-free, estimate under the $3 run
cap, with the shape docs/agent_knowledge.md gives it: #1 ends in judge-eval, #2 trains nothing, #3 runs quantize before
judge-eval) -> POST /agent/run -> GET /agent/runs/{id}/report every 2 s until `ready`. Asserted: the run succeeded in under 5
minutes with every node's contract artifacts and a cost_json, cost $0, the report names the plan, the data-prep dataset downloads
(intent #2: rows with exactly the schema's fields), judge-eval's eval_summary has the contract's shape, and quantize
keep_f16 registers the f16 baseline. It reuses e2e_demo.py: its stack (own API, STUB=1, throwaway DB, no paid key), image
builds and run checks; the images it builds are the shared orchapod/<node>:dev, so it is opt-in like e2e_demo.py.

Intent #1 needs vllm-serve to contract (ml-w4; PENDING below). While a plan's errors are exactly that named gap the intent is
SKIPped, loudly: exit 0, and --strict makes it 3. Any other plan error is a FAIL, and so is a gap whose piece has merged.
`make check E2E=1` does not pass --strict until ml-w4 merges; ml-w4's acceptance is `--stub --strict` -> 3 PASS.

The real run is not written: it needs the keys (spike 3). Without --max-cost it refuses, whatever else it is asked.
"""

import argparse
import json
import re
import sys

import e2e_demo as demo
import httpx

CAP_USD = 3.0  # ORCHAPOD_MAX_RUN_USD: a plan estimated above it can never run
# The caps are pinned so a shell's ORCHAPOD_* cannot change the verdict; the UI is anonymous, so full scale is ANON_SCALE=1.
FULL_CAPS = {"ORCHAPOD_ANON_SCALE": "1", "ORCHAPOD_MAX_RUN_USD": f"{CAP_USD:g}", "ORCHAPOD_MAX_DAY_USD": "15"}
# number: (the slug of its template (apps/api/agent/templates/1-…, 2-…, 3-…), a rule on the plan's node types in execution order,
# what the rule says). Other templates may exist (a fourth also fine-tunes), so a plan's shape cannot tell them apart, and the
# default run covers these three and no others. The rules are docs/agent_knowledge.md "Expected plans": a template edit that
# drops a step fails here.
INTENTS = {
    "1": ("real-estate-compliance", lambda t: t[-1:] == ["judge-eval"], "ends in judge-eval"),
    "2": ("movie-engagement", lambda t: "tf-finetune" not in t, "has no tf-finetune: it trains nothing"),
    "3": ("maths-quantize", lambda t: "quantize" in t and "judge-eval" in t and t.index("quantize") < t.index("judge-eval"),
          "runs quantize before judge-eval"),
}
SLUGS = {number: slug for number, (slug, _, _) in INTENTS.items()}

VLLM = ("ml-w4: vllm-serve is not to contract yet (lora_adapter input, model_ref and base_model_ref outputs, runtime api; "
        "contracts \"vllm-serve\")")
# ponytail: THE vllm-serve SKIP LAYER, one deletion. When ml-w4 merges, `python scripts/e2e_agent.py --stub --strict` must print
# 3 PASS; then delete every site tagged SKIP-SITE(ml-w4) (tests/e2e/test_e2e_agent.py checks that this list is complete):
#   scripts/e2e_agent.py    PENDING, VLLM, skip_reasons, the SKIP branch of run_one, the --strict flag
#   scripts/e2e_ui.py       ui_pending's SKIP half (the plan-error check stays) and the E2E_PENDING it sends
#   tests/ui/smoke.spec.ts  PENDING, pending() and its call in the golden path test; the fixture test goes too: that test then
#                           covers the eval view and the playground on real data
#   Makefile                UI_ARGS (ui-smoke --strict)
#   tests/test_harness.py   the assertion that `check E2E=1` runs the agent e2e without --strict
#   tests/e2e/test_e2e_agent.py, tests/e2e/test_e2e_ui.py   the SKIP tests
#   docs/NODE_CONTRACT.md   the SKIP sentence of step 7
# PENDING is (node type or None, regex over the plan error "<node_id>: <problem>", the missing piece). Entries for merged pieces
# (ml-w3: judge-eval, quantize keep_f16) are already gone: a plan that still lacks them is a failure.
PENDING = (  # SKIP-SITE(ml-w4)
    ("vllm-serve", r"unknown input 'lora_adapter'|no GPU provider", VLLM),
    (None, r"\(vllm-serve\) has no output '(base_)?model_ref'", VLLM),
)
EVAL_KEYS = ("n", "judged", "wins", "ties", "losses", "errors", "win_rate", "consistency", "exact_match", "base", "tuned",
             "judge_model", "decoding", "stub", "samples")  # contracts "judge-eval": eval_summary


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/e2e)
# ---------------------------------------------------------------------------

def canonical(templates: list[dict], number: str) -> dict | None:
    """The template of canonical intent 1, 2 or 3."""
    return next((t for t in templates if t["slug"] == SLUGS[number]), None)


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


def skip_reasons(errors: list[str], plan: dict) -> list[str] | None:  # SKIP-SITE(ml-w4)
    """The missing pieces when every plan error is a PENDING one (the intent SKIPs), else None (no error, or one that is
    something else: that is a FAIL, never a SKIP)."""
    types = {n["id"]: n["type"] for n in plan.get("nodes", [])}
    reasons = []
    for error in errors:
        node_id, _, problem = error.partition(": ")
        why = next((why for kind, pattern, why in PENDING
                    if kind in (None, types.get(node_id)) and re.search(pattern, problem)), None)
        if why is None:
            return None
        reasons.append(why)
    return list(dict.fromkeys(reasons)) or None


def check_eval_summary(s, exact_match: bool) -> list[str]:
    """The shape the eval view reads (contracts "judge-eval"): all keys, sane counts and rates, STUB flagged, verdicts valid."""
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
    if s["stub"] is not True:
        problems.append(f"stub is {s['stub']!r} in a STUB run")
    if bool(s["exact_match"]) != exact_match:
        problems.append(f"exact_match is {s['exact_match']!r} but the plan asked for exact_match={exact_match}")
    if not isinstance(s["samples"], list) or any(
            not isinstance(v, dict) or v.get("verdict") not in ("win", "tie", "loss", None) for v in s["samples"]):
        problems.append("samples must be a list of verdicts with verdict win | tie | loss | null")
    return problems


def check_report(report: dict, intent: str, plan: dict) -> list[str]:
    """What is wrong with the finished run and its report; empty = fine."""
    problems = demo.check_run(report)
    if report["status"] != "succeeded":
        return problems
    if report["intent"] != intent:
        problems.append(f"the report is for the intent {report['intent']!r}, not the one asked")
    text = (report["markdown"] or "").strip()
    if not report["ready"] or not text:
        problems.append("the run ended but the report is not ready (ready, markdown)")
    elif plan["name"] not in text:
        problems.append(f"the report never names the plan {plan['name']!r}")
    return problems


def check_outputs(c: httpx.Client, report: dict, plan: dict) -> list[str]:
    """What a finished plan promised beyond its artifacts existing: data rows, the eval summary, the f16 baseline."""
    problems = demo.fetch_dataset(c, report, plan)
    for node in plan["nodes"]:
        made = {a["name"] for a in report["artifacts"] if a["node_id"] == node["id"]}
        inputs = node.get("inputs") or {}
        if node["type"] == "quantize" and inputs.get("keep_f16") and "gguf_f16" not in made:
            problems.append(f"quantize {node['id']!r} has keep_f16 but did not register gguf_f16")
        if node["type"] == "judge-eval":
            text, problem = demo.download(c, report, node["id"], "eval_summary")
            try:
                summary = None if problem else json.loads(text)
            except ValueError:
                problem = f"{node['id']}.eval_summary is not JSON: {text[:60]!r}"
            problems += [problem] if problem else check_eval_summary(summary, bool(inputs.get("exact_match")))
    return problems


# ---------------------------------------------------------------------------
# The run, through the API
# ---------------------------------------------------------------------------

def show(verb: str, label: str, lines: list[str], note: str = "") -> None:
    print("\n".join([f"e2e {verb} {label}{note}", *(f"  - {x}" for x in lines)]), flush=True)


def run_one(c: httpx.Client, label: str, intent: str, template: dict | None, number: str | None = None) -> str:
    """One intent: PASS, SKIP (named gaps only) or FAIL. `number` is the canonical intent, None for free text."""
    demo.say(f"--- {label}: {intent!r}")
    reply = demo.call(c, "POST", "/agent/plan", json={"intent": intent})
    plan, estimate, errors = reply["plan"], reply["estimate"], reply["errors"]
    problems = []
    if template and plan != template["plan"]:
        problems.append("the STUB planner did not answer this canonical intent with its canonical plan")
    if template and estimate != template["estimate"]:
        problems.append(f"the plan's estimate {estimate['usd']} differs from the template's {template['estimate']['usd']}")
    if number and not INTENTS[number][1](types := node_types(plan)):
        problems.append(f"the plan of canonical intent #{number} {INTENTS[number][2]} (docs/agent_knowledge.md), but this one runs {types}")
    if not problems and (reasons := skip_reasons(errors, plan)):  # SKIP-SITE(ml-w4)
        show("SKIP", label, reasons, " (this is NOT a pass: it did not run; --strict turns it into a failure)")
        return "SKIP"
    problems += errors
    if estimate["usd"] > CAP_USD:
        problems.append(f"the estimate ${estimate['usd']} is over the ${CAP_USD:g} run cap")
    if not problems:
        demo.say(f"plan {plan['name']!r}: {[n['id'] for n in plan['nodes']]}, estimate ${estimate['usd']} / {estimate['minutes']} min")
        if stack := demo.preflight():
            problems = ["the stack is not ready:"] + [f"  {p}" for p in stack]
        elif err := demo.build_images([n["type"] for n in plan["nodes"]]):
            problems = [err]
    if problems:
        show("FAIL", label, problems)
        return "FAIL"
    run_id = demo.call(c, "POST", "/agent/run", json={"intent": intent, "plan": plan})["run_id"]
    report, seconds = demo.poll_run(c, run_id, f"/agent/runs/{run_id}/report", done=lambda r: r["ready"])
    problems = check_report(report, intent, plan)
    if seconds >= demo.LIMIT_S:
        problems.append(f"the run did not end within {demo.LIMIT_S} s, so it was cancelled")
    if not problems:
        problems = check_outputs(c, report, plan)
    if problems:
        show("FAIL", label, problems, f" (run {run_id} after {seconds:.0f} s)")
        return "FAIL"
    demo.say(f"PASS {label}: run {run_id} succeeded in {seconds:.0f} s (limit {demo.LIMIT_S} s), cost $0, "
             f"estimate ${estimate['usd']}, report ready ({len(report['markdown'])} chars)")
    return "PASS"


def run_all(c: httpx.Client, which: str | None, strict: bool) -> int:
    templates = demo.get_templates(c)
    todo = []  # (label, intent text, its canonical template and number, or None for free text)
    for number in [which] if which in INTENTS else [] if which else list(INTENTS):
        template = canonical(templates, number)
        if template is None:
            return demo.fail(f"{len(templates)} templates, none is canonical intent #{number} (slug {SLUGS[number]!r})")
        todo.append((f"intent #{number}", template["intent"], template, number))
    if which and which not in INTENTS:
        todo.append(("free-text intent", which, None, None))
    results = {}
    for label, intent, template, number in todo:
        try:
            results[label] = run_one(c, label, intent, template, number)
        except RuntimeError as e:  # an HTTP error from the API fails this intent, not the others
            show("FAIL", label, [str(e)])
            results[label] = "FAIL"
    count = {r: list(results.values()).count(r) for r in ("PASS", "SKIP", "FAIL")}
    demo.say(f"{count['PASS']} PASS, {count['SKIP']} SKIP (not passes), {count['FAIL']} FAIL: "
             + ", ".join(f"{label} {r}" for label, r in results.items()))
    if count["FAIL"]:
        return 1
    return 3 if count["SKIP"] and strict else 0  # SKIP-SITE(ml-w4)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stub e2e of the canonical intents through the Agent (see the module docstring).")
    ap.add_argument("--stub", action="store_true", help="STUB=1: $0, no keys, no network beyond the local stack")
    ap.add_argument("--intent", help="1, 2 or 3 (a canonical intent), or any text; stub default: all three; a real run needs one")
    ap.add_argument("--max-cost", type=float, help="USD cap of a real run; a real run is refused without it")
    ap.add_argument("--strict", action="store_true", help="a SKIP (vllm-serve not merged yet) exits 3 instead of 0")  # SKIP-SITE(ml-w4)
    args = ap.parse_args(argv)
    if not args.stub:
        if args.max_cost is None or args.max_cost <= 0:
            ap.error("refusing to run without --max-cost: a real run spends money, so it needs a USD cap above 0")
        ap.error("only --stub exists so far; the real run is written once the keys exist (spike 3)")
    return demo.with_stack(lambda c: run_all(c, args.intent, args.strict), FULL_CAPS)


if __name__ == "__main__":
    sys.exit(main())
