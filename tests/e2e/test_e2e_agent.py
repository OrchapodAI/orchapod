"""scripts/e2e_agent.py: the logic around the stub e2e of the canonical intents. The run is `make check E2E=1` (Docker, `make up`)."""

import json
from pathlib import Path

import e2e_agent as agent
import httpx
import pytest

from api.agent import planner

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = [json.loads(f.read_text()) for f in sorted((ROOT / "apps/api/agent/templates").glob("*.json"))]
TEMPLATES = [{**t, "estimate": planner.estimate(t["plan"])[0]} for t in SHIPPED]  # what GET /agent/templates serves
I1, I2, I3 = (agent.canonical(TEMPLATES, n) for n in "123")

# What the planner says about templates #1 and #3 on the wave-2 tree (backend-w2's report).
ERRORS_1 = ["serve: unknown input 'lora_adapter'",
            "serve: no GPU provider in provider_pref ['nebius'] is configured (nebius needs NEBIUS_PROJECT_ID)",
            "evaluate: unknown node type 'judge-eval'"]
ERRORS_3 = ["quantize: unknown input 'keep_f16'", "evaluate: unknown node type 'judge-eval'"]


def fake_api(errors_by_intent=None, plan_for=None, status=200):
    """GET /agent/templates and POST /agent/plan the way the STUB planner answers them (plan_for overrides the plan)."""
    errors_by_intent = errors_by_intent or {}

    def handler(request):
        if request.url.path == "/agent/templates":
            return httpx.Response(200, json=TEMPLATES)
        if request.url.path == "/agent/plan":
            intent = json.loads(request.content)["intent"]
            t = next(t for t in TEMPLATES if t["intent"] == intent)
            body = {"plan": (plan_for or {}).get(intent, t["plan"]), "rationale": "", "estimate": t["estimate"], "warnings": [],
                    "errors": errors_by_intent.get(intent, [])}
            return httpx.Response(status, json=body)
        raise AssertionError(f"unexpected {request.method} {request.url.path}: a SKIP or a plan FAIL must stop before any run")

    return httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler))


# --- which template is which intent ---------------------------------------------------------------------------------------

def test_canonical_intents_are_found_by_what_their_plan_contains():
    assert {t["slug"] for t in (I1, I2, I3)} == {t["slug"] for t in TEMPLATES}, "each template is exactly one canonical intent"
    assert any(n["type"] == "tf-finetune" for n in I1["plan"]["nodes"])
    assert any(n["type"] == "quantize" for n in I3["plan"]["nodes"])
    assert agent.canonical([], "1") is None and agent.canonical([I1, I2], "3") is None


# --- SKIP: only the named gaps -------------------------------------------------------------------------------------------

def test_skip_reasons_name_each_missing_piece_once():
    r1 = agent.skip_reasons(ERRORS_1, I1["plan"])
    assert r1 == [agent.VLLM, "ml-w3: judge-eval is not in NODE_REGISTRY"]  # two vllm-serve errors, one reason
    r3 = agent.skip_reasons(ERRORS_3, I3["plan"])
    assert r3 == ["ml-w3: quantize has no keep_f16 (R11)", "ml-w3: judge-eval is not in NODE_REGISTRY"]
    after_judge_eval = ["serve: unknown input 'lora_adapter'", "serve: no GPU provider in provider_pref ['nebius'] is configured",
                        "evaluate: base_model_ref: serve (vllm-serve) has no output 'base_model_ref'",
                        "evaluate: tuned_model_ref: serve (vllm-serve) has no output 'model_ref'"]
    assert agent.skip_reasons(after_judge_eval, I1["plan"]) == [agent.VLLM]
    assert agent.skip_reasons(["evaluate: base_model_ref: quantize (quantize) has no output 'gguf_f16'"], I3["plan"]) == [
        "ml-w3: quantize has no gguf_f16 (R11)"]


