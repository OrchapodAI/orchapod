"""scripts/e2e_demo.py: the logic around the stub e2e. The run itself is `make check E2E=1` (needs Docker and `make up`)."""

import copy
import json
import re
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import e2e_demo as e2e  # scripts/ is on pytest's import path (pytest.ini)
import httpx
import pytest
import yaml

from api.executor.dag import compile_dag

ROOT = Path(__file__).resolve().parents[2]

ROW_SCHEMA = {  # contracts "Data nodes": the intent #2 schema
    "type": "object", "additionalProperties": False,
    "required": ["user_id", "movie_title", "action", "timestamp", "device"],
    "properties": {
        "user_id": {"type": "string"}, "movie_title": {"type": "string"},
        "action": {"enum": ["like", "share", "subscribe"]},
        "timestamp": {"type": "string", "format": "date-time"},
        "device": {"enum": ["mobile", "tv", "web", "tablet"]},
    },
}
ROW = {"user_id": "u1", "movie_title": "Heat", "action": "like", "timestamp": "2026-01-01T00:00:00Z", "device": "tv"}
INTENT2 = {
    "slug": "movie-events", "title": "Movie events", "intent": "Synthetic data of movie likes, shares and subscribes",
    "plan": {"name": "movie-events", "nodes": [
        {"id": "synth", "type": "synth-distilabel", "needs": [],
         "inputs": {"pipeline_template": "structured", "row_schema": ROW_SCHEMA, "n_samples": 100}},
        {"id": "prep", "type": "data-prep", "needs": ["synth"],
         "inputs": {"dataset": "${{ nodes.synth.outputs.dataset }}", "format": "structured"}},
    ]},
    "estimate": {"usd": 0.1, "minutes": 3},
}
GROUNDED = {"slug": "legal", "plan": {"name": "legal", "nodes": [
    {"id": "synth", "type": "synth-distilabel", "needs": [], "inputs": {"pipeline_template": "grounded"}}]}}


def good_summary() -> dict:
    def node(i, t):
        return {"node_id": i, "type": t, "status": "succeeded", "usd": 0.0, "error": None}

    def art(i, name):
        return {"id": f"{i}-{name}", "node_id": i, "name": name, "kind": "dataset", "uri": f"r2://b/runs/r/{i}/{name}",
                "download_url": f"/artifacts/{i}-{name}/download", "meta": {}}

    return {"run_id": "r", "status": "succeeded", "cost_usd": 0.0, "error": None,
            "nodes": [node("synth", "synth-distilabel"), node("prep", "data-prep")],
            "artifacts": [art("synth", "dataset"), art("synth", "cost_json"), art("prep", "dataset"),
                          art("prep", "train_jsonl"), art("prep", "eval_jsonl"), art("prep", "test_jsonl"),
                          art("prep", "cost_json")]}


def test_api_env_is_stub_local_and_cannot_spend(tmp_path):
    paid = ("VASTAI_API_KEY", "RUNPOD_API_KEY", "NEBIUS_API_KEY", "NEBIUS_IAM_TOKEN", "NEBIUS_PROJECT_ID",
            "ORCHAPOD_ENDPOINT_TOKEN", "TAVILY_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HF_TOKEN")
    shell = {k: "secret" for k in paid} | {
        "PATH": "/usr/bin", "DATABASE_URL": "postgresql+asyncpg://dev", "ORCHAPOD_KILL_SWITCH": "1",
        "ORCHAPOD_CONTROL_URL": "http://host.docker.internal:8002", "REDIS_URL": "redis://hosted:6379",
        "ORCHAPOD_R2_ENDPOINT": "https://storage.eu-north1.nebius.cloud", "ORCHAPOD_R2_ACCESS_KEY": "real-key"}
    env = e2e.api_env(8123, tmp_path / "e2e.db", shell)
    assert not set(paid) & set(env), "a stub run must not see any paid key (VASTAI_API_KEY above all)"
    assert env["STUB"] == "1" and env["ORCHAPOD_KILL_SWITCH"] == "0" and env["PATH"] == "/usr/bin"
    assert env["ORCHAPOD_CONTROL_URL"] == "http://127.0.0.1:8123"  # LocalDocker rewrites it to host.docker.internal
    assert env["DATABASE_URL"] == f"sqlite+aiosqlite:///{tmp_path}/e2e.db"  # never the dev database
    assert env["REDIS_URL"] == "redis://localhost:6379"  # the compose stack, not whatever the shell points at
    assert env["ORCHAPOD_R2_ENDPOINT"] == "http://localhost:9000" and env["ORCHAPOD_R2_ACCESS_KEY"] == "orchapod"
    assert str(ROOT / "apps") in env["PYTHONPATH"] and str(ROOT / "packages/sdk-py") in env["PYTHONPATH"]


