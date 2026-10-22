"""scripts/e2e_agent.py: the logic around the stub e2e of the canonical intents (the run is `make check E2E=1`: Docker, `make up`),
and the real run of one intent (`make agent-e2e INTENT=2 MAX_COST=0.5`, the Orchestrator's), proved here on a fake API."""

import copy
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import e2e_agent as agent
import e2e_demo as demo
import httpx
import pytest

from api.agent import planner
from tests.e2e.test_e2e_demo import ROW, FakeApi, good_summary, templates_on_disk

SHIPPED = templates_on_disk()
TEMPLATES = [{**t, "estimate": planner.estimate(t["plan"])[0]} for t in SHIPPED]  # what GET /agent/templates serves
I1, I2, I3 = (agent.canonical(TEMPLATES, n) for n in "123")
# data-w4's fourth template: it fine-tunes like #1, and a later template must neither steal an intent nor be run by default
FOURTH = {**I1, "slug": "nebius-docs-specialist", "title": "Llama 8B tuned as a Nebius docs specialist",
          "intent": "Distill a Nebius docs specialist: fine-tune Llama 3.1 8B on the Nebius docs"}

# What the planner said about template #1 before ml-w4's vllm-serve merged: a missing piece, which now fails the e2e.
ERRORS_1 = ["serve: unknown input 'lora_adapter'",
            "serve: no GPU provider in provider_pref ['nebius'] is configured (nebius needs NEBIUS_PROJECT_ID)",
            "evaluate: base_model_ref: serve (vllm-serve) has no output 'base_model_ref'",
            "evaluate: tuned_model_ref: serve (vllm-serve) has no output 'model_ref'"]


@pytest.fixture(autouse=True)
def no_docker(monkeypatch):
    """These are logic tests over a fake API: a plan that reaches the stack check or an image build is a bug in the test, never a run."""
    def refuse(name):
        return lambda *args, **kwargs: pytest.fail(f"{name}() was reached from a logic test: that is Docker")

    monkeypatch.setattr(demo, "preflight", refuse("preflight"))
    monkeypatch.setattr(demo, "build_images", refuse("build_images"))


def fake_api(errors_by_intent=None, plan_for=None, status=200, templates=TEMPLATES, run=None, calls=None):
    """GET /agent/templates and POST /agent/plan the way the STUB planner answers them (plan_for overrides the plan). `run`: a
    handler for the run-phase routes of a real run (it answers a request, or returns None to fall through to the rest); `calls`
    collects (method, path) of every request. Any other route is a bug in the test: a plan FAIL must stop before any run."""
    errors_by_intent = errors_by_intent or {}

    def handler(request):
        if calls is not None:
            calls.append((request.method, request.url.path))
        if run and (reply := run(request)) is not None:
            return reply
        if request.url.path == "/agent/templates":
            return httpx.Response(200, json=templates)
        if request.url.path == "/agent/plan":
            intent = json.loads(request.content)["intent"]
            t = next(t for t in templates if t["intent"] == intent)
            body = {"plan": (plan_for or {}).get(intent, t["plan"]), "rationale": "", "estimate": t["estimate"], "warnings": [],
                    "errors": errors_by_intent.get(intent, [])}
            return httpx.Response(status, json=body)
        raise AssertionError(f"unexpected {request.method} {request.url.path}: a plan FAIL must stop before any run")

    return httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler))


# --- which template is which intent ---------------------------------------------------------------------------------------

def test_each_canonical_intent_has_its_own_template_and_extra_templates_are_allowed():
    chosen = [I1, I2, I3]
    assert all(chosen) and len({t["slug"] for t in chosen}) == 3, "each canonical intent has its own template"
    assert {t["slug"] for t in chosen} <= {t["slug"] for t in TEMPLATES}  # canonical ⊆ shipped
    assert any(n["type"] == "tf-finetune" for n in I1["plan"]["nodes"])  # the slugs mean what agent_knowledge.md says
    assert any(n["type"] == "quantize" for n in I3["plan"]["nodes"])
    assert I2 is demo.find_intent2(TEMPLATES), "the template e2e_demo runs as intent #2 is canonical intent #2"
    for order in ([FOURTH, *TEMPLATES], [*TEMPLATES, FOURTH]):  # a fourth template that also fine-tunes steals nothing
        assert [agent.canonical(order, n) for n in "123"] == chosen
    assert agent.canonical([], "1") is None and agent.canonical([I1, I2], "3") is None


