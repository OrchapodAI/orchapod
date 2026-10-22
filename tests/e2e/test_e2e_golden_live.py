"""scripts/e2e_demo.py --max-cost N --api URL: the live golden run (template 4, Lane B) against the HOSTED API, proved here on a fake one:
no network, no Docker, no local API. Nobody runs it live before G2 (Hari's console steps, docs/HOSTING.md); `make e2e API=...` is the Orchestrator's."""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import e2e_agent as agent
import e2e_demo as demo
import httpx
import pytest

from tests.e2e.test_e2e_agent import CHAT_ROWS, I4, TEMPLATES, broken_plans, eval_summary, golden_report

API = "https://api.example.test"
TOKEN = "adm-4Hk9-fake-admin-token"  # a stand-in: no test may print it, log it or read a real one
USER, PASSWORD = "alice", "s3cret-pw-Zq8"
USERINFO_API = f"https://{USER}:{PASSWORD}@api.example.test"
LIVE = ["--max-cost", "3", "--api", API]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """The shell holds no admin token unless a test sets one, polling does not sleep, and nothing here may start a local stack, build an
    image or ask Docker: the live run targets a hosted API, which exists only as a fake."""
    monkeypatch.delenv("ORCHAPOD_ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(demo.time, "sleep", lambda s: None)

    def refuse(name):
        return lambda *args, **kwargs: pytest.fail(f"{name}() was reached from a live-run test: that is a local stack or Docker")

    for name in ("with_stack", "start_api", "preflight", "build_images"):
        monkeypatch.setattr(demo, name, refuse(name))


@pytest.fixture(autouse=True)
def limit_untouched():
    """The live limit is a parameter of poll_run, not a global that the next run would inherit."""
    before = demo.LIMIT_S
    yield
    assert demo.LIMIT_S == before


# --- a live run, as the hosted API shows it ----------------------------------------------------------------------------------------

NODE_USD = {"research": 0.016, "synth": 0.21, "prep": 0.0, "train": 1.31, "serve": 0.78, "evaluate": 0.12}  # $2.436 in all
REAL_ENDPOINT = {"id": "serve-endpoint_url", "node_id": "serve", "name": "endpoint_url", "kind": "endpoint",
                 "uri": "https://e00abc.eu-north1.ai.example.test", "download_url": None,
                 "meta": {"endpoint_id": "orchapod-12345678-serve", "keep_alive_min": 15, "expires_at": "2026-10-25T09:41:00+00:00"}}
REAL_EVAL = eval_summary(stub=False, n=40, judged=38, win_rate=0.71, consistency=0.84, exact_match=None)
LIVE_TEXTS = {"/d/prep/dataset": CHAT_ROWS, "/d/evaluate/eval_summary": json.dumps(REAL_EVAL)}
START = datetime(2026, 10, 25, 9, 0, 0, tzinfo=timezone.utc)
MINUTES = {"research": (0, 1.5), "synth": (1.5, 6), "prep": (6, 7), "train": (7, 17), "serve": (17, 21.5), "evaluate": (21.5, 23.5)}  # 23.5 min


def live_report(drop=(), **changes):
    """A succeeded live run of template 4 as the hosted API reports it: six nodes with their $, their artifacts (`drop`: (node, name)
    pairs left out) and the endpoint vllm-serve registered through /internal/ttl, a real one."""
    report = golden_report()
    report["artifacts"] = [REAL_ENDPOINT if a["name"] == "endpoint_url" else a for a in report["artifacts"]
                           if (a["node_id"], a["name"]) not in drop]
    report["nodes"] = [n | {"usd": NODE_USD[n["node_id"]]} for n in report["nodes"]]
    return report | {"cost_usd": round(sum(NODE_USD.values()), 4)} | changes


def summary_for(report, minutes=MINUTES):
    """GET /runs/{id}/summary: the report's own fields, and when each node started and ended."""
    at = lambda m: (START + timedelta(minutes=m)).isoformat()  # noqa: E731
    nodes = [n | {"started_at": at(minutes[n["node_id"]][0]), "finished_at": at(minutes[n["node_id"]][1])} for n in report["nodes"]]
    return {k: report[k] for k in ("run_id", "status", "cost_usd", "error", "artifacts")} | {"nodes": nodes}


def hosted(report, summary=None, files=LIVE_TEXTS, not_ready=0, templates=TEMPLATES, before=None):
    """The hosted API as the run sees it. Returns (client, seen): `seen.requests` is (method, path) of every request, `seen.admin` the
    (method, path, value) of those that carried X-Orchapod-Admin, `seen.cancels` the cancel tokens it got, `seen.posted` the bodies
    of POST /agent/run. The report is ready only after `not_ready` polls. `before(request, seen)` may answer first, or raise."""
    seen = SimpleNamespace(requests=[], admin=[], posted=[], cancels=[], polls=0, client_args=[])
    summary = summary or summary_for(report)

    def serve(request):
        path = request.url.path
        seen.requests.append((request.method, path))
        if admin := request.headers.get("x-orchapod-admin"):
            seen.admin.append((request.method, path, admin))
        if path == "/agent/runs/r1/report":
            seen.polls += 1
        if before and (reply := before(request, seen)) is not None:
            return reply
        if path == "/agent/templates":
            return httpx.Response(200, json=templates)
        if path == "/agent/run":
            seen.posted.append(json.loads(request.content))
            return httpx.Response(201, json={"run_id": "r1", "workflow_id": "w1", "estimate": I4["estimate"], "cancel_token": "tok-live"})
        if path == "/agent/runs/r1/report":
            return httpx.Response(200, json=report if seen.polls > not_ready else report | {"ready": False, "markdown": None})
        if path == "/runs/r1/summary":
            return httpx.Response(200, json=summary)
        if path == "/runs/r1/cancel":
            seen.cancels.append(request.headers.get("x-orchapod-cancel-token"))
            return httpx.Response(200, json={"id": "r1"})
        if path in files:
            return httpx.Response(200, text=files[path])
        raise AssertionError(f"unexpected {request.method} {path}")

    return httpx.Client(base_url=API, transport=httpx.MockTransport(serve)), seen


@pytest.fixture
def hosted_api(monkeypatch):
    """start(report, **hosted_kwargs) puts the fake in the network's place (and the admin token in the shell): demo.main(...) then talks to it."""
    def start(report=None, token=TOKEN, **kw):
        if token is not None:
            monkeypatch.setenv("ORCHAPOD_ADMIN_TOKEN", token)
        client, seen = hosted(report or live_report(), **kw)
        monkeypatch.setattr(httpx, "Client", lambda **k: seen.client_args.append(k) or client)  # built above, with the real class
        return seen

    return start


def secrets_in(captured, *secrets):
    return [s for s in secrets if s in captured.out + captured.err]


# --- refusals: one readable line, exit 2, before any request ---------------------------------------------------------------------

@pytest.fixture
def no_client(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kw: pytest.fail("a client was built: the next thing it does is a request"))


@pytest.mark.parametrize("argv, token, message", [
    ([], None, "refusing to run without --max-cost"),  # the first thing wrong is the first thing said
    (["--api", API], TOKEN, "refusing to run without --max-cost"),
    (["--max-cost", "0", "--api", API], TOKEN, "refusing to run without --max-cost"),
    (["--max-cost", "-1", "--api", API], TOKEN, "refusing to run without --max-cost"),
    (["--max-cost", "nan", "--api", API], TOKEN, "refusing to run without --max-cost"),
    (["--max-cost", "3.01", "--api", API], TOKEN, "caps a run at $3"),
    (["--max-cost", "inf", "--api", API], TOKEN, "caps a run at $3"),
    (["--max-cost", "3"], TOKEN, "refusing to run without --api"),
    (["--max-cost", "3"], None, "refusing to run without --api"),  # api before token, as the brief lists them
    (["--max-cost", "3", "--api", ""], TOKEN, "refusing to run without --api"),  # `make e2e` with API unset passes ""
    (["--max-cost", "3", "--api", "  "], TOKEN, "refusing to run without --api"),
    (["--max-cost", "3", "--api", "http://api.example.test"], TOKEN, "--api must be an https URL"),
    (["--max-cost", "3", "--api", f"http://{USER}:{PASSWORD}@api.example.test"], TOKEN, "--api must be an https URL"),
    (["--max-cost", "3", "--api", "ftp://api.example.test"], TOKEN, "--api must be an https URL"),
    (["--max-cost", "3", "--api", "api.example.test"], TOKEN, "--api must be an https URL"),
    (["--max-cost", "3", "--api", "https://"], TOKEN, "--api must be an https URL"),
    (["--max-cost", "3", "--api", "https:///runs"], TOKEN, "--api must be an https URL"),
    (LIVE, None, "ORCHAPOD_ADMIN_TOKEN is unset"),
    (LIVE, "", "ORCHAPOD_ADMIN_TOKEN is unset"),  # a blank token is an unset one: nobody is the admin (budget.admin)
    (LIVE, "   ", "ORCHAPOD_ADMIN_TOKEN is unset"),
    # httpx quotes a header value it cannot send in its LocalProtocolError, in a form the scrub would not recognise
    (LIVE, "adm-4Hk9\nfake", "ORCHAPOD_ADMIN_TOKEN holds a character that is not printable ASCII"),
    (LIVE, "adm-4Hk9\tfake", "ORCHAPOD_ADMIN_TOKEN holds a character that is not printable ASCII"),
    (LIVE, "adm-4Hk9\x7ffake", "ORCHAPOD_ADMIN_TOKEN holds a character that is not printable ASCII"),
    (LIVE, "adm-4Hk9-fäke", "ORCHAPOD_ADMIN_TOKEN holds a character that is not printable ASCII"),
    (["--max-cost", "3", "--api", USERINFO_API, "--stub"], TOKEN, "--api is for the live run"),
])
def test_a_live_run_is_refused_in_one_line_before_any_request(argv, token, message, no_client, monkeypatch, capsys):
    if token is not None:
        monkeypatch.setenv("ORCHAPOD_ADMIN_TOKEN", token)
    with pytest.raises(SystemExit) as e:
        demo.main(argv)
    out = capsys.readouterr()
    lines = [ln for ln in out.err.splitlines() if ln.strip()]
    assert e.value.code == 2 and out.out == "" and len(lines) == 1 and message in lines[0], out
    shown = [TOKEN, USER, PASSWORD, *([token.strip(), repr(token)[1:-1]] if token and token.strip() else [])]
    assert secrets_in(out, *shown) == [], "a refusal never shows the token (nor its escaped form) or the URL's userinfo"


def test_a_token_with_a_nul_is_refused_too():
    """The environment cannot hold a NUL, but the check is on the token, wherever it came from."""
    assert "not printable ASCII" in demo.refusal(3.0, API, "adm-4Hk9\x00fake")
    assert demo.refusal(3.0, API, TOKEN) is None


def test_a_token_with_a_space_inside_is_printable_and_goes_out_as_it_is(hosted_api):
    api = hosted_api(token="adm 4Hk9")
    assert demo.main(LIVE) == 0 and api.admin == [("POST", "/agent/run", "adm 4Hk9")]


EST = I4["estimate"]["usd"]  # $2.6627 today: the planner's number for the plan at full scale


@pytest.mark.parametrize("cap, refused", [(EST - 0.0001, True), (EST, False)])  # the cap itself is within it
def test_a_golden_path_whose_full_estimate_is_over_the_cap_is_refused_after_one_read(cap, refused, hosted_api, capsys):
    api = hosted_api()
    argv = ["--max-cost", repr(cap), "--api", API]
    if refused:
        with pytest.raises(SystemExit) as e:
            demo.main(argv)
        err = capsys.readouterr().err
        assert e.value.code == 2 and f"the golden path's full estimate ${EST} is over --max-cost ${cap:g}" in err
        assert api.requests == [("GET", "/agent/templates")], "the estimate is read from the templates: nothing else was asked or started"
    else:
        assert demo.main(argv) == 0
        assert ("POST", "/agent/run") in api.requests


def test_a_golden_template_the_hosted_api_does_not_serve_is_refused_before_it_runs(hosted_api, capsys):
    api = hosted_api(templates=[t for t in TEMPLATES if t is not I4])
    with pytest.raises(SystemExit) as e:
        demo.main(LIVE)
    assert e.value.code == 2 and "none is the golden path (slug 'nebius-docs-specialist')" in capsys.readouterr().err
    assert api.requests == [("GET", "/agent/templates")]


def test_a_template_edit_that_drops_a_step_is_refused_before_a_gpu_is_rented(hosted_api, capsys):
    api = hosted_api(templates=[{**t, "plan": broken_plans()["4"]} if t is I4 else t for t in TEMPLATES])
    with pytest.raises(SystemExit) as e:
        demo.main(LIVE)
    err = capsys.readouterr().err
    assert e.value.code == 2 and "the plan of the golden path is research -> synth -> prep -> unsloth-train -> vllm-serve -> judge-eval" in err
    assert api.requests == [("GET", "/agent/templates")]


def test_the_live_run_waits_two_hours_and_the_intents_one():
    """The golden run's healthy worst case is 75 to 87 minutes, and every paid resource has its own server-side stop (the spend deadline,
    the Job's hour, the endpoint's TTL), so an hour would only risk cancelling a run that is going well. Intents 1 to 3 keep theirs."""
    assert demo.LIVE_LIMIT_S == 7200 and agent.REAL_LIMIT_S == 3600


@pytest.mark.parametrize("minutes, refused", [(120, False), (121, True)])
def test_an_estimate_longer_than_the_time_the_run_waits_is_refused(minutes, refused, hosted_api, capsys):
    api = hosted_api(templates=[{**t, "estimate": {**t["estimate"], "minutes": minutes}} if t is I4 else t for t in TEMPLATES])
    if refused:
        with pytest.raises(SystemExit):
            demo.main(LIVE)
        assert f"takes {minutes} min, over the 120 min a live run waits" in capsys.readouterr().err
        assert api.requests == [("GET", "/agent/templates")]
    else:
        assert demo.main(LIVE) == 0


def test_a_stub_run_is_still_the_local_stack_and_forwards_nothing_to_a_hosted_api(monkeypatch):
    started = []
    monkeypatch.setattr(demo, "with_stack", lambda fn, extra=None: started.append((fn, extra)) or 0)
    assert demo.main(["--stub"]) == 0 and demo.main(["--stub", "--max-cost", "3"]) == 0
    assert started == [(demo.run, None)] * 2


# --- the run: as served, as the admin, to its verdict ----------------------------------------------------------------------------

def test_a_live_run_that_delivers_passes_and_shows_its_evidence(hosted_api, capsys):
    api = hosted_api(not_ready=2)
    assert demo.main(LIVE) == 0
    out = capsys.readouterr()
    report = live_report()
    # the PASS line of e2e_agent's real run, with the judge's numbers
    assert (f"e2e: PASS golden path: run r1 succeeded in 0 s (limit {demo.LIVE_LIMIT_S} s), cost $2.4360, estimate ${I4['estimate']['usd']}, "
            f"report ready ({len(report['markdown'])} chars); eval evaluate: n 40, judged 38, win_rate 0.71, exact_match null") in out.out
    # per-node wall time and $ (from /runs/{id}/summary), the run's span against G1's bar, the endpoint's expiry (which comes first)
    assert re.search(r"research\s+web-research\s+succeeded\s+90 s\s+\$0\.0160", out.out)
    assert re.search(r"train\s+unsloth-train\s+succeeded\s+10\.0 min\s+\$1\.3100", out.out)
    assert re.search(r"serve\s+vllm-serve\s+succeeded\s+4\.5 min\s+\$0\.7800", out.out)
    assert "run wall 23.5 min (first node start to last node end); G1's 25-minute bar: met" in out.out
    assert "endpoint serve: expires_at 2026-10-25T09:41:00+00:00" in out.out
    assert out.out.index("endpoint serve: expires_at") < out.out.index("nodes, from /runs/r1/summary"), "the endpoint bills until then: first"
    assert out.out.splitlines()[2].startswith("e2e: started run r1;"), "the run id is on the third line (the report's checklist says so)"
    # the plan goes up as the hosted API serves it, once, with no planner in between and nothing cancelled
    assert api.posted == [{"intent": I4["intent"], "plan": I4["plan"]}]
    assert [r for r in api.requests if r[1] == "/agent/plan"] == [] and api.cancels == []
    assert ("GET", "/runs/r1/summary") in api.requests and api.polls == 3  # two reports not ready, one ready
    assert secrets_in(out, TOKEN) == []


def test_the_admin_header_goes_to_post_agent_run_and_nowhere_else(hosted_api):
    """A download is a 307 to another host, and httpx forwards a custom header to it: the admin token must not be on the client."""
    api = hosted_api()
    assert demo.main(LIVE) == 0
    assert api.admin == [("POST", "/agent/run", TOKEN)]
    assert any(p.startswith("/d/") for _, p in api.requests), "the dataset and the eval summary were downloaded (so this is not vacuous)"
    assert api.client_args == [{"base_url": API, "timeout": 30}]  # no `headers=`


def test_the_admin_token_is_sent_stripped(hosted_api):
    api = hosted_api(token=f"  {TOKEN}\n")
    assert demo.main(LIVE) == 0
    assert api.admin == [("POST", "/agent/run", TOKEN)]  # budget.admin strips the header too


@pytest.mark.parametrize("minutes, bar", [
    ({**MINUTES, "evaluate": (21.5, 25.0)}, "run wall 25.0 min (first node start to last node end); G1's 25-minute bar: met"),
    ({**MINUTES, "evaluate": (21.5, 25.1)}, "run wall 25.1 min (first node start to last node end); G1's 25-minute bar: NOT met"),
])
def test_the_runs_span_is_held_to_g1s_25_minutes_but_a_slow_run_still_passes(minutes, bar, hosted_api, capsys):
    hosted_api(summary=summary_for(live_report(), minutes))
    assert demo.main(LIVE) == 0  # the bar is measured and shown; the limit that fails a run is LIVE_LIMIT_S
    assert bar in capsys.readouterr().out


# --- one FAIL for each check -----------------------------------------------------------------------------------------------------

def failed_run():
    report = live_report(status="failed", error="exit 1: out of memory")
    report["nodes"] = [n | {"status": "failed", "error": "exit 1: out of memory"} if n["node_id"] == "train" else n for n in report["nodes"]]
    return report


def with_endpoint(**changes):
    report = live_report()
    meta = changes.pop("meta", {})
    report["artifacts"] = [a | changes | {"meta": a["meta"] | meta} if a["name"] == "endpoint_url" else a for a in report["artifacts"]]
    return report


@pytest.mark.parametrize("report, files, text", [
    pytest.param(failed_run(), LIVE_TEXTS, "run failed: exit 1: out of memory", id="the run failed"),
    pytest.param(live_report(cost_usd=0.0), LIVE_TEXTS, "a real run that cost $0 called nothing", id="it cost nothing"),
    pytest.param(live_report(cost_usd=3.01), LIVE_TEXTS, "cost_usd $3.01 is over --max-cost $3", id="it cost more than the cap"),
    pytest.param(live_report(drop=[("train", "lora_adapter")]), LIVE_TEXTS, "unsloth-train 'train' did not register lora_adapter", id="no adapter"),
    pytest.param(live_report(drop=[("serve", "endpoint_url")]), LIVE_TEXTS, "vllm-serve 'serve' registered no endpoint_url", id="no endpoint"),
    pytest.param(with_endpoint(uri="http://e00abc.example.test:8000"), LIVE_TEXTS, "endpoint_url that is not https (http)", id="an endpoint over http"),
    pytest.param(with_endpoint(uri="http://stub.invalid", meta={"endpoint_id": "stub-serve"}), LIVE_TEXTS,
                 "endpoint_url that is not https (http), a stub-* endpoint ('stub-serve')", id="a stub endpoint: the hosted API runs on STUB"),
    pytest.param(live_report(), LIVE_TEXTS | {"/d/evaluate/eval_summary": json.dumps(eval_summary(stub=True))}, "stub is True in a real run",
                 id="a summary that is a stub's"),
    pytest.param(live_report(), LIVE_TEXTS | {"/d/evaluate/eval_summary": json.dumps({"n": 40})}, "eval_summary has no judged, wins", id="a summary off the contract"),
    pytest.param(live_report(markdown="## another-plan: succeeded"), LIVE_TEXTS, "the report never names the plan 'nebius-docs-specialist-nemotron-nano-8b'",
                 id="a report for another plan"),
    pytest.param(live_report(intent="something else"), LIVE_TEXTS, "the report is for the intent 'something else', not the one asked", id="another intent"),
    pytest.param(live_report(drop=[("evaluate", "cost_json")]), LIVE_TEXTS, "node 'evaluate' wrote no cost_json, so its cost was never measured",
                 id="a node that measured nothing"),
    pytest.param(live_report(), LIVE_TEXTS | {"/d/prep/dataset": "\n"}, "the downloaded dataset has no rows", id="an empty dataset"),
])
def test_each_check_fails_the_run_and_says_why(report, files, text, hosted_api, capsys):
    hosted_api(report, files=files)
    assert demo.main(LIVE) == 1
    out = capsys.readouterr()
    cost = f"${report['cost_usd']:.4f}"
    assert f"e2e FAIL golden path (run r1 after 0 s, cost {cost}, estimate ${I4['estimate']['usd']})" in out.out, out.out
    assert text in out.out and "PASS golden path" not in out.out, out.out
    assert "nodes, from /runs/r1/summary" in out.out, "the evidence is shown for a FAIL too"
    assert secrets_in(out, TOKEN) == []


def test_a_run_that_outlives_its_limit_is_cancelled_with_the_token_agent_run_returned(hosted_api, monkeypatch, capsys):
    limit = demo.LIVE_LIMIT_S
    clock = iter([0, 100, limit - 1, limit])  # poll_run's t0, then the time after each poll
    monkeypatch.setattr(demo, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda s: None))
    api = hosted_api(not_ready=99)
    assert demo.main(LIVE) == 1
    out = capsys.readouterr().out
    assert api.polls == 3 and api.cancels == ["tok-live"]
    assert f"the run did not end within {limit} s, so it was cancelled" in out and "PASS" not in out
    assert out.count("cancelling run r1 (up to 90 s)") == 1, "said before the POST, which may take that long"
    assert [r for r in api.admin if r[1].endswith("/cancel")] == [], "the cancel is the run's token, not the admin's"