def test_the_stub_api_never_takes_8002_the_dev_api(monkeypatch):
    """The first port it may bind is 8003, even when 8002 is free; and the default is what start_api uses."""
    import inspect

    assert inspect.signature(e2e.listen_on_free_port).parameters["start"].default == 8003
    asked = []

    def refuse(*args, **kwargs):
        asked.append(args)
        raise RuntimeError("stop here")

    monkeypatch.setattr(e2e, "listen_on_free_port", refuse)
    with pytest.raises(RuntimeError, match="stop here"):
        e2e.start_api(Path("/nonexistent"))
    assert asked == [()], "start_api asks for the default start, not a port of its own"


@pytest.mark.parametrize("env, host", [(None, "127.0.0.1"), ("172.17.0.1", "172.17.0.1")])
def test_the_stub_api_listens_on_loopback_unless_told(env, host, monkeypatch):
    """A node container reaches the API as host.docker.internal: Docker Desktop forwards that name to the host's 127.0.0.1; on
    Linux it is the docker0 gateway, which a 127.0.0.1 listener never answers, so Linux opts in with E2E_BIND_HOST (never
    every interface by default: the STUB API takes runs from anyone who reaches it)."""
    if env:
        monkeypatch.setenv("E2E_BIND_HOST", env)
    else:
        monkeypatch.delenv("E2E_BIND_HOST", raising=False)
    assert e2e.bind_host() == host
    asked = []

    def refuse(*args, **kwargs):  # no real bind: macOS would ask Hari to accept incoming connections
        asked.append(kwargs)
        raise RuntimeError("stop here")

    monkeypatch.setattr(e2e, "listen_on_free_port", refuse)
    with pytest.raises(RuntimeError, match="stop here"):
        e2e.start_api(Path("/nonexistent"))
    assert asked == [{"host": host}]  # start_api binds what bind_host says


def test_preflight_on_linux_asks_for_the_bind_host(monkeypatch):
    monkeypatch.setattr(e2e.sys, "platform", "linux")
    monkeypatch.delenv("E2E_BIND_HOST", raising=False)
    monkeypatch.setattr(e2e.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 0})())
    monkeypatch.setattr(e2e.socket, "create_connection", lambda *a, **k: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(e2e.httpx, "get", lambda *a, **k: type("G", (), {"raise_for_status": lambda self: None})())
    assert any("E2E_BIND_HOST" in p for p in e2e.preflight())
    monkeypatch.setenv("E2E_BIND_HOST", "172.17.0.1")
    assert not any("E2E_BIND_HOST" in p for p in e2e.preflight())

def test_the_api_port_is_held_from_choice_to_start():
    """Two `make check` at once must not pick the same port, nor mistake each other's API for their own."""
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        taken = busy.getsockname()[1]
        with e2e.listen_on_free_port(taken) as held:
            port = held.getsockname()[1]
            assert port > taken  # the busy one is skipped
            with socket.socket() as late, pytest.raises(OSError):
                late.bind(("127.0.0.1", port))  # and nobody else can take the one we chose


def test_preflight_says_which_service_is_missing():
    problems = e2e.preflight({"REDIS_URL": "redis://127.0.0.1:1", "ORCHAPOD_R2_ENDPOINT": "http://127.0.0.1:1"})  # port 1: closed
    assert any("Redis" in p and "make up" in p for p in problems), problems
    assert any("MinIO" in p and "make up" in p for p in problems), problems


def test_find_intent2_is_the_template_with_a_structured_synth_node():
    assert e2e.find_intent2([GROUNDED, INTENT2]) is INTENT2
    assert e2e.find_intent2([INTENT2["plan"]]) is INTENT2["plan"]  # a bare plan file works too
    assert e2e.find_intent2([GROUNDED]) is None and e2e.find_intent2([]) is None


def test_get_templates_reads_the_route_and_names_a_broken_one():
    def client(status, body=None):
        return httpx.Client(base_url="http://api", transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body)))

    assert e2e.get_templates(client(200, [INTENT2])) == [INTENT2]
    for status in (404, 500):  # a route that is missing or broken is a failure naming its status: nothing is left to SKIP
        with pytest.raises(RuntimeError, match=f"GET /agent/templates -> HTTP {status}"):
            e2e.get_templates(client(status, {"detail": "boom"}))