def test_the_default_run_covers_the_three_canonical_intents_and_no_other_template(capsys):
    errors = {I1["intent"]: ["research: boom"], I2["intent"]: ["synth: boom"], I3["intent"]: ["gsm8k: boom"]}  # none reaches a run
    api = fake_api(errors, templates=[*TEMPLATES, FOURTH])  # a fourth intent would reach preflight(), which fails the test
    assert agent.run_all(api, None) == 1
    out = capsys.readouterr().out
    assert out.count("--- intent #") == 3 and "nebius" not in out.lower()


# --- the shape of each canonical plan (docs/agent_knowledge.md "Expected plans") -----------------------------------------------

def test_every_canonical_plan_has_the_shape_the_knowledge_file_gives_it():
    for number in "123":
        slug, rule, what = agent.INTENTS[number]
        types = agent.node_types(agent.canonical(TEMPLATES, number)["plan"])
        assert rule(types), (slug, what, types)
    assert agent.node_types(I3["plan"]).index("quantize") < agent.node_types(I3["plan"]).index("judge-eval")


def broken_plans():
    """Each canonical plan with its step dropped or misplaced."""
    no_judge = copy.deepcopy(I1["plan"])
    no_judge["nodes"] = [n for n in no_judge["nodes"] if n["type"] != "judge-eval"]
    trains = copy.deepcopy(I2["plan"])
    trains["nodes"].append({"id": "ft", "type": "tf-finetune", "needs": ["prep"], "inputs": {}})
    judge_first = copy.deepcopy(I3["plan"])  # the judge needs nothing and is listed first, so it runs before quantize
    judge = next(n for n in judge_first["nodes"] if n["type"] == "judge-eval")
    judge["needs"] = []
    judge_first["nodes"].remove(judge)
    judge_first["nodes"].insert(0, judge)
    return {"1": no_judge, "2": trains, "3": judge_first}


@pytest.mark.parametrize("number", ["1", "2", "3"])
def test_a_template_edit_that_drops_or_misplaces_a_step_fails_the_e2e(number, capsys):
    template = agent.canonical(TEMPLATES, number)
    templates = [{**t, "plan": broken_plans()[number]} if t is template else t for t in TEMPLATES]
    assert not agent.INTENTS[number][1](agent.node_types(broken_plans()[number]))
    assert agent.run_all(fake_api(templates=templates), number) == 1
    out = capsys.readouterr().out
    assert f"e2e FAIL intent #{number}" in out and agent.INTENTS[number][2] in out


def test_node_types_follow_needs_not_the_listing_order():
    plan = {"nodes": [{"id": "b", "type": "judge-eval", "needs": ["a"]}, {"id": "a", "type": "quantize", "needs": []}]}
    assert agent.node_types(plan) == ["quantize", "judge-eval"]
    assert agent.node_types({"nodes": [{"id": "x", "type": "t", "needs": ["y"]}, {"id": "y", "type": "t", "needs": ["x"]}]}) == []


# --- a missing piece fails ----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("number, template, errors", [
    ("1", I1, ERRORS_1),  # vllm-serve was a named gap until ml-w4 merged
    ("3", I3, ["evaluate: unknown node type 'judge-eval'"]),
])
def test_a_missing_piece_fails_the_e2e_and_names_it(number, template, errors, capsys):
    assert agent.run_all(fake_api({template["intent"]: errors}), number) == 1
    out = capsys.readouterr().out
    assert f"e2e FAIL intent #{number}" in out and all(e in out for e in errors) and "SKIP" not in out


def test_a_planner_that_answers_with_another_plan_fails(capsys):
    api = fake_api(plan_for={I3["intent"]: I1["plan"]})
    assert agent.run_all(api, "3") == 1
    out = capsys.readouterr().out
    assert "e2e FAIL intent #3" in out and "canonical plan" in out


def test_an_estimate_over_the_run_cap_fails(capsys):
    over = {**I2, "estimate": {**I2["estimate"], "usd": 3.5}}
    handler = lambda r: httpx.Response(  # noqa: E731
        200, json=[over] if r.url.path == "/agent/templates" else {"plan": over["plan"], "estimate": over["estimate"], "errors": []})
    api = httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler))
    assert agent.run_all(api, "2") == 1
    assert "over the $3 run cap" in capsys.readouterr().out