def curl(run_id="r1", host="api.example.test"):
    """What a run that is still running is stopped with: the admin's token as a variable, never its value."""
    return f'curl -X POST -H "X-Orchapod-Admin: $ORCHAPOD_ADMIN_TOKEN" https://{host}/runs/{run_id}/cancel'


def cancels_of(api):
    return [r for r in api.requests if r == ("POST", "/runs/r1/cancel")]


def test_a_cancel_at_the_limit_is_tried_twice_and_a_failure_names_the_run_and_the_admins_curl(hosted_api, monkeypatch, capsys):
    clock = iter([0, demo.LIVE_LIMIT_S])
    monkeypatch.setattr(demo, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda s: None))
    refuse = lambda request, seen: httpx.Response(403, json={"detail": "cancelling this run needs its cancel token"}) if request.url.path.endswith("/cancel") else None  # noqa: E731
    api = hosted_api(not_ready=99, before=refuse)
    assert demo.main(LIVE) == 1
    out = capsys.readouterr()
    assert len(cancels_of(api)) == 2 and out.out.count("cancelling run r1 (up to 90 s)") == 2
    assert f"run r1 did not end within {demo.LIVE_LIMIT_S} s, and POST /runs/r1/cancel -> HTTP 403" in out.out
    assert f"run r1 may still be running; cancel it as the admin: {curl()}" in out.out
    assert secrets_in(out, TOKEN) == []