def test_plan_yaml_is_a_workflow_the_api_compiles():
    dag = compile_dag(e2e.plan_yaml(INTENT2["plan"]), {})
    assert [n.id for n in dag.topological_order()] == ["synth", "prep"]
    assert dag.nodes["synth"].inputs["row_schema"] == ROW_SCHEMA
    assert dag.nodes["prep"].inputs["dataset"] == "${{ nodes.synth.outputs.dataset }}"


def test_check_run_accepts_a_good_stub_run():
    assert e2e.check_run(good_summary()) == []


def test_check_run_reports_the_node_error_of_a_failed_run():
    s = good_summary()
    s["status"], s["error"] = "failed", "exit 1: boom"
    s["nodes"][1] |= {"status": "failed", "error": "exit 1: boom"}
    assert any("exit 1: boom" in p for p in e2e.check_run(s))


def test_check_run_wants_the_three_files_on_the_data_prep_node():
    s = good_summary()
    s["artifacts"] = [a for a in s["artifacts"] if a["name"] != "train_jsonl"]
    (problem,) = e2e.check_run(s)
    assert "train_jsonl" in problem
    s = good_summary()  # synth's own `dataset` must not stand in for data-prep's
    s["artifacts"] = [a for a in s["artifacts"] if (a["node_id"], a["name"]) != ("prep", "dataset")]
    assert any("dataset" in p for p in e2e.check_run(s))


def test_check_run_wants_zero_cost_measured_on_every_node():
    s = good_summary()
    s["cost_usd"] = 0.02
    assert any("cost_usd" in p for p in e2e.check_run(s))
    s = good_summary()
    s["nodes"][0]["usd"] = 0.01
    assert any("synth" in p for p in e2e.check_run(s))
    s = good_summary()
    s["artifacts"] = [a for a in s["artifacts"] if (a["node_id"], a["name"]) != ("synth", "cost_json")]
    assert any("cost_json" in p for p in e2e.check_run(s))
    s = good_summary()
    s["nodes"] = s["nodes"][:1]
    assert any("data-prep" in p for p in e2e.check_run(s))


def spent(total, **by_node):
    """good_summary() that cost `total`, each node `by_node[node_id]` (default 0)."""
    s = good_summary()
    s["cost_usd"] = total
    for n in s["nodes"]:
        n["usd"] = by_node.get(n["node_id"], 0.0)
    return s


def test_check_run_of_a_real_run_wants_more_than_zero_and_at_most_the_cap():
    """With max_cost the run is judged on 0 < cost_usd <= max_cost; a node may cost nothing (data-prep) but never less."""
    assert e2e.check_run(spent(0.0823, synth=0.0823), 0.5) == []
    assert e2e.check_run(spent(0.5, synth=0.5), 0.5) == []  # the cap itself is within it
    assert any("a real run that cost $0 called nothing" in p for p in e2e.check_run(spent(0.0), 0.5))
    assert any("cost_usd $0.51 is over --max-cost $0.5" in p for p in e2e.check_run(spent(0.51, synth=0.51), 0.5))
    assert any("'prep'" in p for p in e2e.check_run(spent(0.08, synth=0.09, prep=-0.01), 0.5))
    assert any("expected 0 in STUB" in p for p in e2e.check_run(spent(0.0823, synth=0.0823)))  # no cap: the STUB rule, as before