def test_anything_else_is_not_a_skip():
    assert agent.skip_reasons([], I1["plan"]) is None  # nothing wrong: it runs
    assert agent.skip_reasons(ERRORS_1 + ["synth: unknown input 'bogus'"], I1["plan"]) is None  # one stray error spoils it
    assert agent.skip_reasons(["plan: the estimate $9.00 is more than the $3.00 left"], I1["plan"]) is None
    # "no GPU provider" excuses vllm-serve only; for another node it is a real problem
    assert agent.skip_reasons(["research: no GPU provider in provider_pref ['nebius'] is configured"], I1["plan"]) is None
    assert agent.skip_reasons(["nope: unknown input 'lora_adapter'"], I1["plan"]) is None  # not even a node of the plan


def test_every_planner_error_on_a_shipped_template_is_a_named_gap_or_gone():
    """If the planner's wording drifts, the SKIP stops matching and the e2e fails loudly, so catch it here first."""
    for t in SHIPPED:
        errors, _, _ = planner.review(t["plan"])
        assert not errors or agent.skip_reasons(errors, t["plan"]), (t["slug"], errors)


# --- exit codes: a SKIP is not a pass --------------------------------------------------------------------------------------

@pytest.mark.parametrize("number, errors", [("1", ERRORS_1), ("3", ERRORS_3)])
def test_a_skip_exits_0_and_strict_makes_it_3(number, errors, capsys):
    template = agent.canonical(TEMPLATES, number)
    api = fake_api({template["intent"]: errors})
    assert agent.run_all(api, number, strict=False) == 0
    out = capsys.readouterr().out
    assert f"e2e SKIP intent #{number} (this is NOT a pass" in out and "1 SKIP (not passes)" in out
    assert all(reason in out for reason in agent.skip_reasons(errors, template["plan"])), "the missing pieces are named"
    assert agent.run_all(api, number, strict=True) == 3
    assert "--strict turns it into a failure" in out


def test_an_unexpected_plan_error_fails_and_a_skip_never_hides_it(capsys):
    errors = ERRORS_3 + ["gsm8k: hf_split: Input should be a valid string"]
    assert agent.run_all(fake_api({I3["intent"]: errors}), "3", strict=False) == 1
    out = capsys.readouterr().out
    assert "e2e FAIL intent #3" in out and "hf_split" in out and "SKIP" not in out.replace("0 SKIP", "")


@pytest.mark.parametrize("errors", [[], ERRORS_1])  # ERRORS_1 are named gaps of the plan it answered with: still no SKIP
def test_a_planner_that_answers_with_another_plan_fails_even_when_its_errors_are_named_gaps(errors, capsys):
    api = fake_api({I3["intent"]: errors}, plan_for={I3["intent"]: I1["plan"]})
    assert agent.run_all(api, "3", strict=False) == 1
    out = capsys.readouterr().out
    assert "e2e FAIL intent #3" in out and "canonical plan" in out


def test_an_estimate_over_the_run_cap_fails(capsys):
    over = {**I2, "estimate": {**I2["estimate"], "usd": 3.5}}
    handler = lambda r: httpx.Response(  # noqa: E731
        200, json=[over] if r.url.path == "/agent/templates" else {"plan": over["plan"], "estimate": over["estimate"], "errors": []})
    api = httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler))
    assert agent.run_all(api, "2", strict=False) == 1
    assert "over the $3 run cap" in capsys.readouterr().out


def test_an_api_error_fails_that_intent_not_the_script(capsys):
    assert agent.run_all(fake_api(status=500), "1", strict=False) == 1
    assert "POST /agent/plan -> HTTP 500" in capsys.readouterr().out


def test_a_missing_canonical_template_is_a_failure_not_a_skip(capsys):
    api = httpx.Client(base_url="http://api", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[I2])))
    assert agent.run_all(api, "3", strict=False) == 1
    assert "none is canonical intent #3" in capsys.readouterr().out


# --- the real run is refused without a cap -----------------------------------------------------------------------------------

REFUSED = "refusing to run without --max-cost"


