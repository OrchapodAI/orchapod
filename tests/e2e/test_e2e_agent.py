"""scripts/e2e_agent.py: the logic around the stub e2e of the canonical intents and the golden path (the run is `make check E2E=1`: Docker, `make up`),
and the real run of one intent (`make agent-e2e INTENT=2 MAX_COST=0.5`, the Orchestrator's), proved here on a fake API."""

import copy
import json
import shutil
import sqlite3
import subprocess
import uuid
from decimal import Decimal
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
I1, I2, I3, I4 = (agent.canonical(TEMPLATES, n) for n in "1234")  # I4: the golden path
# a later template (the shipped fifth is the golden path's CPU variant): it must neither steal an intent nor be run by default
LATER = {**I1, "slug": "a-later-template", "title": "A later template", "intent": "Do what a later template does"}

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

def test_each_canonical_intent_and_the_golden_path_has_its_own_template_and_extra_templates_are_allowed():
    chosen = [I1, I2, I3, I4]
    assert all(chosen) and len({t["slug"] for t in chosen}) == 4, "each canonical intent and the golden path has its own template"
    assert {t["slug"] for t in chosen} <= {t["slug"] for t in TEMPLATES}  # canonical ⊆ shipped
    assert any(n["type"] == "tf-finetune" for n in I1["plan"]["nodes"])  # the slugs mean what agent_knowledge.md says
    assert any(n["type"] == "quantize" for n in I3["plan"]["nodes"])
    assert any(n["type"] == "unsloth-train" for n in I4["plan"]["nodes"]) and not any(n["type"] == "quantize" for n in I4["plan"]["nodes"])
    assert I2 is demo.find_intent2(TEMPLATES), "the template e2e_demo runs as intent #2 is canonical intent #2"
    for order in ([LATER, *TEMPLATES], [*TEMPLATES, LATER]):  # a later template steals nothing
        assert [agent.canonical(order, n) for n in "1234"] == chosen
    assert agent.canonical([], "1") is None and agent.canonical([I1, I2], "3") is None


def test_the_default_run_covers_the_three_canonical_intents_and_the_golden_path_and_no_other_template(monkeypatch, capsys):
    errors = {I1["intent"]: ["research: boom"], I2["intent"]: ["synth: boom"], I3["intent"]: ["gsm8k: boom"]}  # none reaches a run
    monkeypatch.setattr(demo, "preflight", lambda: ["the stack is down"])  # the golden path has no planner to fail: it stops here
    assert agent.run_all(fake_api(errors, templates=[*TEMPLATES, LATER]), None) == 1
    out = capsys.readouterr().out
    assert out.count("e2e: --- ") == 4 and out.count("e2e: --- intent #") == 3 and out.count("e2e: --- golden path: ") == 1
    assert "later template" not in out.lower() and "on cpu" not in out.lower()  # neither LATER nor the shipped CPU variant is run


def test_the_default_stub_run_ends_in_4_pass(monkeypatch, capsys):
    ran = []

    def pass_all(c, label, intent, template, number=None, max_cost=None):
        ran.append((label, number, template["slug"], max_cost))
        return "PASS"

    monkeypatch.setattr(agent, "run_one", pass_all)
    assert agent.run_all(fake_api(), None) == 0
    assert ran == [("intent #1", "1", "real-estate-compliance", None), ("intent #2", "2", "movie-engagement", None),
                   ("intent #3", "3", "maths-quantize", None), ("golden path", "4", "nebius-docs-specialist", None)]
    assert "e2e: 4 PASS, 0 FAIL: intent #1 PASS, intent #2 PASS, intent #3 PASS, golden path PASS" in capsys.readouterr().out


# --- the shape of each canonical plan (docs/agent_knowledge.md "Expected plans") -----------------------------------------------

def test_every_canonical_plan_has_the_shape_the_knowledge_file_gives_it():
    for number in "1234":
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
    no_serve = copy.deepcopy(I4["plan"])  # the golden path that no longer serves what it judges (its other nodes still run in order)
    no_serve["nodes"] = [n for n in no_serve["nodes"] if n["type"] != "vllm-serve"]
    next(n for n in no_serve["nodes"] if n["type"] == "judge-eval")["needs"] = ["prep", "train"]
    return {"1": no_judge, "2": trains, "3": judge_first, "4": no_serve}