def test_check_run_names_a_missing_cost_json_in_the_words_of_its_kind_of_run():
    """A real run's node that wrote no cost_json was not measured, which is not the same as costing $0."""
    def without_synth_cost_json(s):
        s["artifacts"] = [a for a in s["artifacts"] if (a["node_id"], a["name"]) != ("synth", "cost_json")]
        return s

    assert e2e.check_run(without_synth_cost_json(good_summary())) == ["node 'synth' wrote no cost_json, so its $0 was never measured"]
    assert e2e.check_run(without_synth_cost_json(spent(0.0823, synth=0.0823)), 0.5) == [
        "node 'synth' wrote no cost_json, so its cost was never measured"]


def test_check_run_of_a_failed_real_run_names_the_node_error_not_the_cost():
    s = spent(0.0)
    s["status"], s["error"] = "failed", "exit 1: boom"
    s["nodes"][1] |= {"status": "failed", "error": "exit 1: boom"}
    problems = e2e.check_run(s, 0.5)
    assert any("exit 1: boom" in p for p in problems) and not any("cost" in p for p in problems), problems


def test_check_rows_wants_rows_with_exactly_the_schema_fields():
    line = json.dumps(ROW)
    assert e2e.check_rows(line + "\n" + line + "\n", ROW_SCHEMA) == []
    assert e2e.check_rows(line, json.dumps(ROW_SCHEMA)) == []  # row_schema may arrive as a JSON string
    assert e2e.check_rows(json.dumps({"a": 1}), None) == []  # no schema: only "rows exist"
    assert e2e.check_rows("\n", ROW_SCHEMA)
    assert any("not JSON" in p for p in e2e.check_rows("nope", ROW_SCHEMA))
    assert any("extra" in p for p in e2e.check_rows(json.dumps(ROW | {"extra": 1}), ROW_SCHEMA))
    assert any("device" in p for p in e2e.check_rows(json.dumps({k: v for k, v in ROW.items() if k != "device"}), ROW_SCHEMA))


def templates_on_disk() -> list[dict]:
    return [json.loads(f.read_text()) for f in sorted((ROOT / "apps/api/agent/templates").glob("*.json"))]


def test_exactly_one_shipped_template_is_intent2():
    found = [t for t in templates_on_disk() if e2e.find_intent2([t])]
    assert len(found) == 1, "the e2e would fail or pick the wrong plan"


def test_the_intent2_template_runs_on_the_nodes_that_exist():
    from packages.workflow_schema.models import NODE_REGISTRY, NodeType

    plan = e2e.plan_of(e2e.find_intent2(templates_on_disk()))
    compile_dag(e2e.plan_yaml(plan), {})
    for node in plan["nodes"]:
        assert (ROOT / "containers" / node["type"] / "Dockerfile").exists(), node
        assert NODE_REGISTRY[NodeType(node["type"])]["runtime"] in ("cpu", "api"), node  # LocalDocker runs these
    assert yaml.safe_load(e2e.plan_yaml(plan)) == copy.deepcopy(plan)


# --- qa-w2 review carry-overs ---------------------------------------------------------------------------------------------

def test_paid_names_every_key_and_token_the_executor_forwards_to_containers():
    """A new secret in FORWARD that PAID misses would reach a stub run's API through the shell."""
    from api.executor.run_workflow import FORWARD

    secrets = {k for k in FORWARD if k.endswith(("_KEY", "_TOKEN"))} - {"ORCHAPOD_R2_ACCESS_KEY", "ORCHAPOD_R2_SECRET_KEY"}
    assert {"NEBIUS_API_KEY", "TAVILY_API_KEY", "HF_TOKEN"} <= secrets  # the filter still finds the real ones
    assert secrets <= set(e2e.PAID), f"add to PAID in scripts/e2e_demo.py: {sorted(secrets - set(e2e.PAID))}"


class FakeApi:
    """A Popen stand-in: terminate() is fine, wait() times out for the first `hangs` calls."""

    def __init__(self, hangs=0):
        self.hangs, self.calls = hangs, []

    def terminate(self):
        self.calls.append("terminate")

    def kill(self):
        self.calls.append("kill")

    def wait(self, timeout):
        self.calls.append(("wait", timeout))
        if self.hangs:
            self.hangs -= 1
            raise subprocess.TimeoutExpired("api", timeout)