@pytest.mark.parametrize("argv, message", [
    (["--intent", "Quantize a model"], REFUSED),
    (["--intent", "Quantize a model", "--max-cost", "0"], REFUSED),
    (["--intent", "Quantize a model", "--max-cost", "-1"], REFUSED),
    ([], REFUSED),
    (["--intent", "Quantize a model", "--max-cost", "3"], "only --stub exists"),  # capped, but the real run is not written yet
])
def test_a_real_run_is_refused_without_max_cost(argv, message, capsys):
    with pytest.raises(SystemExit) as e:
        agent.main(argv)
    err = capsys.readouterr().err
    assert e.value.code == 2 and message in err and (message == REFUSED) == (REFUSED in err), err


# --- the report and the outputs -----------------------------------------------------------------------------------------------

def good_report(plan_name="movie-engagement-synthetic-data", intent="Generate synthetic data"):
    from tests.e2e.test_e2e_demo import good_summary

    return {**good_summary(), "intent": intent, "estimate": {"usd": 0.15}, "ready": True,
            "markdown": f"## {plan_name}: succeeded\n\n**Cost:** $0.0000 of $0.15 estimated."}


def test_a_good_report_passes():
    assert agent.check_report(good_report(), "Generate synthetic data", I2["plan"]) == []


def test_check_report_says_what_is_missing():
    plan = I2["plan"]
    ask = "Generate synthetic data"
    assert any("not ready" in p for p in agent.check_report({**good_report(), "ready": False, "markdown": None}, ask, plan))
    assert any("not ready" in p for p in agent.check_report({**good_report(), "markdown": "  "}, ask, plan))
    assert any("never names the plan" in p for p in agent.check_report(good_report("another-plan"), ask, plan))
    assert any("not the one asked" in p for p in agent.check_report(good_report(), "something else", plan))
    failed = {**good_report(), "status": "failed", "error": "exit 1: boom", "markdown": None, "ready": False}
    failed["nodes"][1] |= {"status": "failed", "error": "exit 1: boom"}
    problems = agent.check_report(failed, ask, plan)
    assert any("exit 1: boom" in p for p in problems) and not any("report" in p for p in problems), problems


def eval_summary(**changes):
    verdict = {"i": 0, "question": "q", "reference": "r", "context": None, "source_url": None, "base": "a", "tuned": "b",
               "base_correct": None, "tuned_correct": None, "verdict": "win", "error": None,
               "judgments": [{"order": "tuned_first", "winner": "tuned", "reasoning": "x"},
                             {"order": "base_first", "winner": "tuned", "reasoning": "y"}]}
    ref = {"base_url": "https://api.tokenfactory.nebius.com/v1", "model": "m", "api_key_env": "NEBIUS_API_KEY", "base_model": None}
    return {"n": 2, "judged": 2, "wins": 1, "ties": 1, "losses": 0, "errors": 0, "win_rate": 0.75, "consistency": 0.5,
            "exact_match": None, "base": ref, "tuned": ref, "judge_model": "nvidia/Nemotron-3-Ultra-550b-a55b",
            "decoding": {"temperature": 0.0, "max_tokens": 512}, "stub": True,
            "samples": [verdict, {**verdict, "i": 1, "verdict": "tie"}]} | changes


def test_check_eval_summary_accepts_the_contract_shape():
    assert agent.check_eval_summary(eval_summary(), exact_match=False) == []
    assert agent.check_eval_summary(eval_summary(exact_match={"base": 0.4, "tuned": 0.5}), exact_match=True) == []
    assert agent.check_eval_summary(eval_summary(win_rate=None, consistency=None, samples=[]), exact_match=False) == []


@pytest.mark.parametrize("changes, text", [
    ({"wins": 3}, "more than the 2 rows"),
    ({"errors": -1}, "must be counts"),
    ({"ties": 1.5}, "must be counts"),
    ({"win_rate": 1.5}, "win_rate"),
    ({"consistency": "high"}, "consistency"),
    ({"stub": False}, "stub is False"),
    ({"exact_match": {"base": 0, "tuned": 1}}, "exact_match"),
    ({"samples": [{"verdict": "maybe"}]}, "samples"),
    ({"samples": "none"}, "samples"),
])
def test_check_eval_summary_flags(changes, text):
    problems = agent.check_eval_summary(eval_summary(**changes), exact_match=False)
    assert any(text in p for p in problems), problems