def test_a_second_try_finds_the_run_cancelled_or_ended(hosted_api, monkeypatch, capsys):
    """The first POST can time out while the cancel goes through; the second then meets a run that has ended: a 409, which is done."""
    clock = iter([0, demo.LIVE_LIMIT_S])
    monkeypatch.setattr(demo, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda s: None))
    answers = iter([httpx.ReadTimeout("no answer"), httpx.Response(409, json={"detail": "Run already in terminal state"})])

    def first_times_out(request, seen):
        if request.url.path.endswith("/cancel"):
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return answer

    api = hosted_api(not_ready=99, before=first_times_out)
    assert demo.main(LIVE) == 1  # the run did not end by itself: a FAIL, but a cancelled one
    out = capsys.readouterr().out
    assert len(cancels_of(api)) == 2 and "may still be running" not in out and f"did not end within {demo.LIVE_LIMIT_S} s, so it was cancelled" in out
    assert "run r1 had ended" in out


def test_a_redirect_is_not_a_cancel(hosted_api, monkeypatch, capsys):
    """A proxy that redirects the POST has cancelled nothing: two tries, then the run is named with the admin's curl."""
    clock = iter([0, demo.LIVE_LIMIT_S])
    monkeypatch.setattr(demo, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda s: None))
    redirect = lambda request, seen: (httpx.Response(307, headers={"location": "https://elsewhere.example.test/"})  # noqa: E731
                                      if request.url.path.endswith("/cancel") else None)
    api = hosted_api(not_ready=99, before=redirect)
    assert demo.main(LIVE) == 1
    out = capsys.readouterr().out
    assert len(cancels_of(api)) == 2 and "POST /runs/r1/cancel -> HTTP 307" in out and f"run r1 may still be running; cancel it as the admin: {curl()}" in out