def test_an_api_error_fails_that_intent_not_the_script(capsys):
    assert agent.run_all(fake_api(status=500), "1") == 1
    assert "POST /agent/plan -> HTTP 500" in capsys.readouterr().out


def test_a_missing_canonical_template_fails(capsys):
    api = httpx.Client(base_url="http://api", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[I2])))
    assert agent.run_all(api, "3") == 1
    assert "none is canonical intent #3" in capsys.readouterr().out


# --- the real run is refused before anything starts ---------------------------------------------------------------------------

REFUSED = "refusing to run without --max-cost"
KEY = "nb-key-9f3c1d-never-print-me"  # a stand-in value: no test may print it, log it or read a real key
REAL = ["--intent", "2", "--max-cost", "0.5"]


@pytest.fixture
def stack_spy(monkeypatch):
    """The stack a real run would start: recorded, never started."""
    started = []
    monkeypatch.setattr(demo, "with_stack", lambda fn, extra=None: started.append((fn, extra)) or 0)
    return started


@pytest.fixture(autouse=True)
def shell(monkeypatch):
    """The shell is not the developer's: no key, base URL or bind host unless a test sets one."""
    for name in ("NEBIUS_API_KEY", "TAVILY_API_KEY", "HF_TOKEN", "VASTAI_API_KEY", "NEBIUS_BASE_URL", "STUB", "E2E_BIND_HOST"):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("argv, key, message", [
    ([], KEY, REFUSED),
    (["--intent", "2"], KEY, REFUSED),
    (["--intent", "2", "--max-cost", "0"], KEY, REFUSED),
    (["--intent", "2", "--max-cost", "-1"], KEY, REFUSED),
    (["--intent", "2", "--max-cost", "nan"], KEY, REFUSED),  # nan is neither <= 0 nor > 3
    (["--intent", "2", "--max-cost", "3.01"], KEY, "caps a run at $3"),
    (["--intent", "2", "--max-cost", "inf"], KEY, "caps a run at $3"),
    (["--max-cost", "0.5"], KEY, "without --intent"),
    (["--intent", "  ", "--max-cost", "0.5"], KEY, "without --intent"),  # `make agent-e2e` with INTENT unset passes ""
    (REAL, None, "NEBIUS_API_KEY is unset"),
    (REAL, "   ", "NEBIUS_API_KEY is unset"),
])
def test_a_real_run_is_refused_before_anything_starts(argv, key, message, stack_spy, monkeypatch, capsys):
    if key is not None:
        monkeypatch.setenv("NEBIUS_API_KEY", key)
    with pytest.raises(SystemExit) as e:
        agent.main(argv)
    err = capsys.readouterr().err
    assert e.value.code == 2 and message in err and stack_spy == [], err
    assert (message == REFUSED) == (REFUSED in err) and KEY not in err, err


