"""scripts/e2e_demo.py: the logic around the stub e2e. The run itself is `make check E2E=1` (needs Docker and `make up`)."""

import copy
import json
import socket
import subprocess
from pathlib import Path

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

    def refuse(*args):
        asked.append(args)
        raise RuntimeError("stop here")

    monkeypatch.setattr(e2e, "listen_on_free_port", refuse)
    with pytest.raises(RuntimeError, match="stop here"):
        e2e.start_api(Path("/nonexistent"))
    assert asked == [()], "start_api asks for the default start, not a port of its own"


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


def test_poll_run_cancels_a_run_that_outlives_the_limit(monkeypatch):
    seen = []

    def api(request):
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"status": "running", "nodes": [{"node_id": "a", "status": "running"}]})

    monkeypatch.setattr(e2e, "LIMIT_S", 0)
    reply, _ = e2e.poll_run(httpx.Client(base_url="http://api", transport=httpx.MockTransport(api)), "r1", "/runs/r1/summary")
    assert reply["status"] == "running"
    assert seen == [("GET", "/runs/r1/summary"), ("POST", "/runs/r1/cancel")]


def test_poll_run_ends_when_the_done_test_says_so(monkeypatch):
    replies = iter([{"status": "succeeded", "ready": False, "nodes": []}, {"status": "succeeded", "ready": True, "nodes": []}])
    monkeypatch.setattr(e2e.time, "sleep", lambda s: None)
    c = httpx.Client(base_url="http://api", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=next(replies))))
    reply, _ = e2e.poll_run(c, "r1", "/agent/runs/r1/report", done=lambda r: r["ready"])  # terminal is not enough
    assert reply["ready"] is True


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
