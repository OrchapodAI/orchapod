"""Unit tests for containers/tf-deploy/run.py (docs/contracts.md "ML nodes → tf-deploy")."""

import json
from unittest.mock import MagicMock

import httpx
import pytest

from orchapod.prices import PRICES
from packages.workflow_schema.models import NODE_REGISTRY, NodeType, TFDeployInputs, TFDeployOutputs

from .conftest import load_container

dep = load_container("tf-deploy")

LLAMA = "meta-llama/Llama-3.1-8B-Instruct"
JOB = {"job_id": "ftjob-1", "model": LLAMA, "status": "succeeded", "checkpoint_id": "ftckpt-1", "checkpoint_step": 5,
       "train_loss": 1.2, "valid_loss": 0.9, "trained_tokens": 4000}
JOB_URI = "r2://orchapod-artifacts/runs/run12345/finetune/job"
SERVED = f"{LLAMA}-LoRa:orchapod-run12345-AbCd"  # Token Factory may serve it under another name than requested
REF = {"base_url": "https://api.tokenfactory.nebius.com/v1", "model": SERVED, "api_key_env": "NEBIUS_API_KEY",
       "base_model": LLAMA}


def lora(status):
    return {"name": SERVED, "base_model": LLAMA, "status": status}


def routes(**over):
    """Deploy → one `validating` poll → `active` → the proving chat; `over` replaces routes by name."""
    named = {
        "deploy": lora("validating"),
        "status": [lora("validating"), lora("active")],
        "chat": {"model": SERVED, "usage": {"prompt_tokens": 20, "completion_tokens": 16}, "choices": [
            {"index": 0, "finish_reason": "length", "message": {"role": "assistant", "content": "Hello! I can help"}}]},
        **over,
    }
    return {
        ("POST", "/v0/models"): named["deploy"],
        ("GET", f"/v0/models/{SERVED}"): named["status"],
        ("DELETE", f"/v0/models/{SERVED}"): {},
        ("POST", "/v1/chat/completions"): named["chat"],
    }