def test_the_cap_may_be_the_project_cap_itself(stack_spy, monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", KEY)
    assert agent.main(["--intent", "2", "--max-cost", "3"]) == 0
    assert len(stack_spy) == 1  # $3 is the run cap, not over it


def test_a_real_run_starts_a_stack_with_the_cap_pinned(stack_spy, monkeypatch):
    for name, value in {"NEBIUS_API_KEY": KEY, "TAVILY_API_KEY": "", "HF_TOKEN": "hf-1", "VASTAI_API_KEY": "vast-1"}.items():
        monkeypatch.setenv(name, value)
    assert agent.main(REAL) == 0
    [(_, extra)] = stack_spy
    assert extra == {  # the keys that are set, STUB gone, the shell's base URL gone, both caps = --max-cost, full scale
        "NEBIUS_API_KEY": KEY, "HF_TOKEN": "hf-1", "STUB": None, "NEBIUS_BASE_URL": None,
        "ORCHAPOD_MAX_RUN_USD": "0.5", "ORCHAPOD_MAX_DAY_USD": "0.5", "ORCHAPOD_ANON_SCALE": "1"}


def test_a_real_api_sees_three_keys_and_nothing_else_paid(tmp_path, monkeypatch):
    """The env the API process gets (api_env over the shell): the three forwarded keys when set; STUB, the shell's base URL and
    every other name in e2e_demo.PAID stay out."""
    shell_env = {name: f"leak-{name}" for name in demo.PAID} | {"PATH": "/usr/bin", "STUB": "1", "NEBIUS_BASE_URL": "https://x.example/v1"}
    for name, value in shell_env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("TAVILY_API_KEY", " ")  # blank counts as unset
    assert set(agent.FORWARD) <= set(demo.PAID)  # else the shell's copies would reach the API, blank or not
    env = demo.api_env(8123, tmp_path / "e2e.db", shell_env, agent.real_env(0.5))
    assert {n for n in demo.PAID if n in env} == {"NEBIUS_API_KEY", "HF_TOKEN"}
    assert env["NEBIUS_API_KEY"] == "leak-NEBIUS_API_KEY" and "STUB" not in env and "NEBIUS_BASE_URL" not in env
    assert (env["ORCHAPOD_MAX_RUN_USD"], env["ORCHAPOD_MAX_DAY_USD"], env["ORCHAPOD_ANON_SCALE"]) == ("0.5", "0.5", "1")
    assert env["ORCHAPOD_KILL_SWITCH"] == "0" and env["DATABASE_URL"].startswith("sqlite+aiosqlite:///" + str(tmp_path))


@pytest.mark.parametrize("argv", [["--stub"], ["--stub", "--intent", "2", "--max-cost", "0.5"]])
def test_a_stub_run_forwards_no_key_whatever_the_shell_holds(argv, stack_spy, monkeypatch):
    """`make check E2E=1` runs `e2e_agent.py --stub` from the Orchestrator's shell, which holds the keys: a stub stays a stub, with the
    stub's caps and no key (and `--max-cost` beside `--stub` does not make it a real run)."""
    for name, value in {"NEBIUS_API_KEY": KEY, "TAVILY_API_KEY": "tv-1", "HF_TOKEN": "hf-1", "NEBIUS_BASE_URL": "https://x.example/v1"}.items():
        monkeypatch.setenv(name, value)
    assert agent.main(argv) == 0
    [(_, extra)] = stack_spy
    assert extra == agent.FULL_CAPS


def test_a_stub_run_is_held_to_the_stub_limit_not_a_real_runs(stack_spy, stack_ok, monkeypatch, capsys):
    """The run `main --stub` starts, given an API that never reports its report, is cancelled at demo.LIMIT_S (the clock is
    poll_run's t0, then the time after each poll)."""
    monkeypatch.setenv("NEBIUS_API_KEY", KEY)
    assert agent.main(["--stub", "--intent", "2", "--max-cost", "0.5"]) == 0
    [(fn, _)] = stack_spy
    limit = demo.LIMIT_S
    clock = iter([0, 100, limit - 1, limit])
    monkeypatch.setattr(demo, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda s: None))
    run = live(good_report(intent=I2["intent"]), not_ready=99)
    assert fn(fake_api(run=run)) == 1
    assert len(run.polls) == 3 and run.cancels == ["tok-real"]
    assert f"the run did not end within {limit} s, so it was cancelled" in capsys.readouterr().out


@pytest.mark.skipif(not shutil.which("make"), reason="make is not installed")
@pytest.mark.parametrize("args, tail", [
    (["INTENT=2", "MAX_COST=0.5"], 'scripts/e2e_agent.py --intent "2" --max-cost "0.5"'),
    (["INTENT=Quantize a model"], 'scripts/e2e_agent.py --intent "Quantize a model" --max-cost "3"'),  # the cap defaults to the project's
])
def test_make_agent_e2e_passes_the_intent_and_the_cap(args, tail):
    dry_run = subprocess.run(["make", "-n", "agent-e2e", *args], cwd=demo.ROOT, capture_output=True, text=True, check=True).stdout
    assert dry_run.strip().endswith(tail), dry_run


# --- a real plan that must not run is refused before /agent/run --------------------------------------------------------------

def plan_with(*nodes):
    """The intent #2 plan with more nodes after it."""
    return {**I2["plan"], "nodes": [*I2["plan"]["nodes"], *nodes]}


SERVE = {"id": "serve", "type": "vllm-serve", "needs": ["prep"], "inputs": {}}  # rents_gpu: an endpoint billed by the hour
TRAIN = {"id": "train", "type": "unsloth-train", "needs": ["prep"], "inputs": {}}  # runtime gpu: a Serverless Job
RESEARCH = {"id": "research", "type": "web-research", "needs": [], "inputs": {"seed_urls": ["https://docs.nebius.com"]}}