@pytest.mark.parametrize("number, label", [("1", "intent #1"), ("2", "intent #2"), ("3", "intent #3"), ("4", "golden path")])
def test_a_template_edit_that_drops_or_misplaces_a_step_fails_the_e2e(number, label, capsys):
    template = agent.canonical(TEMPLATES, number)
    templates = [{**t, "plan": broken_plans()[number]} if t is template else t for t in TEMPLATES]
    assert not agent.INTENTS[number][1](agent.node_types(broken_plans()[number]))
    assert agent.run_all(fake_api(templates=templates), number) == 1  # the no_docker fixture fails the test if it got as far as Docker
    out = capsys.readouterr().out
    assert f"e2e FAIL {label}" in out and agent.INTENTS[number][2] in out


def test_a_golden_path_that_serves_before_it_trains_fails_the_e2e(capsys):
    plan = copy.deepcopy(I4["plan"])
    serve, train = (next(n for n in plan["nodes"] if n["type"] == t) for t in ("vllm-serve", "unsloth-train"))
    serve["needs"], train["needs"] = ["prep"], ["serve"]  # the adapter would be served before it exists
    assert agent.node_types(plan) == ["web-research", "synth-distilabel", "data-prep", "vllm-serve", "unsloth-train", "judge-eval"]
    templates = [{**t, "plan": plan} if t is I4 else t for t in TEMPLATES]
    assert agent.run_all(fake_api(templates=templates), "4") == 1
    assert "e2e FAIL golden path" in capsys.readouterr().out


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


@pytest.mark.parametrize("number, what", [("3", "canonical intent #3 (slug 'maths-quantize')"), ("4", "the golden path (slug 'nebius-docs-specialist')")])
def test_a_missing_canonical_template_fails(number, what, capsys):
    api = httpx.Client(base_url="http://api", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[I2])))
    assert agent.run_all(api, number) == 1
    assert f"none is {what}" in capsys.readouterr().out


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


@pytest.fixture(autouse=True)
def limit_untouched():
    """The real limit is a parameter of the run (poll_run's `limit`), not a global that the next run would inherit: no test, and
    so no run of main(), may leave e2e_demo.LIMIT_S changed. (Runs after monkeypatch has put back what a test set.)"""
    before = demo.LIMIT_S
    yield
    assert demo.LIMIT_S == before


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
    (["--intent", "4", "--max-cost", "0.5"], KEY, "the golden path is a stub run"),  # a real run would spend a planner call, then be refused
    (["--intent", " 4 ", "--max-cost", "0.5"], KEY, "the golden path is a stub run"),
])
def test_a_real_run_is_refused_before_anything_starts(argv, key, message, stack_spy, monkeypatch, capsys):
    if key is not None:
        monkeypatch.setenv("NEBIUS_API_KEY", key)
    with pytest.raises(SystemExit) as e:
        agent.main(argv)
    err = capsys.readouterr().err
    assert e.value.code == 2 and message in err and stack_spy == [], err
    assert (message == REFUSED) == (REFUSED in err) and KEY not in err, err


def test_the_golden_path_alone_is_a_stub_run(stack_spy):
    assert agent.main(["--stub", "--intent", "4"]) == 0 and len(stack_spy) == 1