# --- Ctrl-C and SIGTERM stop the run; a poll that fails is waited through until the limit -----------------------------------------------

def test_ctrl_c_while_polling_cancels_the_run_it_leaves_behind(hosted_api, capsys):
    def interrupt(request, seen):
        if request.url.path == "/agent/runs/r1/report" and seen.polls == 2:
            raise KeyboardInterrupt

    api = hosted_api(not_ready=99, before=interrupt)
    with pytest.raises(KeyboardInterrupt):
        demo.main(LIVE)
    out = capsys.readouterr().out
    assert api.cancels == ["tok-live"] and out.index("cancelling run r1 (up to 90 s)") < out.index("cancelled run r1")


def test_ctrl_c_tries_the_cancel_twice_like_the_limit_does(hosted_api, capsys):
    def interrupt(request, seen):
        if request.url.path == "/agent/runs/r1/report" and seen.polls == 2:
            raise KeyboardInterrupt
        if request.url.path == "/runs/r1/cancel" and not seen.cancels and len(cancels_of(seen)) == 1:
            return httpx.Response(502, text="bad gateway")  # the first POST only

    api = hosted_api(not_ready=99, before=interrupt)
    with pytest.raises(KeyboardInterrupt):
        demo.main(LIVE)
    out = capsys.readouterr().out
    assert len(cancels_of(api)) == 2 and api.cancels == ["tok-live"] and out.count("cancelling run r1 (up to 90 s)") == 2
    assert "cancelled run r1" in out and "may still be running" not in out