@pytest.mark.parametrize("nodes, errors, max_cost, tavily, line", [
    ([], ["synth: unknown input 'bogus'"], 0.5, "tv", "synth: unknown input 'bogus'"),
    ([], [], 0.1, "tv", "the estimate $0.15 is over --max-cost $0.1"),  # I2's estimate is $0.15
    ([SERVE], [], 0.5, "tv", "vllm-serve 'serve' rents a GPU"),
    ([TRAIN], [], 0.5, "tv", "unsloth-train 'train' rents a GPU"),
    ([RESEARCH], [], 0.5, "", "web-research 'research' needs TAVILY_API_KEY, which is unset"),
])
def test_a_real_plan_that_must_not_run_is_refused_in_one_line_before_the_run(nodes, errors, max_cost, tavily, line, monkeypatch, capsys):
    monkeypatch.setenv("TAVILY_API_KEY", tavily)
    calls = []
    api = fake_api({I2["intent"]: errors}, plan_for={I2["intent"]: plan_with(*nodes)}, calls=calls)
    assert agent.run_all(api, "2", max_cost) == 1  # the no_docker fixture fails the test if it got as far as Docker
    out = capsys.readouterr().out
    assert "e2e FAIL intent #2" in out and f"  - {line}" in out and out.count("\n  - ") == 1, out
    assert ("POST", "/agent/run") not in calls


def test_refusals_name_each_node_that_rents_a_gpu_or_lacks_its_key():
    plan = plan_with(SERVE, TRAIN, RESEARCH)
    assert agent.refusals(plan, {"TAVILY_API_KEY": "tv"}) == [
        "vllm-serve 'serve' rents a GPU: only the golden run (scripts/e2e_demo.py --max-cost) starts one, and it needs G2 quota",
        "unsloth-train 'train' rents a GPU: only the golden run (scripts/e2e_demo.py --max-cost) starts one, and it needs G2 quota"]
    assert agent.refusals(plan_with(RESEARCH), {"TAVILY_API_KEY": "tv"}) == []
    assert agent.refusals(plan_with(RESEARCH), {"TAVILY_API_KEY": " "}) == ["web-research 'research' needs TAVILY_API_KEY, which is unset"]
    assert agent.refusals(I2["plan"], {}) == []


# --- the report and the outputs -----------------------------------------------------------------------------------------------

def good_report(plan_name="movie-engagement-synthetic-data", intent="Generate synthetic data"):
    return {**good_summary(), "intent": intent, "estimate": {"usd": 0.15}, "ready": True,
            "markdown": f"## {plan_name}: succeeded\n\n**Cost:** $0.0000 of $0.15 estimated."}


def test_a_good_report_passes():
    assert agent.check_report(good_report(), "Generate synthetic data", I2["plan"]) == []


LONG_NAME = "Synthetic movie engagement events\nfor a streaming service:   likes, shares and subscribes over the last thirty days"  # 115 chars
LONG_TITLE = "Synthetic movie engagement events for a streaming service: likes, shares and sub"  # how the report writes it: 80 chars


def test_check_report_looks_for_the_plan_name_as_the_report_titles_it():
    """backend-w7: the title is `## <name>: <status>` with the name's whitespace runs (newlines too) collapsed to one space and the
    name cut at 80 characters, so a live planner's long or multi-line name never appears in the report as the plan has it."""
    plan, ask = {**I2["plan"], "name": LONG_NAME}, I2["intent"]
    assert len(LONG_TITLE) == 80 and LONG_NAME not in LONG_TITLE
    assert agent.check_report(good_report(LONG_TITLE, ask), ask, plan) == []
    problems = agent.check_report(good_report("another-plan", ask), ask, plan)
    assert [p for p in problems if "never names the plan" in p] == [f"the report never names the plan {LONG_TITLE!r}"]
    assert any("never names the plan" in p for p in agent.check_report(good_report(LONG_TITLE[:79], ask), ask, plan))  # not the 80 written


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