def test_stop_gives_the_api_45_s_to_stop_its_node_before_it_kills_it():
    """The API's own shutdown stops a running node (docker stop -t 30); killing it sooner orphans that container."""
    api = FakeApi()
    e2e.stop(api)
    assert api.calls == ["terminate", ("wait", 45)]  # a clean exit is never killed
    api = FakeApi(hangs=1)
    e2e.stop(api)
    assert api.calls == ["terminate", ("wait", 45), "kill"]


def test_a_stack_that_cannot_start_is_reported_not_a_traceback(monkeypatch, capsys):
    def no_port(tmp, extra=None):
        raise RuntimeError("no free port in 8002..8051")

    stopped = []
    monkeypatch.setattr(e2e, "start_api", no_port)
    monkeypatch.setattr(e2e, "stop", stopped.append)
    assert e2e.with_stack(lambda c: pytest.fail("no stack, no run")) == 1
    assert "e2e FAIL: no free port" in capsys.readouterr().out
    assert stopped == []  # there is no API to stop


def test_the_api_stops_however_the_run_ends(monkeypatch):
    api, stopped = FakeApi(), []
    monkeypatch.setattr(e2e, "start_api", lambda tmp, extra=None: (api, "http://127.0.0.1:1"))
    monkeypatch.setattr(e2e, "wait_healthy", lambda *a: None)
    monkeypatch.setattr(e2e, "stop", stopped.append)

    def interrupted(client):
        raise KeyboardInterrupt  # Ctrl-C and SIGTERM (SystemExit) both unwind through the same finally

    with pytest.raises(KeyboardInterrupt):
        e2e.with_stack(interrupted)
    assert e2e.with_stack(lambda c: 3) == 3  # fn's exit code is the stack's
    assert stopped == [api, api]


def test_extra_env_lands_last_but_the_stub_basics_stay(tmp_path):
    env = e2e.api_env(8123, tmp_path / "e2e.db", {"PATH": "/usr/bin"}, {"ORCHAPOD_ANON_SCALE": "1"})
    assert env["ORCHAPOD_ANON_SCALE"] == "1" and env["STUB"] == "1" and env["ORCHAPOD_KILL_SWITCH"] == "0"


def test_a_none_in_extra_removes_the_name_so_a_real_run_has_no_stub(tmp_path):
    """A real run's API must not inherit a shell's STUB=1 or a base URL that would receive the key, and must get its own keys."""
    shell = {"PATH": "/usr/bin", "STUB": "1", "NEBIUS_BASE_URL": "https://elsewhere.example/v1", "NEBIUS_API_KEY": "from-the-shell"}
    env = e2e.api_env(8123, tmp_path / "e2e.db", shell, {"STUB": None, "NEBIUS_BASE_URL": None, "NEBIUS_API_KEY": "k"})
    assert "STUB" not in env and "NEBIUS_BASE_URL" not in env
    assert env["NEBIUS_API_KEY"] == "k" and env["ORCHAPOD_KILL_SWITCH"] == "0" and env["PATH"] == "/usr/bin"


@pytest.mark.parametrize("extra, stub", [(None, True), ({"ORCHAPOD_ANON_SCALE": "1"}, True), ({"STUB": None}, False)])
def test_with_stack_says_stub_only_when_the_api_runs_on_stub(extra, stub, monkeypatch, capsys):
    monkeypatch.setattr(e2e, "start_api", lambda tmp, extra=None: (FakeApi(), "http://127.0.0.1:1"))
    monkeypatch.setattr(e2e, "wait_healthy", lambda *a: None)
    monkeypatch.setattr(e2e, "stop", lambda proc: None)
    assert e2e.with_stack(lambda c: 0, extra) == 0
    assert ("STUB=1" in capsys.readouterr().out) is stub


RUNNING = {"status": "running", "nodes": [{"node_id": "a", "status": "running"}]}