def test_a_cancel_that_gets_no_answer_twice_names_the_run_and_the_admins_curl_and_keeps_the_interrupt(hosted_api, capsys):
    def interrupt(request, seen):
        if request.url.path == "/agent/runs/r1/report" and seen.polls == 2:
            raise KeyboardInterrupt
        if request.url.path == "/runs/r1/cancel":
            raise httpx.ReadTimeout("no answer")

    api = hosted_api(not_ready=99, before=interrupt)
    with pytest.raises(KeyboardInterrupt):
        demo.main(LIVE)
    out = capsys.readouterr()
    assert len(cancels_of(api)) == 2 and out.out.count("cancelling run r1 (up to 90 s)") == 2
    assert f"run r1 may still be running; cancel it as the admin: {curl()}" in out.out and "cancelled run r1" not in out.out
    assert secrets_in(out, TOKEN) == [], "the curl names the variable, never the value"


def test_sigterm_unwinds_like_ctrl_c_and_the_old_handler_comes_back(hosted_api):
    def terminate(request, seen):
        if request.url.path == "/agent/runs/r1/report" and seen.polls == 2:
            signal.raise_signal(signal.SIGTERM)

    def unwatched(*_):  # what SIGTERM would meet if golden() installed nothing (the default would end pytest itself)
        raise AssertionError("SIGTERM arrived while no handler of golden() was in place")

    api = hosted_api(not_ready=99, before=terminate)
    outside = signal.signal(signal.SIGTERM, unwatched)
    try:
        with pytest.raises(SystemExit) as e:
            demo.main(LIVE)
        assert e.value.code == 143 and api.cancels == ["tok-live"]
        assert signal.getsignal(signal.SIGTERM) is unwatched  # and the handler from before comes back
    finally:
        signal.signal(signal.SIGTERM, outside)


def ticking(monkeypatch, seconds_per_call):
    """A clock that moves `seconds_per_call` each time it is read (poll_run reads it once per poll), and no sleeping."""
    ticks = iter(range(0, 10**9, seconds_per_call))
    monkeypatch.setattr(demo, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda s: None))


def reports_fail(fault, since=2, until=10**9):
    """`before` for hosted(): the report polls from `since` to `until` meet `fault` (a Response, or a callable that raises)."""
    def before(request, seen):
        if request.url.path == "/agent/runs/r1/report" and since <= seen.polls <= until:
            return fault() if callable(fault) else fault

    return before


def read_timeout():
    raise httpx.ReadTimeout("slow")


def connection_dropped():
    raise httpx.ConnectError("reset")


@pytest.mark.parametrize("fault", [
    pytest.param(httpx.Response(502, text="bad gateway"), id="a 502 from the proxy"),
    pytest.param(httpx.Response(500, text="boom"), id="a 500 from the API"),
    pytest.param(httpx.Response(200, text="<html>maintenance</html>"), id="a 200 that is not JSON"),
    pytest.param(read_timeout, id="a timeout"),
    pytest.param(connection_dropped, id="a dropped connection"),
])
def test_failed_polls_are_waited_through_however_many(fault, hosted_api, capsys):
    """No count gives up on a run: 40 failures in a row used to be 25 too many."""
    api = hosted_api(not_ready=1, before=reports_fail(fault, since=2, until=41))
    assert demo.main(LIVE) == 0
    assert api.polls == 42 and api.cancels == []


def test_a_poll_that_keeps_failing_is_waited_through_until_the_limit_and_then_the_run_is_cancelled(hosted_api, monkeypatch, capsys):
    ticking(monkeypatch, 600)  # the limit is the 13th reading
    api = hosted_api(not_ready=99, before=reports_fail(httpx.Response(502, text="bad gateway")))
    assert demo.main(LIVE) == 1
    out = capsys.readouterr().out
    assert api.polls == 12 and api.cancels == ["tok-live"] and len(cancels_of(api)) == 1
    assert f"the run did not end within {demo.LIVE_LIMIT_S} s, so it was cancelled" in out, "the last good reply is the run's last known state"