def test_a_run_that_outlives_the_limit_is_cancelled_with_the_token_agent_run_returned(monkeypatch):
    """An anonymous cancel without the run's token is a 403 (contracts "Run control API"), and /agent/run returns it once."""
    monkeypatch.setattr(demo, "LIMIT_S", 0)
    monkeypatch.setattr(demo, "preflight", lambda: [])  # past the Docker guard of this file: the plan is good, the run never ends
    monkeypatch.setattr(demo, "build_images", lambda types: None)
    posts = []

    def handler(request):
        path = request.url.path
        if path == "/agent/plan":
            return httpx.Response(200, json={"plan": I2["plan"], "rationale": "", "estimate": I2["estimate"], "warnings": [], "errors": []})
        if path == "/agent/run":
            return httpx.Response(201, json={"run_id": "r1", "workflow_id": "w1", "estimate": I2["estimate"], "cancel_token": "tok-agent"})
        if request.method == "GET":
            return httpx.Response(200, json=good_report() | {"status": "running", "ready": False, "markdown": None})
        posts.append((path, request.headers.get("x-orchapod-cancel-token")))
        return httpx.Response(200, json={"id": "r1"})

    api = httpx.Client(base_url="http://api", transport=httpx.MockTransport(handler))
    assert agent.run_one(api, "intent #2", I2["intent"], I2, "2") == "FAIL"  # it did not end within the limit
    assert posts == [("/runs/r1/cancel", "tok-agent")]


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
    ({"samples": None}, "samples"),
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


# --- a real run, to its verdict ----------------------------------------------------------------------------------------------

MARKDOWN = "\n".join(["## movie-engagement-synthetic-data: succeeded", "", "**Intent:** Generate synthetic data of movie likes, shares "
                      "and subscribes", "", "**Cost:** $0.0823 of $0.15 estimated.", "| Node | Type | Status | $ |",
                      "| synth | synth-distilabel | succeeded | 0.0823 |"])  # 7 lines: the run prints 5
DATASET = "/artifacts/prep-dataset/download"  # where good_summary() links the data-prep dataset
ROWS_500 = "\n".join([json.dumps(ROW)] * 500) + "\n"  # intent #2 asks for n_samples = 500


def rows(n: int) -> str:
    return "\n".join([json.dumps(ROW)] * n) + "\n"


def real_report(**changes):
    """A succeeded real run of the intent #2 plan: the synth node cost $0.0823, the report is ready."""
    report = good_report(intent=I2["intent"]) | {"cost_usd": 0.0823, "markdown": MARKDOWN}
    report["nodes"] = [{**n, "usd": 0.0823 if n["node_id"] == "synth" else 0.0} for n in report["nodes"]]
    return report | changes


def live(report, dataset=ROWS_500, not_ready=0, planner_waits=0):
    """The run-phase routes of a real run, for fake_api(run=...): /agent/run, the report (ready only after `not_ready` polls
    that answer a finished run whose report is still being written), the dataset download. A planner that may take
    `planner_waits` seconds raises ReadTimeout for a client that gives up sooner."""
    polls, cancels = [], []

    def handler(request):
        path = request.url.path
        if path == "/agent/plan" and request.extensions["timeout"]["read"] < planner_waits:
            raise httpx.ReadTimeout("the planner is a model call and may take longer than this client waits")
        if path == "/agent/run":
            return httpx.Response(201, json={"run_id": "r1", "workflow_id": "w1", "estimate": I2["estimate"], "cancel_token": "tok-real"})
        if path == "/agent/runs/r1/report":
            polls.append(request)
            return httpx.Response(200, json=report if len(polls) > not_ready else report | {"ready": False, "markdown": None})
        if path == "/runs/r1/cancel":
            cancels.append(request.headers.get("x-orchapod-cancel-token"))
            return httpx.Response(200, json={"id": "r1"})
        if path == DATASET:
            return httpx.Response(200, text=dataset)

    handler.polls, handler.cancels = polls, cancels
    return handler


@pytest.fixture
def stack_ok(monkeypatch):
    """Docker and the images are fine (no_docker says otherwise), and polling does not sleep."""
    monkeypatch.setattr(demo, "preflight", lambda: [])
    monkeypatch.setattr(demo, "build_images", lambda types: None)
    monkeypatch.setattr(demo.time, "sleep", lambda s: None)


def test_a_real_run_that_delivers_within_its_cap_passes_and_shows_five_lines_of_its_report(stack_ok, capsys):
    calls = []
    api = fake_api(run=live(real_report(), not_ready=2), calls=calls)
    assert agent.run_all(api, "2", 0.5) == 0
    out = capsys.readouterr().out
    assert f"PASS intent #2: run r1 succeeded in 0 s (limit {agent.REAL_LIMIT_S} s), cost $0.0823, estimate $0.15, " \
           f"report ready ({len(MARKDOWN)} chars)" in out
    lines = MARKDOWN.splitlines()
    assert "\n".join(lines[:5]) in out and lines[5] not in out
    assert [path for _, path in calls].count("/agent/runs/r1/report") == 3  # polled past the two "ready: false" answers
    assert ("POST", "/runs/r1/cancel") not in calls