def test_poll_run_cancels_a_run_that_outlives_the_limit_with_its_cancel_token(monkeypatch):
    """An anonymous cancel without the run's token is a 403 (contracts "Run control API"), and the e2e's API has no admin."""
    seen = []

    def api(request):
        seen.append((request.method, request.url.path, request.headers.get("x-orchapod-cancel-token")))
        return httpx.Response(200, json=RUNNING)

    monkeypatch.setattr(e2e, "LIMIT_S", 0)
    reply, _ = e2e.poll_run(httpx.Client(base_url="http://api", transport=httpx.MockTransport(api)), "r1", "/runs/r1/summary",
                            cancel_token="tok-1")
    assert reply["status"] == "running"
    assert seen == [("GET", "/runs/r1/summary", None), ("POST", "/runs/r1/cancel", "tok-1")]


def test_a_cancel_the_api_refuses_is_a_failure_but_a_run_that_just_ended_is_not(monkeypatch):
    monkeypatch.setattr(e2e, "LIMIT_S", 0)

    def client(cancel_status):
        def api(request):
            if request.method == "POST":
                return httpx.Response(cancel_status, json={"detail": "cancelling this run needs its cancel token"})
            return httpx.Response(200, json=RUNNING)

        return httpx.Client(base_url="http://api", transport=httpx.MockTransport(api))

    with pytest.raises(RuntimeError, match="run r1 did not end within 0 s, and POST /runs/r1/cancel -> HTTP 403: .*cancel token"):
        e2e.poll_run(client(403), "r1", "/runs/r1/summary", cancel_token="wrong")  # it would run on: say so, never "so it was cancelled"
    reply, _ = e2e.poll_run(client(409), "r1", "/runs/r1/summary", cancel_token="tok-1")  # 409: it ended while we asked
    assert reply["status"] == "running"


def test_poll_run_holds_a_run_to_the_limit_it_is_given_not_to_the_stub_one(monkeypatch):
    """A real run waits an hour: poll_run(limit=...) beats LIMIT_S (300 s), which the stub runs keep. The clock is poll_run's t0, then
    the time after each poll."""
    clock = iter([0, 100, 599, 600])
    monkeypatch.setattr(e2e, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda s: None))
    seen = []

    def api(request):
        seen.append((request.method, request.url.path, request.headers.get("x-orchapod-cancel-token")))
        return httpx.Response(200, json=RUNNING)

    reply, seconds = e2e.poll_run(httpx.Client(base_url="http://api", transport=httpx.MockTransport(api)), "r1", "/runs/r1/summary",
                                  cancel_token="tok-1", limit=600)
    assert seconds == 600 and reply["status"] == "running"
    assert seen == [("GET", "/runs/r1/summary", None)] * 3 + [("POST", "/runs/r1/cancel", "tok-1")]  # 3 polls; the stub's 300 s would stop at 2


def test_a_cancel_the_api_refuses_names_the_limit_the_run_was_held_to(monkeypatch):
    clock = iter([0, 700])
    monkeypatch.setattr(e2e, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda s: None))
    api = lambda r: httpx.Response(403 if r.method == "POST" else 200, json=RUNNING)  # noqa: E731
    with pytest.raises(RuntimeError, match="run r1 did not end within 600 s, and POST /runs/r1/cancel -> HTTP 403"):
        e2e.poll_run(httpx.Client(base_url="http://api", transport=httpx.MockTransport(api)), "r1", "/runs/r1/summary",
                     cancel_token="tok-1", limit=600)


def test_run_plan_cancels_with_the_token_start_returned(monkeypatch):
    monkeypatch.setattr(e2e, "LIMIT_S", 0)
    posts = []

    def api(request):
        if request.method == "GET":
            return httpx.Response(200, json=RUNNING)
        posts.append((request.url.path, request.headers.get("x-orchapod-cancel-token")))
        made = {"/workflows": {"id": "w1"}, "/runs": {"id": "r1"}, "/runs/r1/start": {"id": "r1", "cancel_token": "tok-start"}}
        return httpx.Response(200, json=made.get(request.url.path, {"id": "r1"}))

    e2e.run_plan(httpx.Client(base_url="http://api", transport=httpx.MockTransport(api)), INTENT2["plan"])
    assert posts == [("/workflows", None), ("/runs", None), ("/runs/r1/start", None), ("/runs/r1/cancel", "tok-start")]