@pytest.fixture
def node(mock_orchapod_io, monkeypatch, tmp_path, clock):
    """node(**inputs) runs main(); the job artifact is served from r2. Returns ({name: (path, kind, metadata)}, metrics)."""
    for k, v in {"ORCHAPOD_RUN_ID": "run12345-abcd", "ORCHAPOD_NODE_ID": "deploy", "NEBIUS_API_KEY": "tf-key"}.items():
        monkeypatch.setenv(k, v)
    for k in ("STUB", "NEBIUS_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setitem(PRICES["token_factory"], LLAMA, {"in": 0.02, "out": 0.06})  # a LoRA is priced as its base
    monkeypatch.setattr(dep, "cost", MagicMock())
    (tmp_path / "r2").mkdir()
    (tmp_path / "r2" / "job").write_text(json.dumps(JOB))
    mock_orchapod_io.download_input.side_effect = lambda uri: tmp_path / "r2" / uri.rsplit("/", 1)[1]
    mock_orchapod_io.local_path.side_effect = lambda name: tmp_path / name

    def run(**inputs):
        mock_orchapod_io.write_output.reset_mock()
        mock_orchapod_io.read_inputs.return_value = inputs
        dep.main()
        outs = {c.args[0]: (c.args[1], c.kwargs["kind"], c.kwargs["metadata"])
                for c in mock_orchapod_io.write_output.call_args_list}
        return outs, mock_orchapod_io.write_metrics.call_args.args[0]

    return run


def last_error():
    return dep.log.error.call_args_list[-1].args[0]


def test_registry_row_and_defaults():
    row = NODE_REGISTRY[NodeType.TF_DEPLOY]
    assert (row["runtime"], row["inputs_schema"], row["outputs_schema"]) == ("api", TFDeployInputs, TFDeployOutputs)
    assert TFDeployInputs(job=JOB_URI).name is None and TFDeployInputs(job=JOB).job == JOB
    assert set(TFDeployOutputs.model_fields) == {"model_ref"}


@pytest.mark.parametrize("job", [JOB_URI, JOB, json.dumps(JOB)], ids=["r2", "inline", "json-string"])
def test_deploys_waits_for_active_and_proves_it(node, tf_routes, clock, job):
    seen = tf_routes(dep, routes())
    outs, metrics = node(job=job)

    assert json.loads(seen[0].content) == {"name": "orchapod-run12345", "base_model": LLAMA, "source": "ftjob-1:ftckpt-1"}
    path, kind, meta = outs["model_ref"]
    assert (json.loads(path.read_text()), kind, meta) == (REF, "model", {**REF, "proof": "Hello! I can help"})
    chat = json.loads(seen[-1].content)
    assert (seen[-1].url.path, chat["model"], chat["max_tokens"]) == ("/v1/chat/completions", SERVED, 16)
    assert clock == [15] and [c.kwargs["extra"] for c in dep.log.progress.call_args_list] == [{"phase": "validating"}]
    assert "DELETE" not in [r.method for r in seen]  # idle costs nothing, so it stays up
    assert dep.cost.add.call_args.args[:4] == ("token_factory", SERVED, 20, 16)  # the proving call is billed
    assert (metrics["model"], metrics["base_model"], metrics["wait_s"]) == (SERVED, LLAMA, 15)


def test_name_input_is_the_requested_deployment_name(node, tf_routes):
    seen = tf_routes(dep, routes())
    node(job=JOB, name="realestate-lora")
    assert json.loads(seen[0].content)["name"] == "realestate-lora"


@pytest.mark.parametrize("status", [400, 404, 405, 422])
def test_no_per_token_lora_points_at_vllm_serve(node, tf_routes, status):
    seen = tf_routes(dep, routes(deploy=httpx.Response(status, json={"detail": "Not Found"})))
    with pytest.raises(SystemExit) as e:
        node(job=JOB)
    assert e.value.code == 1 and last_error().endswith("serve it with vllm-serve + lora_adapter")
    assert "token_factory unsupported" in last_error()
    assert [r.method for r in seen] == ["POST"]  # deletes nothing it did not create


@pytest.mark.parametrize("over, why", [
    ({"status": [lora("validating"), lora("error")]}, "is error after 15 s"),  # at once, not at the 15-min cap
    ({"status": [lora("validating")] * 62 + [lora("active")]}, "after 915 s"),  # not active within 15 min
    ({"chat": httpx.Response(400, json={"error": "bad"})}, "token_factory bad_request 400"),
], ids=["error", "timeout", "proof-fails"])
def test_failure_after_deploy_deletes_it(node, tf_routes, over, why):
    seen = tf_routes(dep, routes(**over))
    with pytest.raises(SystemExit) as e:
        node(job=JOB)
    assert e.value.code == 1 and why in last_error()
    assert (seen[-1].method, seen[-1].url.path) == ("DELETE", f"/v0/models/{SERVED}")
    assert dep.io.write_output.call_count == 0


@pytest.mark.parametrize("job", ["${{ nodes.finetune.outputs.job }}", "[1, 2]", {"job_id": "ftjob-1"}])
def test_unusable_job_input_fails_before_any_call(node, tf_routes, job):
    seen = tf_routes(dep, routes())
    with pytest.raises(SystemExit) as e:
        node(job=job)
    assert e.value.code == 1 and seen == [] and "tf-finetune's job output" in last_error()


def test_unpriced_base_fails_before_deploying(node, tf_routes, monkeypatch):
    monkeypatch.delitem(PRICES["token_factory"], LLAMA)
    seen = tf_routes(dep, routes())
    with pytest.raises(SystemExit) as e:
        node(job=JOB)
    assert e.value.code == 1 and seen == [] and f"no price for {LLAMA}" in last_error()


def test_stub_deploys_offline(node, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.delenv("NEBIUS_API_KEY")
    monkeypatch.delitem(PRICES["token_factory"], LLAMA)  # nothing is spent, so STUB needs no price
    outs, _ = node(job=JOB)
    meta = outs["model_ref"][2]
    assert (meta["model"], meta["base_model"]) == ("orchapod-run12345", LLAMA) and meta["proof"].startswith("stub-")
    assert node(job=JOB)[0]["model_ref"][2] == meta  # deterministic