def test_a_real_run_waits_for_a_slow_planner(stack_ok):
    """The live planner is a model call (300 s a call, with repairs): a client that gives up at the stack's 30 s fails a run
    that the API goes on to bill."""
    api = fake_api(run=live(real_report(), planner_waits=300))
    assert agent.run_all(api, "2", 0.5) == 0


FAILED_RUN = real_report(status="failed", error="exit 1: boom", cost_usd=0.0123,
                         nodes=[{"node_id": "synth", "type": "synth-distilabel", "status": "failed", "usd": 0.0123, "error": "exit 1: boom"}])


def test_a_real_run_that_never_becomes_ready_is_cancelled_at_the_real_limit(stack_ok, monkeypatch, capsys):
    """Polled past the stub's 300 s, cancelled with the token /agent/run returned once REAL_LIMIT_S has passed. The clock is
    poll_run's t0, then the time after each poll."""
    limit = agent.REAL_LIMIT_S
    clock = iter([0, 100, limit - 1, limit])
    monkeypatch.setattr(demo, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda s: None))
    run = live(real_report(), not_ready=99)
    assert agent.run_all(fake_api(run=run), "2", 0.5) == 1
    assert len(run.polls) == 3 and run.cancels == ["tok-real"]
    assert f"the run did not end within {limit} s, so it was cancelled" in capsys.readouterr().out


@pytest.mark.parametrize("report, dataset, text", [
    pytest.param(real_report(cost_usd=0.0), ROWS_500, "a real run that cost $0 called nothing", id="cost-zero"),
    pytest.param(real_report(cost_usd=0.51), ROWS_500, "$0.51 is over --max-cost $0.5", id="cost-over-cap"),
    pytest.param(real_report(), rows(449), "449 rows, under 90 % of the 500 asked", id="449-of-500-rows"),
    pytest.param(real_report(), "\n".join([json.dumps(ROW | {"mood": "x"})] * 500), "mood", id="row-with-an-extra-field"),
    pytest.param(FAILED_RUN, ROWS_500, "exit 1: boom", id="failed-run"),
])
def test_a_real_run_that_spent_nothing_too_much_or_delivered_too_little_fails(report, dataset, text, stack_ok, capsys):
    assert agent.run_all(fake_api(run=live(report, dataset)), "2", 0.5) == 1
    out = capsys.readouterr().out
    assert "e2e FAIL intent #2 (run r1 after 0 s, cost $" in out and ", estimate $0.15)" in out and text in out, out
    assert "e2e: PASS" not in out and MARKDOWN.splitlines()[0] in out  # the report's head is shown on a FAIL too


def test_a_real_run_that_delivers_exactly_90_percent_of_its_rows_and_spends_exactly_its_cap_passes(stack_ok):
    assert agent.run_all(fake_api(run=live(real_report(cost_usd=0.5), rows(450))), "2", 0.5) == 0


def test_a_plan_that_leaves_n_samples_out_asked_for_the_nodes_default_1000(stack_ok, capsys):
    plan = copy.deepcopy(I2["plan"])
    del plan["nodes"][0]["inputs"]["n_samples"]
    assert agent.run_all(fake_api(plan_for={I2["intent"]: plan}, run=live(real_report(), ROWS_500)), "2", 0.5) == 1
    assert "500 rows, under 90 % of the 1000 asked" in capsys.readouterr().out


def test_a_stub_run_still_ends_in_its_pass_line_and_shows_no_report_head(stack_ok, capsys):
    api = fake_api(run=live(good_report(intent=I2["intent"]), ROWS_500))
    assert agent.run_all(api, "2") == 0
    out = capsys.readouterr().out
    assert f"e2e: PASS intent #2: run r1 succeeded in 0 s (limit {demo.LIMIT_S} s), cost $0, estimate $0.15, " \
           f"report ready ({len(good_report()['markdown'])} chars)\n" in out
    assert "first 5 lines" not in out


def test_a_real_plan_for_a_canonical_intent_keeps_the_shape_the_knowledge_file_gives_it(stack_ok, capsys):
    api = fake_api(plan_for={I2["intent"]: broken_plans()["2"]}, run=live(real_report()))  # intent #2 that also trains
    assert agent.run_all(api, "2", 0.5) == 1
    assert agent.INTENTS["2"][2] in capsys.readouterr().out