def test_a_run_that_was_never_seen_is_cancelled_at_the_limit_and_said_so(hosted_api, monkeypatch, capsys):
    ticking(monkeypatch, 3600)
    api = hosted_api(before=reports_fail(httpx.Response(502, text="bad gateway"), since=1))
    assert demo.main(LIVE) == 1
    out = capsys.readouterr().out
    assert api.polls == 2 and api.cancels == ["tok-live"] and "cancelled run r1" in out and "may still be running" not in out
    assert "e2e FAIL golden path (run r1)" in out and f"the run was not seen once in {demo.LIVE_LIMIT_S} s, so it was cancelled" in out


def test_a_warning_about_failing_polls_comes_at_most_once_a_minute(hosted_api, monkeypatch, capsys):
    ticking(monkeypatch, 10)  # a poll every 10 s: 30 failures cover 300 s
    hosted_api(not_ready=1, before=reports_fail(httpx.Response(502, text="bad gateway"), since=2, until=31))
    assert demo.main(LIVE) == 0
    warnings = [ln for ln in capsys.readouterr().out.splitlines() if "poll failed" in ln]
    assert [re.search(r"poll failed at (\d+) s", ln).group(1) for ln in warnings] == ["20", "80", "140", "200", "260"], warnings


@pytest.mark.parametrize("status, headers", [(404, {}), (401, {}), (307, {"location": "https://elsewhere.example.test/"})])
def test_a_poll_that_will_not_heal_is_not_waited_through_and_the_run_is_left_with_its_curl(status, headers, hosted_api, capsys):
    gone = reports_fail(httpx.Response(status, headers=headers, json={"detail": "no"}), since=2, until=2)
    api = hosted_api(not_ready=99, before=gone)
    assert demo.main(LIVE) == 1
    out = capsys.readouterr().out
    assert api.polls == 2 and api.cancels == [], "nothing here is a reason to cancel: the server's caps stop what runs on"
    assert f"GET /agent/runs/r1/report -> HTTP {status}" in out and f"run r1 may still be running; cancel it as the admin: {curl()}" in out



# --- /agent/run refuses, or the answer is lost ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("status, detail, hint, started", [
    (403, "runs on a rented GPU, billed by the hour: only the admin can start it on the public app", "check ORCHAPOD_ADMIN_TOKEN", False),
    (402, "day cap $5: $2.10 left, the plan needs $2.66", "day cap $5: $2.10 left", False),
    (422, "the plan has errors", "POST /agent/run -> HTTP 422", False),
    (429, "slow down", "POST /agent/run -> HTTP 429", False),
    (503, "the kill switch is on (ORCHAPOD_KILL_SWITCH)", "the kill switch is on", True),  # also what a proxy says when the API is down
    (500, "boom", "POST /agent/run -> HTTP 500", True),
])
def test_a_refused_run_starts_nothing_and_says_what_the_api_said(status, detail, hint, started, hosted_api, capsys):
    refuse = lambda request, seen: httpx.Response(status, json={"detail": detail}) if request.url.path == "/agent/run" else None  # noqa: E731
    api = hosted_api(before=refuse)
    assert demo.main(LIVE) == 1
    out = capsys.readouterr()
    assert hint in out.out and ("the run may have started" in out.out) is started, out.out
    assert api.polls == 0 and api.cancels == [] and secrets_in(out, TOKEN) == []


@pytest.mark.parametrize("reply", [
    pytest.param(httpx.Response(307, headers={"location": "https://elsewhere.example.test/agent/run"}), id="a redirect"),
    pytest.param(httpx.Response(200, text="<html>welcome</html>"), id="a 200 that is not JSON"),
    pytest.param(httpx.Response(201, text=""), id="a 201 with no body"),
])
def test_a_reply_to_post_agent_run_that_is_not_a_run_says_a_run_may_have_started(reply, hosted_api, capsys):
    api = hosted_api(before=lambda request, seen: reply if request.url.path == "/agent/run" else None)
    assert demo.main(LIVE) == 1
    out = capsys.readouterr().out
    assert "the run may have started" in out and "'nebius-docs-specialist-nemotron-nano-8b'" in out
    assert api.polls == 0 and api.cancels == []


@pytest.mark.parametrize("interrupt", [pytest.param(KeyboardInterrupt, id="Ctrl-C"), pytest.param(lambda: sys.exit(143), id="SIGTERM")])
def test_an_interrupt_during_post_agent_run_says_a_run_may_have_started_and_cancels_nothing(interrupt, hosted_api, capsys):
    """There is no cancel token yet; the run, if it started, is found among the runs and stopped by the admin."""
    def interrupted(request, seen):
        if request.url.path == "/agent/run":
            raise interrupt()

    api = hosted_api(before=interrupted)
    with pytest.raises((KeyboardInterrupt, SystemExit)):
        demo.main(LIVE)
    out = capsys.readouterr().out
    assert "interrupted during POST /agent/run; the run may have started" in out and "'nebius-docs-specialist-nemotron-nano-8b'" in out
    assert cancels_of(api) == [] and api.polls == 0


def test_a_lost_reply_to_post_agent_run_says_a_run_may_have_started(hosted_api, capsys):
    def lost(request, seen):
        if request.url.path == "/agent/run":
            raise httpx.ReadTimeout("no answer")

    api = hosted_api(before=lost)
    assert demo.main(LIVE) == 1
    out = capsys.readouterr().out
    assert "the run may have started" in out and "'nebius-docs-specialist-nemotron-nano-8b'" in out and api.polls == 0


# --- the token and the URL's userinfo are never printed --------------------------------------------------------------------------------

@pytest.mark.parametrize("report, code", [(live_report(), 0), (failed_run(), 1), (live_report(cost_usd=0.0), 1)])
def test_a_run_with_credentials_in_its_url_never_prints_them(report, code, hosted_api, capsys):
    api = hosted_api(report)
    assert demo.main(["--max-cost", "3", "--api", USERINFO_API]) == code
    out = capsys.readouterr()
    assert secrets_in(out, TOKEN, USER, PASSWORD) == []
    assert api.client_args == [{"base_url": USERINFO_API, "timeout": 30}]  # the URL did reach the client, so this has something to catch
    assert "api.example.test" in out.out  # the host is evidence, the userinfo is not