def test_check_eval_summary_names_missing_keys_and_wants_exact_match_when_asked():
    s = eval_summary()
    del s["consistency"], s["decoding"]
    assert agent.check_eval_summary(s, False) == ["eval_summary has no consistency, decoding"]
    assert any("exact_match" in p for p in agent.check_eval_summary(eval_summary(), exact_match=True))
    assert agent.check_eval_summary([], False) == ["eval_summary is not a JSON object"]


def report_with(files: dict, nodes: dict):
    """A report whose artifacts are served at /d/<node>/<name> from `files`; nodes = {id: type}."""
    arts = [{"id": f"{i}-{n}", "node_id": i, "name": n, "kind": "metrics", "uri": "r2://b/x", "download_url": f"/d/{i}/{n}", "meta": {}}
            for i, n in files]
    return {"nodes": [{"node_id": i, "type": t, "status": "succeeded", "usd": 0.0, "error": None} for i, t in nodes.items()],
            "artifacts": arts}


def download_client(texts: dict):
    return httpx.Client(base_url="http://api", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text=texts[r.url.path]) if r.url.path in texts else httpx.Response(404)))


def test_check_outputs_reads_the_eval_summary_and_the_f16_baseline():
    plan = I3["plan"]
    plan = {**plan, "nodes": [dict(n, id=n["id"]) for n in plan["nodes"]]}  # download, quantize, gsm8k, evaluate
    rows = json.dumps({"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]})
    files = [("gsm8k", "dataset"), ("quantize", "gguf_file"), ("quantize", "gguf_f16"), ("evaluate", "eval_summary")]
    nodes = {"download": "hf-download", "quantize": "quantize", "gsm8k": "data-prep", "evaluate": "judge-eval"}
    texts = {"/d/gsm8k/dataset": rows + "\n", "/d/evaluate/eval_summary": json.dumps(eval_summary(exact_match={"base": 0, "tuned": 1}))}
    assert agent.check_outputs(download_client(texts), report_with(files, nodes), plan) == []
    # no f16 baseline although keep_f16 asked for one
    problems = agent.check_outputs(download_client(texts), report_with([f for f in files if f[1] != "gguf_f16"], nodes), plan)
    assert problems == ["quantize 'quantize' has keep_f16 but did not register gguf_f16"]
    # an eval_summary that is not JSON, or one that breaks the contract, is named
    texts["/d/evaluate/eval_summary"] = "<html>"
    assert any("not JSON" in p for p in agent.check_outputs(download_client(texts), report_with(files, nodes), plan))
    texts["/d/evaluate/eval_summary"] = json.dumps(eval_summary(stub=False, exact_match={"base": 0, "tuned": 1}))
    assert any("stub is False" in p for p in agent.check_outputs(download_client(texts), report_with(files, nodes), plan))
    del texts["/d/evaluate/eval_summary"]
    assert any("HTTP 404" in p for p in agent.check_outputs(download_client(texts), report_with(files, nodes), plan))


def test_intent_2_outputs_are_the_downloaded_rows_with_exactly_the_schema_fields():
    nodes = {"synth": "synth-distilabel", "prep": "data-prep"}
    files = [("prep", "dataset")]
    row = {"user_id": "u", "movie_title": "t", "action": "like", "timestamp": "2026-01-01T00:00:00Z", "device": "tv"}
    ok = {"/d/prep/dataset": json.dumps(row) + "\n"}
    assert agent.check_outputs(download_client(ok), report_with(files, nodes), I2["plan"]) == []
    bad = {"/d/prep/dataset": json.dumps(row | {"extra": 1})}
    assert any("extra" in p for p in agent.check_outputs(download_client(bad), report_with(files, nodes), I2["plan"]))