def test_a_free_text_intent_runs_for_real_with_no_canonical_shape(stack_ok, capsys):
    text = "Make me some movie event data"
    api = fake_api(templates=[*TEMPLATES, {**I2, "slug": "free", "intent": text}], run=live(real_report(intent=text)))
    assert agent.run_all(api, text, 0.5) == 0
    assert f"e2e: PASS free-text intent: run r1 succeeded in 0 s (limit {agent.REAL_LIMIT_S} s), cost $0.0823" in capsys.readouterr().out


def test_a_real_report_is_judged_on_its_cost_not_on_the_stub_zero():
    ask, plan = I2["intent"], I2["plan"]
    assert agent.check_report(real_report(), ask, plan, 0.5) == []
    assert any("cost_usd" in p for p in agent.check_report(real_report(), ask, plan))  # judged as a STUB run, $0.0823 is wrong
    assert any("called nothing" in p for p in agent.check_report(real_report(cost_usd=0.0), ask, plan, 0.5))
    assert agent.check_report(real_report(cost_usd=0.5), ask, plan, 0.5) == []  # the cap itself is within the cap


def test_judge_eval_of_a_real_run_says_stub_false():
    assert agent.check_eval_summary(eval_summary(stub=False), False, stub=False) == []
    assert any("stub is True in a real run" in p for p in agent.check_eval_summary(eval_summary(stub=True), False, stub=False))
    assert any("stub is False in a STUB run" in p for p in agent.check_eval_summary(eval_summary(stub=False), False))


# --- no secret is printed or logged -------------------------------------------------------------------------------------------

SECRETS = {"NEBIUS_API_KEY": "nb-7Qf2-fake-key", "TAVILY_API_KEY": "tv-9Zk4-fake-key", "HF_TOKEN": "hf-3Lm8-fake-token",
           "VASTAI_API_KEY": "va-1Xc6-fake-key", "NEBIUS_IAM_TOKEN": "iam-5Rt0-fake-token"}


@pytest.mark.parametrize("planner_status, exit_code", [(200, 0), (500, 1)])
def test_a_real_run_never_prints_or_logs_a_key(planner_status, exit_code, stack_ok, monkeypatch, capsys):
    """main() -> with_stack -> start_api -> api_env are the real ones; only the uvicorn process and the HTTP transport are fake.
    The API's log holds every request it got (as an access log would), and on a FAIL the stack prints its tail."""
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    spawned, api_logs = [], []

    class Spawned(FakeApi):
        """What start_api asks subprocess.Popen to start: it keeps the argv and env, and logs a startup line like uvicorn."""

        def __init__(self, argv, **kw):
            super().__init__()
            self.argv, self.kw = argv, kw
            kw["stdout"].write("INFO:     Started server process\n")
            spawned.append(self)

    def log_request(request):  # the API's access log, with the request's headers and body
        with open(spawned[0].kw["stdout"].name, "a") as f:
            f.write(f"{request.method} {request.url} {dict(request.headers)} {request.content!r}\n")

    run = live(real_report())

    def logged(request):
        log_request(request)
        return run(request)

    api = fake_api(status=planner_status, run=logged)
    monkeypatch.setattr(demo.subprocess, "Popen", Spawned)
    monkeypatch.setattr(demo, "wait_healthy", lambda *a: None)
    monkeypatch.setattr(demo, "stop", lambda proc: api_logs.append(Path(proc.kw["stdout"].name).read_text()))
    monkeypatch.setattr(httpx, "Client", lambda **kw: api)

    assert agent.main(REAL) == exit_code
    out = capsys.readouterr()
    everything = out.out + out.err + api_logs[0]
    assert [v for v in SECRETS.values() if v in everything] == []
    # the keys did reach the API (through its env, never its command line), so the check above has something to catch
    env = spawned[0].kw["env"]
    assert (env["NEBIUS_API_KEY"], env["TAVILY_API_KEY"], env["HF_TOKEN"]) == tuple(SECRETS[k] for k in ("NEBIUS_API_KEY", "TAVILY_API_KEY", "HF_TOKEN"))
    assert "VASTAI_API_KEY" not in env and "NEBIUS_IAM_TOKEN" not in env and "STUB" not in env
    assert not any(v in " ".join(spawned[0].argv) for v in SECRETS.values())
    assert "POST http://api/agent/plan" in api_logs[0]  # the log has the requests: a key sent in one would be in it
    assert ("e2e: PASS" in out.out) == (exit_code == 0) and "STUB=1" not in out.out