@pytest.mark.parametrize("where, code", [("/agent/templates", 1), ("/agent/run", 1), ("/agent/runs/r1/report", 1), ("/runs/r1/summary", 0),
                                         ("/d/prep/dataset", 1)])  # the summary is evidence: the verdict stands without it
def test_an_error_that_quotes_the_token_or_the_url_is_printed_without_them(where, code, hosted_api, monkeypatch, capsys):
    """An exception text is the one place a secret could get into a line: a proxy's error page, an httpx message with the URL in it."""
    ticking(monkeypatch, 600)  # a poll that fails every time is waited through to the limit: this one gets there in 12 readings

    def leak(request, seen):
        if request.url.path == where:
            raise httpx.ConnectError(f"cannot reach {USERINFO_API}{where} with X-Orchapod-Admin: {TOKEN}")

    api = hosted_api(before=leak)
    assert demo.main(["--max-cost", "3", "--api", USERINFO_API]) == code
    out = capsys.readouterr()
    assert secrets_in(out, TOKEN, USER, PASSWORD) == [], out
    assert "<hidden>" in out.out and any(r[1] == where for r in api.requests)


ENCODED_API = f"https://{USER}:p%40ss-Zq8@api.example.test"  # the password is p@ss-Zq8, which httpx decodes and an error may quote


def test_credentials_are_hidden_as_written_and_as_decoded(hosted_api, capsys):
    def leak(request, seen):
        if request.url.path == "/agent/templates":
            raise httpx.ConnectError("cannot reach https://alice:p@ss-Zq8@api.example.test (the URL was ...p%40ss-Zq8...)")

    hosted_api(before=leak)
    assert demo.main(["--max-cost", "3", "--api", ENCODED_API]) == 1
    out = capsys.readouterr()
    assert secrets_in(out, "p@ss-Zq8", "p%40ss-Zq8", USER) == [], out


def test_everything_the_run_prints_to_either_stream_is_scrubbed(monkeypatch, capsys):
    """live() is what prints; golden() is what guarantees that nothing it (or anything it calls) writes holds a secret."""
    def chatty(c, token, max_cost):
        print(f"stdout: {token} {PASSWORD}")
        print(f"stderr: {token} {USER}", file=sys.stderr)
        return 0

    monkeypatch.setattr(demo, "live", chatty)
    assert demo.golden(USERINFO_API, TOKEN, 3.0) == 0
    out = capsys.readouterr()
    assert out.out.count("<hidden>") >= 2 and out.err.count("<hidden>") >= 2 and secrets_in(out, TOKEN, USER, PASSWORD) == []


def test_an_output_that_cannot_be_read_fails_the_run_with_its_verdict_and_evidence(hosted_api, capsys):
    def timeout(request, seen):
        if request.url.path == "/d/evaluate/eval_summary":
            raise httpx.ReadTimeout("slow")

    hosted_api(before=timeout)
    assert demo.main(LIVE) == 1
    out = capsys.readouterr().out
    assert "e2e FAIL golden path (run r1 after 0 s" in out and "could not check the outputs: ReadTimeout" in out
    assert "nodes, from /runs/r1/summary" in out and "endpoint serve: expires_at" in out


def test_an_output_check_that_breaks_on_a_bug_or_an_odd_reply_still_gives_a_verdict_and_the_evidence(hosted_api, capsys):
    report = live_report()
    report["artifacts"] = [{k: v for k, v in a.items() if k != "download_url"} if a["name"] == "dataset" and a["node_id"] == "prep" else a
                           for a in report["artifacts"]]  # a reply off the contract: the check meets a KeyError, not an HTTP error
    hosted_api(report)
    assert demo.main(LIVE) == 1
    out = capsys.readouterr().out
    assert "could not check the outputs: KeyError" in out and "nodes, from /runs/r1/summary" in out


def test_a_url_httpx_cannot_parse_is_a_failure_not_a_traceback_and_shows_no_credentials(monkeypatch, capsys):
    monkeypatch.setenv("ORCHAPOD_ADMIN_TOKEN", TOKEN)  # the real httpx.Client: it refuses the URL before any request
    assert demo.main(["--max-cost", "3", "--api", f"https://{USER}:{PASSWORD}@api.example.test:port"]) == 1
    out = capsys.readouterr()
    assert "e2e FAIL: InvalidURL" in out.out and secrets_in(out, TOKEN, USER, PASSWORD) == []


def test_an_api_error_body_that_echoes_the_token_is_printed_without_it(hosted_api, capsys):
    echo = lambda request, seen: httpx.Response(400, text=f"bad header X-Orchapod-Admin: {TOKEN}") if request.url.path == "/agent/run" else None  # noqa: E731
    hosted_api(before=echo)
    assert demo.main(LIVE) == 1
    out = capsys.readouterr()
    assert secrets_in(out, TOKEN) == [] and "HTTP 400" in out.out


# --- helpers: what the evidence says --------------------------------------------------------------------------------------------------

def test_node_lines_give_each_nodes_wall_time_and_dollars_and_the_span_of_the_run():
    lines, span = demo.node_lines(summary_for(live_report()))
    assert span == 23.5 * 60 and len(lines) == 6
    assert [ln.split()[0] for ln in lines] == ["research", "synth", "prep", "train", "serve", "evaluate"]
    assert re.fullmatch(r"prep\s+data-prep\s+succeeded\s+60 s\s+\$0\.0000", lines[2])


def test_a_node_that_never_started_has_no_wall_time_and_the_span_covers_those_that_did():
    summary = summary_for(live_report())
    summary["nodes"][5] |= {"status": "pending", "started_at": None, "finished_at": None}  # evaluate was never reached
    lines, span = demo.node_lines(summary)
    assert re.fullmatch(r"evaluate\s+judge-eval\s+pending\s+-\s+\$0\.1200", lines[5]) and span == 21.5 * 60
    nothing = {"nodes": [n | {"started_at": None, "finished_at": None} for n in summary["nodes"]]}
    assert demo.node_lines(nothing)[1] is None