def test_the_cap_may_be_the_project_cap_itself(stack_spy, monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", KEY)
    assert agent.main(["--intent", "2", "--max-cost", "3"]) == 0
    assert len(stack_spy) == 1  # $3 is the run cap, not over it


def test_a_real_run_starts_a_stack_with_the_cap_pinned(stack_spy, monkeypatch):
    for name, value in {"NEBIUS_API_KEY": KEY, "TAVILY_API_KEY": "", "HF_TOKEN": "hf-1", "VASTAI_API_KEY": "vast-1"}.items():
        monkeypatch.setenv(name, value)
    assert agent.main(REAL) == 0
    [(_, extra)] = stack_spy
    assert extra.pop("DATABASE_URL").endswith("/e2e.db")  # the throwaway DB whose ledger the run's last line reads
    assert extra == {  # the keys that are set, STUB gone, both caps = --max-cost, full scale
        "NEBIUS_API_KEY": KEY, "HF_TOKEN": "hf-1", "STUB": None,
        "ORCHAPOD_MAX_RUN_USD": "0.5", "ORCHAPOD_MAX_DAY_USD": "0.5", "ORCHAPOD_ANON_SCALE": "1"}


def test_a_real_api_sees_three_keys_and_nothing_else_paid(tmp_path, monkeypatch):
    """The env the API process gets (api_env over the shell): the three forwarded keys when set, and a non-secret setting such as
    NEBIUS_BASE_URL as the shell has it; STUB and every other name in e2e_demo.PAID stay out."""
    shell_env = {name: f"leak-{name}" for name in demo.PAID} | {"PATH": "/usr/bin", "STUB": "1", "NEBIUS_BASE_URL": "https://x.example/v1"}
    for name, value in shell_env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("TAVILY_API_KEY", " ")  # blank counts as unset
    assert set(agent.FORWARD) <= set(demo.PAID)  # else the shell's copies would reach the API, blank or not
    env = demo.api_env(8123, tmp_path / "e2e.db", shell_env, agent.real_env(0.5))
    assert {n for n in demo.PAID if n in env} == {"NEBIUS_API_KEY", "HF_TOKEN"}
    assert env["NEBIUS_API_KEY"] == "leak-NEBIUS_API_KEY" and "STUB" not in env and env["NEBIUS_BASE_URL"] == "https://x.example/v1"
    assert (env["ORCHAPOD_MAX_RUN_USD"], env["ORCHAPOD_MAX_DAY_USD"], env["ORCHAPOD_ANON_SCALE"]) == ("0.5", "0.5", "1")
    assert env["ORCHAPOD_KILL_SWITCH"] == "0" and env["DATABASE_URL"].startswith("sqlite+aiosqlite:///" + str(tmp_path))


@pytest.mark.parametrize("bind, refused", [("172.17.0.1", True), ("0.0.0.0", True), ("", False)])  # blank = unset = loopback
def test_a_real_run_is_refused_when_its_api_would_listen_beyond_loopback(bind, refused, stack_spy, monkeypatch, capsys):
    """The API of a real run holds a key, so it takes runs, and spends, from anyone who reaches it: it stays on 127.0.0.1."""
    monkeypatch.setenv("NEBIUS_API_KEY", KEY)
    monkeypatch.setenv("E2E_BIND_HOST", bind)
    if not refused:
        assert agent.main(REAL) == 0 and len(stack_spy) == 1
        return
    with pytest.raises(SystemExit) as e:
        agent.main(REAL)
    err = capsys.readouterr().err
    assert e.value.code == 2 and "E2E_BIND_HOST" in err and stack_spy == [] and KEY not in err, err


def test_a_stub_run_may_listen_on_the_docker_bridge(stack_spy, monkeypatch):
    """Linux: the node containers reach a stub API through docker0; a stub API holds no key."""
    monkeypatch.setenv("E2E_BIND_HOST", "172.17.0.1")
    assert agent.main(["--stub"]) == 0 and len(stack_spy) == 1


TOKEN_FACTORY = "https://api.tokenfactory.nebius.com/v1"


@pytest.mark.parametrize("base", [
    "https://api.example.com/v1",
    "http://api.tokenfactory.nebius.com/v1",  # not https
    "https://api.tokenfactory.nebius.com/v2",
    "https://api.tokenfactory.nebius.com.attacker.example/v1",
    "https://user:s3cret-pw@api.tokenfactory.nebius.com/v1",  # a URL can carry userinfo, so it is never echoed
])
def test_a_real_run_is_refused_when_the_key_would_go_to_another_base_url(base, stack_spy, monkeypatch, capsys):
    """NEBIUS_BASE_URL is where the providers send NEBIUS_API_KEY; the client's pairing rule cannot catch it, since base == NEBIUS_BASE_URL
    by construction. Exit 2 before the stack, and the value is not printed."""
    monkeypatch.setenv("NEBIUS_API_KEY", KEY)
    monkeypatch.setenv("NEBIUS_BASE_URL", base)
    with pytest.raises(SystemExit) as e:
        agent.main(REAL)
    seen = capsys.readouterr()
    assert e.value.code == 2 and "NEBIUS_BASE_URL" in seen.err and stack_spy == [], seen.err
    assert not [v for v in (base, "s3cret-pw", "attacker.example", KEY) if v in seen.err + seen.out]


@pytest.mark.parametrize("base", ["", "   ", TOKEN_FACTORY, TOKEN_FACTORY + "/", f"  {TOKEN_FACTORY}//  "])  # compared after strip and rstrip("/")
def test_a_real_run_may_have_a_blank_or_the_token_factory_base_url(base, stack_spy, monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", KEY)
    monkeypatch.setenv("NEBIUS_BASE_URL", base)
    assert agent.main(REAL) == 0 and len(stack_spy) == 1


def test_a_stub_run_does_not_care_about_the_base_url(stack_spy, monkeypatch):
    """A stub run forwards no key, so no base URL can receive one."""
    monkeypatch.setenv("NEBIUS_BASE_URL", "https://api.example.com/v1")
    assert agent.main(["--stub"]) == 0 and len(stack_spy) == 1


def test_the_hardcoded_token_factory_url_is_the_providers_default():
    """The script cannot import the providers (their SDK is not on a script's path), so it hardcodes the default; this pins it."""
    from packages.providers.tokenfactory import TF_BASE

    assert agent.TF_BASE == TF_BASE == TOKEN_FACTORY


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


def test_every_stub_target_is_a_node_a_real_run_refuses():
    """The stub stage has no torch, so a node built from it must never be one a real run could start: a real run refuses it first."""
    for node in demo.STUB_TARGETS:
        lines = agent.refusals({"nodes": [{"id": "n", "type": node}]}, {})
        assert any("rents a GPU" in line for line in lines), f"{node} is built from a stub-only stage but a real run would start it: {lines}"


def test_refusals_name_each_node_that_rents_a_gpu_or_lacks_its_key():
    plan = plan_with(SERVE, TRAIN, RESEARCH)
    assert agent.refusals(plan, {"TAVILY_API_KEY": "tv"}) == [
        "vllm-serve 'serve' rents a GPU: only the golden run (scripts/e2e_demo.py --max-cost) starts one, and it needs G2 quota",
        "unsloth-train 'train' rents a GPU: only the golden run (scripts/e2e_demo.py --max-cost) starts one, and it needs G2 quota"]
    assert agent.refusals(plan_with(RESEARCH), {"TAVILY_API_KEY": "tv"}) == []
    assert agent.refusals(plan_with(RESEARCH), {"TAVILY_API_KEY": " "}) == ["web-research 'research' needs TAVILY_API_KEY, which is unset"]
    assert agent.refusals(I2["plan"], {}) == []


def test_the_gpu_rule_agrees_with_the_budget_guard_over_every_node_type():
    """refusals() reads the registry itself (a script has no apps/ on its path); budget.gpu_nodes is what the API's guards use. A
    type that one counts and the other does not is a plan the API would refuse the public that this script would run."""
    from api.services import budget
    from packages.workflow_schema.models import NODE_REGISTRY

    refused = {t.value: any("rents a GPU" in line for line in agent.refusals({"nodes": [{"id": "n", "type": t.value}]}, {"TAVILY_API_KEY": "k"}))
               for t in NODE_REGISTRY}
    assert refused == {t.value: bool(budget.gpu_nodes([t.value])) for t in NODE_REGISTRY}
    assert {t for t, rents in refused.items() if rents} >= {"vllm-serve", "unsloth-train"} and not refused["data-prep"]  # not vacuous


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


def live(report, dataset=ROWS_500, not_ready=0, planner_waits=0, files=None):
    """The run-phase routes of a real run, for fake_api(run=...): /agent/run, the report (ready only after `not_ready` polls
    that answer a finished run whose report is still being written), the dataset download. A planner that may take
    `planner_waits` seconds raises ReadTimeout for a client that gives up sooner. `files` (path: text) are served as well; `posted`
    keeps the bodies of POST /agent/run."""
    polls, cancels, posted = [], [], []

    def handler(request):
        path = request.url.path
        if path == "/agent/plan" and request.extensions["timeout"]["read"] < planner_waits:
            raise httpx.ReadTimeout("the planner is a model call and may take longer than this client waits")
        if path == "/agent/run":
            posted.append(json.loads(request.content))
            return httpx.Response(201, json={"run_id": "r1", "workflow_id": "w1", "estimate": I2["estimate"], "cancel_token": "tok-real"})
        if path == "/agent/runs/r1/report":
            polls.append(request)
            return httpx.Response(200, json=report if len(polls) > not_ready else report | {"ready": False, "markdown": None})
        if path == "/runs/r1/cancel":
            cancels.append(request.headers.get("x-orchapod-cancel-token"))
            return httpx.Response(200, json={"id": "r1"})
        if path == DATASET:
            return httpx.Response(200, text=dataset)
        if path in (files or {}):
            return httpx.Response(200, text=files[path])

    handler.polls, handler.cancels, handler.posted = polls, cancels, posted
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


@pytest.mark.parametrize("minutes, refused", [(60, False), (61, True)])
def test_a_real_run_is_refused_when_its_estimate_outlasts_the_hour_it_waits(minutes, refused, stack_ok, capsys):
    templates = [{**t, "estimate": {**t["estimate"], "minutes": minutes}} if t["slug"] == I2["slug"] else t for t in TEMPLATES]
    calls = []
    assert agent.run_all(fake_api(templates=templates, run=live(real_report()), calls=calls), "2", 0.5) == (1 if refused else 0)
    out = capsys.readouterr().out
    assert ("the estimate takes 61 min, over the 60 min a real run waits" in out) is refused
    assert (("POST", "/agent/run") in calls) is not refused  # refused before the run: nothing is spent on a run that cannot be waited for


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


# --- the stack main starts, fake at its edges: no secret is printed or logged, and the total spend is read ---------------------

def make_ledger(db, run=None, **ledger):
    """The throwaway DB as the API leaves it: its own tables (the SQLModel ones), a run that cost `run` if given, and one Spend row
    per keyword (planner, reporter)."""
    from sqlmodel import Session, SQLModel, create_engine

    from api.models.db import Run, Spend

    engine = create_engine(f"sqlite:///{db}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if run is not None:
            session.add(Run(user_id=uuid.uuid4(), cost_usd=Decimal(str(run))))
        session.add_all(Spend(source=source, usd=Decimal(str(usd))) for source, usd in ledger.items())
        session.commit()
    engine.dispose()


@pytest.fixture
def fake_stack(stack_ok, monkeypatch):
    """main -> with_stack -> start_api -> api_env are the real ones; only the uvicorn process and the HTTP transport are fake. The
    fake Popen keeps start_api's argv and env, logs a startup line like uvicorn, and leaves the ledger (`ledger`: make_ledger's
    keywords) in the DB the API was told to use. serve(report, status) answers like the API, and writes every request, with its
    headers and body, to the API's log as an access log would."""
    stack = SimpleNamespace(spawned=[], api_logs=[], ledger={})

    class Spawned(FakeApi):
        def __init__(self, argv, **kw):
            super().__init__()
            self.argv, self.kw = argv, kw
            kw["stdout"].write("INFO:     Started server process\n")
            stack.spawned.append(self)
            if stack.ledger:
                make_ledger(Path(kw["env"]["DATABASE_URL"].split(":///", 1)[1]), **stack.ledger)

    def serve(report, status=200):
        run = live(report)

        def logged(request):
            with open(stack.spawned[0].kw["stdout"].name, "a") as f:
                f.write(f"{request.method} {request.url} {dict(request.headers)} {request.content!r}\n")
            return run(request)

        api = fake_api(status=status, run=logged)  # built before httpx.Client is replaced
        monkeypatch.setattr(httpx, "Client", lambda **kw: api)

    stack.serve = serve
    monkeypatch.setattr(demo.subprocess, "Popen", Spawned)
    monkeypatch.setattr(demo, "wait_healthy", lambda *a: None)
    monkeypatch.setattr(demo, "stop", lambda proc: stack.api_logs.append(Path(proc.kw["stdout"].name).read_text()))
    return stack


SECRETS = {"NEBIUS_API_KEY": "nb-7Qf2-fake-key", "TAVILY_API_KEY": "tv-9Zk4-fake-key", "HF_TOKEN": "hf-3Lm8-fake-token",
           "VASTAI_API_KEY": "va-1Xc6-fake-key", "NEBIUS_IAM_TOKEN": "iam-5Rt0-fake-token"}


@pytest.mark.parametrize("planner_status, exit_code", [(200, 0), (500, 1)])
def test_a_real_run_never_prints_or_logs_a_key(planner_status, exit_code, fake_stack, monkeypatch, capsys):
    """The API's log holds every request it got, and on a FAIL the stack prints its tail."""
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    fake_stack.serve(real_report(), planner_status)

    assert agent.main(REAL) == exit_code
    out = capsys.readouterr()
    everything = out.out + out.err + fake_stack.api_logs[0]
    assert [v for v in SECRETS.values() if v in everything] == []
    # the keys did reach the API (through its env, never its command line), so the check above has something to catch
    env = fake_stack.spawned[0].kw["env"]
    assert (env["NEBIUS_API_KEY"], env["TAVILY_API_KEY"], env["HF_TOKEN"]) == tuple(SECRETS[k] for k in ("NEBIUS_API_KEY", "TAVILY_API_KEY", "HF_TOKEN"))
    assert "VASTAI_API_KEY" not in env and "NEBIUS_IAM_TOKEN" not in env and "STUB" not in env
    assert not any(v in " ".join(fake_stack.spawned[0].argv) for v in SECRETS.values())
    assert "POST http://api/agent/plan" in fake_stack.api_logs[0]  # the log has the requests: a key sent in one would be in it
    assert ("e2e: PASS" in out.out) == (exit_code == 0) and "STUB=1" not in out.out


def test_the_spend_line_adds_the_planner_and_reporter_ledger_to_the_runs_cost(tmp_path):
    make_ledger(tmp_path / "e2e.db", run=0.0823, planner=0.0031, reporter=0.0004)
    assert agent.spend_line(tmp_path / "e2e.db") == "total $0.0858 (run $0.0823 + planner/reporter $0.0035)"
    make_ledger(tmp_path / "refused.db", planner=0.0031)  # a plan refused before /agent/run still cost the planner's call
    assert agent.spend_line(tmp_path / "refused.db") == "total $0.0031 (run $0.0000 + planner/reporter $0.0031)"


def test_the_spend_line_says_so_when_the_db_cannot_be_read_and_never_creates_it(tmp_path):
    line = agent.spend_line(tmp_path / "never-created.db")
    assert line.startswith("total spend unknown") and "unable to open database file" in line
    assert not (tmp_path / "never-created.db").exists()  # read-only: looking must not make a DB


def test_the_spend_line_says_so_when_the_file_is_no_ledger(tmp_path):
    other = sqlite3.connect(tmp_path / "other.db")  # a DB with none of the API's tables
    other.execute("CREATE TABLE unrelated (x)")
    other.close()
    assert "no such table: run" in agent.spend_line(tmp_path / "other.db")


def test_the_spend_line_reads_a_wal_db_the_api_still_holds_open(tmp_path):
    """The API puts every SQLite connection in WAL mode (apps/api/database.py) and is up while the line is read: a read-only
    open must still see what is committed, and must not wait on a transaction in flight."""
    db = tmp_path / "e2e.db"
    make_ledger(db, run=0.0823, planner=0.0031, reporter=0.0004)
    api = sqlite3.connect(db)
    try:
        assert api.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        api.execute("INSERT INTO spend (source, usd, created_at) VALUES ('reporter', 9, '2026-10-22 00:00:00')")  # not committed yet
        assert agent.spend_line(db) == "total $0.0858 (run $0.0823 + planner/reporter $0.0035)"
    finally:
        api.close()


@pytest.mark.parametrize("status, exit_code, ledger, line", [
    (200, 0, {"run": 0.0823, "planner": 0.0031, "reporter": 0.0004}, "total $0.0858 (run $0.0823 + planner/reporter $0.0035)"),
    (500, 1, {"planner": 0.0031}, "total $0.0031 (run $0.0000 + planner/reporter $0.0031)"),  # a planner that failed after it billed
])
def test_a_real_run_ends_with_its_total_spend_read_from_the_db_it_gave_the_api(status, exit_code, ledger, line, fake_stack, monkeypatch, capsys):
    monkeypatch.setenv("NEBIUS_API_KEY", KEY)
    fake_stack.ledger = ledger
    fake_stack.serve(real_report(), status)
    assert agent.main(REAL) == exit_code
    out = capsys.readouterr().out
    assert f"e2e: {line}\n" in out and out.index("e2e: 1 PASS" if exit_code == 0 else "e2e: 0 PASS") < out.index(f"e2e: {line}")


def test_the_total_spend_is_printed_even_when_the_run_is_interrupted(fake_stack, monkeypatch, capsys):
    monkeypatch.setenv("NEBIUS_API_KEY", KEY)
    fake_stack.ledger = {"planner": 0.0031}
    fake_stack.serve(real_report())

    def interrupted(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(agent, "run_all", interrupted)
    with pytest.raises(KeyboardInterrupt):
        agent.main(REAL)
    assert "e2e: total $0.0031 (run $0.0000 + planner/reporter $0.0031)" in capsys.readouterr().out


# --- the golden path (R25): template 4 run as it is -----------------------------------------------------------------------------

GOLDEN_NODES = {"research": "web-research", "synth": "synth-distilabel", "prep": "data-prep", "train": "unsloth-train",
                "serve": "vllm-serve", "evaluate": "judge-eval"}  # template 4's six, written out: what the golden path is
GOLDEN_FILES = [("research", "corpus"), ("synth", "dataset"), ("prep", "dataset"), ("prep", "train_jsonl"), ("prep", "eval_jsonl"),
                ("prep", "test_jsonl"), ("train", "lora_adapter"), ("serve", "model_ref"), ("serve", "base_model_ref"),
                ("evaluate", "eval_summary"), *((node, "cost_json") for node in GOLDEN_NODES)]
STUB_ENDPOINT = {"id": "serve-endpoint_url", "node_id": "serve", "name": "endpoint_url", "kind": "endpoint", "uri": "http://stub.invalid",
                 "download_url": None, "meta": {"endpoint_id": "stub-serve", "keep_alive_min": 15, "expires_at": "2026-10-22T09:00:00+00:00"}}
CHAT_ROWS = "\n".join([json.dumps({"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]})] * 3) + "\n"
GOLDEN_TEXTS = {"/d/prep/dataset": CHAT_ROWS, "/d/evaluate/eval_summary": json.dumps(eval_summary())}


def golden_report(without=(), **changes):
    """A succeeded STUB run of template 4 as the API reports it: six nodes at $0, their artifacts, and vllm-serve's stub endpoint."""
    base = report_with([f for f in GOLDEN_FILES if f not in without], GOLDEN_NODES)
    report = {**base, "run_id": "r1", "status": "succeeded", "cost_usd": 0.0, "error": None, "intent": I4["intent"], "estimate": I4["estimate"],
              "ready": True, "markdown": f"## {I4['plan']['name']}: succeeded\n\n**Cost:** $0.0000 of ${I4['estimate']['usd']:.2f} estimated."}
    report["artifacts"] = [*base["artifacts"], STUB_ENDPOINT]
    return report | changes


def test_the_golden_path_runs_its_template_as_it_is_and_passes(stack_ok, capsys):
    calls = []
    run = live(golden_report(), files=GOLDEN_TEXTS)
    assert agent.run_all(fake_api(run=run, calls=calls), "4") == 0
    assert ("POST", "/agent/plan") not in calls  # no planner matching: the template is the plan
    assert run.posted == [{"intent": I4["intent"], "plan": I4["plan"]}]  # straight to /agent/run, no /agent/plan
    out = capsys.readouterr().out
    assert f"e2e: PASS golden path: run r1 succeeded in 0 s (limit {demo.LIMIT_S} s), cost $0, estimate ${I4['estimate']['usd']}, " \
           f"report ready ({len(golden_report()['markdown'])} chars)" in out
    assert "e2e: 1 PASS, 0 FAIL: golden path PASS" in out and "report, first 5 lines" not in out


def with_endpoint_id(endpoint_id):
    report = golden_report()
    report["artifacts"] = [a | {"meta": {**a["meta"], "endpoint_id": endpoint_id}} if a["name"] == "endpoint_url" else a for a in report["artifacts"]]
    return report


def without_endpoint():
    report = golden_report()
    report["artifacts"] = [a for a in report["artifacts"] if a["name"] != "endpoint_url"]
    return report


@pytest.mark.parametrize("report, texts, text", [
    pytest.param(with_endpoint_id("endpoint-e00real"), GOLDEN_TEXTS, "vllm-serve 'serve' registered no stub-* endpoint", id="a real endpoint id"),
    pytest.param(without_endpoint(), GOLDEN_TEXTS, "vllm-serve 'serve' registered no stub-* endpoint", id="no endpoint"),
    pytest.param(golden_report(without=[("train", "lora_adapter")]), GOLDEN_TEXTS, "unsloth-train 'train' did not register lora_adapter", id="no adapter"),
    pytest.param(golden_report(without=[("evaluate", "cost_json")]), GOLDEN_TEXTS, "node 'evaluate' wrote no cost_json", id="no cost_json"),
    pytest.param(golden_report(cost_usd=0.02), GOLDEN_TEXTS, "cost_usd is 0.02, expected 0 in STUB", id="it cost money"),
    pytest.param(golden_report(), GOLDEN_TEXTS | {"/d/evaluate/eval_summary": json.dumps(eval_summary(stub=False))}, "stub is False in a STUB run", id="a summary that is not a stub's"),
    pytest.param(golden_report(), GOLDEN_TEXTS | {"/d/prep/dataset": "\n"}, "the downloaded dataset has no rows", id="an empty dataset"),
])
def test_the_golden_path_is_strict(report, texts, text, stack_ok, capsys):
    assert agent.run_all(fake_api(run=live(report, files=texts)), "4") == 1
    out = capsys.readouterr().out
    assert "e2e FAIL golden path (run r1 after 0 s)" in out and text in out and "PASS golden path" not in out, out


def test_a_plan_the_run_route_refuses_fails_the_golden_path_with_its_errors(stack_ok, capsys):
    inner = live(golden_report(), files=GOLDEN_TEXTS)

    def refuse(request):
        if request.url.path == "/agent/run":
            return httpx.Response(422, json={"detail": "the plan has errors", "errors": ["serve: unknown input 'lora_adapter'"]})
        return inner(request)

    assert agent.run_all(fake_api(run=refuse), "4") == 1
    out = capsys.readouterr().out
    assert "e2e FAIL golden path" in out and "POST /agent/run -> HTTP 422" in out and "unknown input 'lora_adapter'" in out


def stub_endpoint_plan():
    """Just what check_outputs reads: a data-prep node for the dataset and a vllm-serve node."""
    return {"nodes": [{"id": "prep", "type": "data-prep", "inputs": {}}, {"id": "serve", "type": "vllm-serve", "inputs": {}}]}


@pytest.mark.parametrize("endpoint_id, owner, max_cost, problems", [
    ("stub-serve", "serve", None, []),
    ("endpoint-e00real", "serve", None, ["vllm-serve 'serve' registered no stub-* endpoint (endpoint_url: ['endpoint-e00real'])"]),
    (None, "serve", None, ["vllm-serve 'serve' registered no stub-* endpoint (endpoint_url: none)"]),
    ("stub-serve", "prep", None, ["vllm-serve 'serve' registered no stub-* endpoint (endpoint_url: none)"]),  # another node's does not count
    ("endpoint-e00real", "serve", 0.5, []),  # a real run's vllm-serve is refused before it starts; its endpoint is a real one if it ever ran
])
def test_check_outputs_wants_a_stub_endpoint_of_a_stub_runs_vllm_serve(endpoint_id, owner, max_cost, problems):
    report = report_with([("prep", "dataset")], {"prep": "data-prep", "serve": "vllm-serve"})
    if endpoint_id:
        report["artifacts"].append(STUB_ENDPOINT | {"node_id": owner, "meta": {"endpoint_id": endpoint_id}})
    found = agent.check_outputs(download_client({"/d/prep/dataset": CHAT_ROWS}), report, stub_endpoint_plan(), max_cost)
    assert [p for p in found if "stub-* endpoint" in p] == problems
