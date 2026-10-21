"""scripts/e2e_demo.py: the logic around the stub e2e. The run itself is `make check`'s last step (needs Docker and `make up`)."""

import copy
import importlib.util
import json
import socket
from pathlib import Path
from typing import Literal

import pytest
import yaml
from pydantic import BaseModel, model_validator

from api.executor.dag import compile_dag

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("e2e_demo", ROOT / "scripts" / "e2e_demo.py")
e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e2e)

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


def test_plan_yaml_is_a_workflow_the_api_compiles():
    dag = compile_dag(e2e.plan_yaml(INTENT2["plan"]), {})
    assert [n.id for n in dag.topological_order()] == ["synth", "prep"]
    assert dag.nodes["synth"].inputs["row_schema"] == ROW_SCHEMA
    assert dag.nodes["prep"].inputs["dataset"] == "${{ nodes.synth.outputs.dataset }}"


def test_structured_supported_follows_the_synth_schema(monkeypatch):
    from packages.workflow_schema import models

    class Merged(BaseModel):
        pipeline_template: Literal["self-instruct", "structured"] = "self-instruct"
        row_schema: dict | str | None = None
        n_samples: int = 10

        @model_validator(mode="after")
        def _needs_schema(self):
            if self.pipeline_template == "structured" and not self.row_schema:
                raise ValueError("structured needs row_schema")
            return self

    class Old(BaseModel):
        pipeline_template: Literal["self-instruct", "magpie"] = "self-instruct"

    monkeypatch.setattr(models, "SynthDistilabelInputs", Old)
    assert not e2e.structured_supported()
    monkeypatch.setattr(models, "SynthDistilabelInputs", Merged)
    assert e2e.structured_supported()  # the probe brings its own row_schema
    assert e2e.structured_supported({"pipeline_template": "structured", "n_samples": "x"})  # a bad input is not "unmerged"


def test_skip_reasons_name_each_missing_prerequisite():
    assert e2e.skip_reasons(True, True) == []
    assert "backend-w2" in e2e.skip_reasons(False, True)[0] and "/agent/templates" in e2e.skip_reasons(False, True)[0]
    assert "data-w2" in e2e.skip_reasons(True, False)[0] and "structured" in e2e.skip_reasons(True, False)[0]
    assert len(e2e.skip_reasons(False, False)) == 2


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


TEMPLATE_FILES = sorted((ROOT / "apps/api/agent/templates").glob("*.json"))
NO_TEMPLATES = "backend-w2 has not merged apps/api/agent/templates/*.json yet; this guard switches on when it does"


@pytest.mark.skipif(not TEMPLATE_FILES, reason=NO_TEMPLATES)
def test_exactly_one_shipped_template_is_intent2():
    found = [t for t in e2e.templates_on_disk() if e2e.find_intent2([t])]
    assert len(found) == 1, "the e2e would SKIP or pick the wrong plan"


@pytest.mark.skipif(not TEMPLATE_FILES, reason=NO_TEMPLATES)
def test_the_intent2_template_runs_on_the_nodes_that_exist():
    from packages.workflow_schema.models import NODE_REGISTRY, NodeType

    plan = e2e.plan_of(e2e.find_intent2(e2e.templates_on_disk()))
    compile_dag(e2e.plan_yaml(plan), {})
    for node in plan["nodes"]:
        assert (ROOT / "containers" / node["type"] / "Dockerfile").exists(), node
        assert NODE_REGISTRY[NodeType(node["type"])]["runtime"] in ("cpu", "api"), node  # LocalDocker runs these
    assert yaml.safe_load(e2e.plan_yaml(plan)) == copy.deepcopy(plan)