@pytest.mark.parametrize("reply", [
    pytest.param(httpx.Response(500, text="boom"), id="a 500"),
    pytest.param(httpx.Response(200, text="<html>not json</html>"), id="a 200 that is not JSON"),
    pytest.param(httpx.Response(200, json={"nodes": [{"node_id": "x"}]}), id="a summary off its shape"),
    pytest.param(httpx.Response(200, json={"nodes": [{"node_id": "x", "type": "t", "status": "s", "usd": "n/a", "started_at": "soon"}]}),
                 id="dollars and timestamps that are not numbers"),
])
def test_a_summary_that_cannot_be_read_does_not_turn_a_pass_into_an_exit_1(reply, hosted_api, capsys):
    hosted_api(before=lambda request, seen: reply if request.url.path == "/runs/r1/summary" else None)
    assert demo.main(LIVE) == 0
    out = capsys.readouterr().out
    assert "PASS golden path" in out and "could not read the summary of run r1" in out
    assert out.index("endpoint serve: expires_at") < out.index("could not read the summary"), "the endpoint's expiry comes first, whatever follows"


def test_a_summary_that_cannot_be_read_does_not_hide_a_fail_either(hosted_api, capsys):
    hosted_api(live_report(cost_usd=0.0), before=lambda request, seen: httpx.Response(200, text="oops") if request.url.path == "/runs/r1/summary" else None)
    assert demo.main(LIVE) == 1
    out = capsys.readouterr().out
    assert "e2e FAIL golden path" in out and "could not read the summary of run r1" in out


def test_poll_run_gives_up_on_a_failed_poll_unless_asked_to_wait_through_it():
    """The stub runs poll a local API: one that fails is a failure. Only the live run waits (live() asks)."""
    c = httpx.Client(base_url=API, transport=httpx.MockTransport(lambda request: httpx.Response(502, text="bad gateway")))
    with pytest.raises(demo.ApiError, match="GET /runs/r1/summary -> HTTP 502"):
        demo.poll_run(c, "r1", "/runs/r1/summary", cancel_token="tok")


def endpoints(*artifacts, node="serve"):
    plan = {"nodes": [{"id": node, "type": "vllm-serve"}, {"id": "prep", "type": "data-prep"}]}
    return demo.check_endpoints({"artifacts": [dict(a) for a in artifacts]}, plan)


def test_check_endpoints_wants_an_https_endpoint_url_that_is_not_a_stub():
    assert endpoints(REAL_ENDPOINT) == []
    assert endpoints() == ["vllm-serve 'serve' registered no endpoint_url"]
    assert endpoints(REAL_ENDPOINT | {"node_id": "prep"}) == ["vllm-serve 'serve' registered no endpoint_url"]  # another node's does not count
    assert endpoints(REAL_ENDPOINT | {"name": "model_ref"}) == ["vllm-serve 'serve' registered no endpoint_url"]
    assert endpoints(REAL_ENDPOINT | {"uri": "http://e00abc.example.test"}) == [
        "vllm-serve 'serve' registered an endpoint_url that is not https (http)"]
    assert endpoints(REAL_ENDPOINT | {"uri": ""}) == ["vllm-serve 'serve' registered an endpoint_url that is not https (no scheme)"]
    assert endpoints(REAL_ENDPOINT | {"meta": {}}) == ["vllm-serve 'serve' registered an endpoint_url that is unnamed (no endpoint_id)"]
    assert endpoints(REAL_ENDPOINT | {"meta": {"endpoint_id": "stub-serve"}}) == [
        "vllm-serve 'serve' registered an endpoint_url that is a stub-* endpoint ('stub-serve')"]
    superseded = REAL_ENDPOINT | {"id": "old", "uri": "http://old.example.test", "meta": {"endpoint_id": "stub-old"}}
    assert endpoints(superseded, REAL_ENDPOINT) == []  # one good registration is the run's endpoint
    assert demo.check_endpoints({"artifacts": []}, {"nodes": [{"id": "prep", "type": "data-prep"}]}) == []  # no vllm-serve, nothing to want


# --- the command: make e2e ----------------------------------------------------------------------------------------------------------------

@pytest.mark.skipif(not shutil.which("make"), reason="make is not installed")
@pytest.mark.parametrize("args, tail", [
    ([f"API={API}"], f'scripts/e2e_demo.py --max-cost "3" --api "{API}"'),
    ([f"API={API}", "MAX_COST=2.8"], f'scripts/e2e_demo.py --max-cost "2.8" --api "{API}"'),
    ([], 'scripts/e2e_demo.py --max-cost "3" --api ""'),  # forgotten: the script refuses it in a line
])
def test_make_e2e_passes_the_api_and_the_cap(args, tail):
    dry_run = subprocess.run(["make", "-n", "e2e", *args], cwd=demo.ROOT, capture_output=True, text=True, check=True).stdout
    assert dry_run.strip().endswith(tail), dry_run


def test_the_help_and_the_docstring_describe_the_live_run(capsys):
    with pytest.raises(SystemExit) as e:
        demo.main(["--help"])
    help_text = capsys.readouterr().out
    assert e.value.code == 0 and "--api" in help_text and "ORCHAPOD_ADMIN_TOKEN" in help_text
    assert "written on D3" not in demo.__doc__ and "ORCHAPOD_ADMIN_TOKEN" in demo.__doc__ and "X-Orchapod-Admin" in demo.__doc__


def test_run_as_a_script_it_refuses_in_one_line(tmp_path):
    """pytest imports e2e_demo by name; `python scripts/e2e_demo.py` runs it as __main__ and e2e_agent, which refusal() imports, imports it
    again: the refusal path must work that way too."""
    env = {k: v for k, v in os.environ.items() if k != "ORCHAPOD_ADMIN_TOKEN"}
    done = subprocess.run([sys.executable, str(demo.ROOT / "scripts" / "e2e_demo.py"), "--max-cost", "3", "--api", API], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 2 and done.stdout == "", done
    assert done.stderr.strip().splitlines() == ["e2e: refusing to run: ORCHAPOD_ADMIN_TOKEN is unset (the hosted API's admin token: "
                                                "only the admin can start a run that rents a GPU)"]