def test_poll_run_ends_when_the_done_test_says_so(monkeypatch):
    replies = iter([{"status": "succeeded", "ready": False, "nodes": []}, {"status": "succeeded", "ready": True, "nodes": []}])
    monkeypatch.setattr(e2e.time, "sleep", lambda s: None)
    c = httpx.Client(base_url="http://api", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=next(replies))))
    reply, _ = e2e.poll_run(c, "r1", "/agent/runs/r1/report", done=lambda r: r["ready"], cancel_token="tok-1")  # terminal is not enough
    assert reply["ready"] is True


def test_check_run_wants_unsloth_trains_lora_adapter_and_not_a_merged_model():
    """Templates 4 and 5 train with merge: false, which registers the adapter only (ml-w7)."""
    s = good_summary()
    s["nodes"].append({"node_id": "train", "type": "unsloth-train", "status": "succeeded", "usd": 0.0, "error": None})
    s["artifacts"].append({"id": "train-cost_json", "node_id": "train", "name": "cost_json", "kind": "metrics", "uri": "r2://b/x",
                           "download_url": "/d", "meta": {}})
    assert e2e.check_run(s) == ["unsloth-train 'train' did not register lora_adapter"]
    s["artifacts"].append({"id": "train-lora_adapter", "node_id": "train", "name": "lora_adapter", "kind": "model", "uri": "r2://b/y",
                           "download_url": "/d", "meta": {}})
    assert e2e.check_run(s) == []


class RecordedBuilds:
    """subprocess.run stand-in for `docker build`: keeps each command line and answers like a build that worked."""

    def __init__(self):
        self.commands = []

    def __call__(self, cmd, **kwargs):
        self.commands.append(cmd)
        return SimpleNamespace(returncode=0, stdout="sha256:0", stderr="")


def test_build_images_builds_unsloth_train_from_its_stub_stage_and_every_other_node_as_before(monkeypatch):
    """ml-w7: the stub stack has no 20 GB amd64 CUDA image to build, so unsloth-train is built from its slim `stub` stage."""
    builds = RecordedBuilds()
    monkeypatch.setattr(e2e.subprocess, "run", builds)
    assert e2e.build_images(["data-prep", "unsloth-train", "data-prep"]) is None  # a node type twice builds once
    assert builds.commands == [
        ["docker", "build", "-q", "-t", "orchapod/data-prep:dev", "-f", "containers/data-prep/Dockerfile", "."],
        ["docker", "build", "-q", "--target", "stub", "-t", "orchapod/unsloth-train:dev", "-f", "containers/unsloth-train/Dockerfile", "."]]


def test_every_stub_target_is_a_stage_of_its_dockerfile():
    """A renamed stage would fail the stub e2e at its build, after the others'. (tests/containers pins the stage's content.)"""
    assert e2e.STUB_TARGETS == {"unsloth-train": "stub"}
    for node, stage in e2e.STUB_TARGETS.items():
        dockerfile = (ROOT / "containers" / node / "Dockerfile").read_text()
        assert re.search(rf"^FROM .+ AS {stage}\s*$", dockerfile, re.MULTILINE | re.IGNORECASE), f"containers/{node}/Dockerfile has no stage {stage}"


def test_check_run_wants_what_each_node_type_promises():
    """The agent e2e runs plans with more node types than intent #2's (contracts "Data nodes", "ML nodes")."""
    s = good_summary()
    s["nodes"] += [{"node_id": "ft", "type": "tf-finetune", "status": "succeeded", "usd": 0.0, "error": None},
                   {"node_id": "ev", "type": "judge-eval", "status": "succeeded", "usd": 0.0, "error": None}]
    s["artifacts"] += [{"id": f"{i}-{n}", "node_id": i, "name": n, "kind": "metrics", "uri": "r2://b/x", "download_url": "/d", "meta": {}}
                       for i, n in (("ft", "job"), ("ft", "lora_adapter"), ("ft", "cost_json"), ("ev", "cost_json"))]
    problems = e2e.check_run(s)
    assert len(problems) == 1 and "judge-eval 'ev'" in problems[0] and "eval_summary" in problems[0], problems
    s["artifacts"] = [a for a in s["artifacts"] if a["name"] != "lora_adapter"]
    assert any("tf-finetune 'ft'" in p and "lora_adapter" in p for p in e2e.check_run(s))
