"""Unit tests for containers/vllm-serve/run.py (docs/contracts.md "ML nodes → vllm-serve", "ModelRef", R10, R11)."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from packages.providers.base import ProviderError
from packages.providers.tokenfactory import TokenFactory
from packages.workflow_schema.models import NODE_REGISTRY, NodeType, VLLMServeInputs, VLLMServeOutputs

from .conftest import load_container

vs = load_container("vllm-serve")

BASE = "meta-llama/Llama-3.1-8B-Instruct"
ADAPTER = "r2://orchapod-artifacts/runs/r1/finetune/lora_adapter"
MERGED = "r2://orchapod-artifacts/runs/r1/train/merged_model"
URL = "https://ep-1.serverless.example"
TOKEN = "endpoint-token"
NAME = "orchapod-12345678-serve-8b"  # run 1234567890ab, node serve_8b
CREATE_S = 5  # a create takes a moment, and spend counts from just before it


class Endpoints:
    """A fake NebiusServerless().endpoints. `ops` records find, create and delete in order. create notes the WARN lines
    logged before it, takes CREATE_S and raises `create_error` when set. get walks `states` and find walks `finds`, each
    then staying on its last item (find: None when empty)."""

    def __init__(self, states=("PROVISIONING", "STARTING", "RUNNING")):
        self.states, self.finds, self.create_error = list(states), [], None
        self.ops, self.created, self.deleted = [], [], []

    def find(self, name):
        self.ops.append(("find", name))
        return self.finds.pop(0) if len(self.finds) > 1 else next(iter(self.finds), None)

    def create(self, name, image, **kw):
        self.ops.append(("create", name))
        self.created.append({"name": name, "image": image, "warned": [c.args[0] for c in vs.log.warn.call_args_list],
                             **kw})
        time.sleep(CREATE_S)
        if self.create_error:
            raise self.create_error
        return "ep-1"

    def get(self, eid):
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"id": eid, "state": state, "url": URL if state == "RUNNING" else None, "code": "", "message": ""}

    def delete(self, eid):
        self.ops.append(("delete", eid))
        self.deleted.append(eid)


def listed(eid, state):
    """find()'s view of an endpoint named NAME."""
    return {"id": eid, "name": NAME, "state": state, "url": None, "code": None, "message": None}


@pytest.fixture
def node(mock_orchapod_io, monkeypatch, tmp_path, clock):
    """node(**inputs) runs main() against fake endpoints and a fake vLLM; returns {output: (ref, metadata)}.
    node.eps is the fake client, node.seen the requests vLLM got, node.answers the replies it gives in turn."""
    for k in ("STUB", "ORCHAPOD_MAX_COST_USD", "HF_TOKEN", "ORCHAPOD_R2_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ORCHAPOD_ENDPOINT_TOKEN", TOKEN)
    monkeypatch.setenv("ORCHAPOD_CONTROL_URL", "http://api:8001")
    monkeypatch.setenv("ORCHAPOD_RUN_ID", "1234567890ab")
    monkeypatch.setenv("ORCHAPOD_NODE_ID", "serve_8b")
    monkeypatch.setattr(vs, "cost", MagicMock(BudgetExceeded=RuntimeError))
    mock_orchapod_io.local_path.side_effect = lambda name: tmp_path / name
    eps, seen, answers = Endpoints(), [], []

    def vllm(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if answers:
            return answers.pop(0)
        return httpx.Response(200, json={"choices": [{"index": 0, "finish_reason": "stop",
                                                      "message": {"role": "assistant", "content": "I can help."}}]})

    http = httpx.Client(transport=httpx.MockTransport(vllm))
    monkeypatch.setattr(vs, "TokenFactory", lambda **kw: TokenFactory(http=http, **kw))
    monkeypatch.setattr(vs, "endpoints", lambda: run.eps)

    def run(**inputs):
        mock_orchapod_io.read_inputs.return_value = {"model": BASE, "lora_adapter": ADAPTER, **inputs}
        vs.main()
        return {c.args[0]: (json.loads(Path(c.args[1]).read_text()), c.kwargs["metadata"])
                for c in mock_orchapod_io.write_output.call_args_list}

    run.eps, run.seen, run.answers = eps, seen, answers
    return run


def ttl_posts():
    return [c.args for c in vs.log.post.call_args_list if c.args[0] == "/internal/ttl"]


def test_registry_row_is_an_api_node_with_model_refs():
    meta = NODE_REGISTRY[NodeType.VLLM_SERVE]
    assert (meta["runtime"], meta.get("long_running"), meta["rents_gpu"]) == ("api", None, True)
    assert set(VLLMServeInputs.model_fields) == {"model", "lora_adapter", "max_model_len", "keep_alive_min",
                                                 "served_model_name", "gpu_memory_utilization", "dtype", "platform",
                                                 "preset"}  # no hf_token: HF_TOKEN is env only
    i = VLLMServeInputs(model=BASE)
    assert (i.keep_alive_min, i.platform, i.preset, i.lora_adapter) == (30, "gpu-l40s-a", "1gpu-8vcpu-32gb", None)
    with pytest.raises(ValueError):
        VLLMServeInputs(model=BASE, keep_alive_min=121)
    assert set(VLLMServeOutputs.model_fields) == {"model_ref", "base_model_ref"}


def test_base_and_adapter_share_one_endpoint_and_the_refs_name_the_token_env_var(node, mock_orchapod_io):
    out = node()
    (create,) = node.eps.created
    assert (create["name"], create["image"], create["platform"], create["preset"], create["port"]) == (
        NAME, "vllm/vllm-openai:v0.18.0-cu130", "gpu-l40s-a", "1gpu-8vcpu-32gb", 8000)
    assert node.eps.ops[:2] == [("find", NAME), ("create", NAME)]  # R19: a leftover would hold the name
    assert any(NAME in line and "Nebius console" in line for line in create["warned"])  # before a SIGTERM can cut it
    assert create["args"].split() == [
        BASE, "--served-model-name", BASE, "--port", "8000", "--max-model-len", "8192", "--dtype", "bfloat16",
        "--gpu-memory-utilization", "0.9", "--enable-lora", "--lora-modules",
        "tuned=/mnt/artifacts/runs/r1/finetune/lora_adapter", "--max-lora-rank", "64"]
    assert create["auth_token"] == TOKEN and create["volumes"] == ("s3://orchapod-artifacts:/mnt/artifacts:ro",)
    (smoke,) = node.seen  # one completion proves the adapter loaded
    assert str(smoke.url) == f"{URL}/v1/chat/completions" and smoke.headers["authorization"] == f"Bearer {TOKEN}"
    assert json.loads(smoke.content)["model"] == "tuned"
    assert ttl_posts() == [("/internal/ttl", {"action": "register_ttl", "keep_alive_min": 30, "endpoint_url": URL,
                                              "endpoint_id": "ep-1"})]
    assert [c.kwargs for c in vs.log.post.call_args_list] == [{"timeout": 30}]  # the SDK's 3 s would delete it
    ref, meta = out["model_ref"]
    assert ref == {"base_url": f"{URL}/v1", "model": "tuned", "api_key_env": "ORCHAPOD_ENDPOINT_TOKEN", "base_model": BASE}
    assert meta["endpoint_id"] == "ep-1" and meta["expires_at"] and meta["proof"] == "I can help."
    assert out["base_model_ref"][0] == {**ref, "model": BASE, "base_model": None}
    written = json.dumps([out, mock_orchapod_io.write_metrics.call_args.args])
    assert TOKEN not in written  # R10/R21: the env var's name, never its value
    assert node.eps.deleted == []  # registered: the backend deletes it at expiry
    (bill,) = vs.cost.add.call_args_list
    assert bill.args == ("nebius_serverless", "gpu-l40s-a/1gpu-8vcpu-32gb")
    # from just before the create: the create, 2 polls of 15 s, then 30 min
    assert bill.kwargs["gpu_hours"] == pytest.approx((CREATE_S + 30) / 3600 + 0.5, abs=1e-4)


def test_a_merged_model_dir_is_served_from_the_bucket_as_tuned(node, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    out = node(model=MERGED, lora_adapter=None)
    (create,) = node.eps.created
    assert create["args"].split()[:3] == ["/mnt/artifacts/runs/r1/train/merged_model", "--served-model-name", "tuned"]
    assert "--enable-lora" not in create["args"] and create["env"] == {}  # no Hub download, so no HF_TOKEN
    assert set(out) == {"model_ref"} and out["model_ref"][0]["base_model"] is None


def test_a_gated_hf_base_gets_hf_token_in_the_endpoint_env(node, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf-secret")
    node(lora_adapter=None, keep_alive_min=10)
    (create,) = node.eps.created
    assert create["env"] == {"HF_TOKEN": "hf-secret"} and create["volumes"] == ()


@pytest.mark.parametrize("break_it, error", [
    (lambda n: setattr(n.eps, "states", ["PROVISIONING", "ERROR"]), "endpoint ep-1 is ERROR after 20 s"),  # at once
    (lambda n: setattr(n.eps, "states", ["STARTING"]), "endpoint ep-1 is STARTING after"),  # never Running in 15 min
    (lambda n: n.answers.append(httpx.Response(404, json={"error": "model tuned not found"})), "did not answer"),
    (lambda n: setattr(vs.log.post, "side_effect", OSError("connection refused")), "could not register"),
], ids=["error-state", "timeout", "adapter-not-loaded", "ttl-refused"])
def test_a_failure_before_registration_deletes_the_endpoint(node, break_it, error):
    break_it(node)
    with pytest.raises(SystemExit) as e:
        node()
    assert e.value.code == 1 and error in vs.log.error.call_args_list[0].args[0]
    assert node.eps.deleted == ["ep-1"]
    assert vs.cost.add.call_args.kwargs["gpu_hours"] < 0.3  # the time it ran, not keep_alive_min


def test_a_cancel_while_starting_deletes_the_endpoint(node, monkeypatch):
    def sigterm(*a, **k):
        raise SystemExit(143)  # the SDK's SIGTERM handler

    monkeypatch.setattr(vs.log, "progress", sigterm)
    with pytest.raises(SystemExit) as e:
        node()
    assert e.value.code == 143 and node.eps.deleted == ["ep-1"] and ttl_posts() == []


@pytest.mark.parametrize("error, code", [
    (ProviderError("nebius_serverless", "server", 504, "deadline exceeded"), 1),
    (ProviderError("nebius_serverless", "bad_output", 200, f"endpoints create {NAME}: no resourceId"), 1),
    (SystemExit(143), 143),  # SIGTERM during the create's read: the SDK raises it there
], ids=["5xx", "no-id", "sigterm"])
def test_a_create_that_may_have_landed_is_found_by_name_and_deleted(node, error, code):
    node.eps.create_error, node.eps.finds = error, [None, listed("ep-lost", "PROVISIONING")]
    with pytest.raises(SystemExit) as e:
        node()
    assert e.value.code == code
    assert node.eps.ops == [("find", NAME), ("create", NAME), ("find", NAME), ("delete", "ep-lost")]
    assert vs.cost.add.call_args.kwargs["gpu_hours"] == pytest.approx(CREATE_S / 3600, abs=1e-4)  # from the create
    assert ttl_posts() == [] and node.seen == []
    if code == 1:
        assert vs.log.error.call_args_list[0].args[0] == str(error)


def test_a_lost_create_that_find_misses_is_named_for_the_console(node):
    node.eps.create_error = ProviderError("nebius_serverless", "server", 504, "deadline exceeded")
    with pytest.raises(SystemExit):
        node()
    assert node.eps.ops == [("find", NAME), ("create", NAME), ("find", NAME)] and not vs.cost.add.called
    assert NAME in vs.log.error.call_args.args[0] and "Nebius console" in vs.log.error.call_args.args[0]


@pytest.mark.parametrize("kind, status", [("bad_request", 409), ("auth", 401), ("quota", 402), ("rate_limit", 429)])
def test_a_refused_create_looks_nothing_up(node, kind, status):
    node.eps.create_error = ProviderError("nebius_serverless", kind, status, "refused")
    with pytest.raises(SystemExit) as e:
        node()
    assert e.value.code == 1 and node.eps.ops == [("find", NAME), ("create", NAME)] and not vs.cost.add.called


@pytest.mark.parametrize("state, deleted", [("RUNNING", True), ("ERROR", True), ("DELETING", False)])
def test_an_endpoint_left_by_an_earlier_attempt_is_deleted_and_a_fresh_one_created(node, state, deleted):
    node.eps.finds = [listed("ep-old", state), listed("ep-old", "DELETING"), None]
    out = node()
    assert node.eps.ops == ([("find", NAME)] + [("delete", "ep-old")] * deleted
                            + [("find", NAME), ("find", NAME), ("create", NAME)])  # waits until the name is free
    assert out["model_ref"][1]["endpoint_id"] == "ep-1"  # never adopted
    assert "ep-old" in vs.log.warn.call_args_list[0].args[0]


def test_a_leftover_still_listed_15_min_after_its_delete_fails_before_any_create(node):
    node.eps.finds = [listed("ep-old", "RUNNING")]
    with pytest.raises(SystemExit) as e:
        node()
    assert e.value.code == 1 and node.eps.created == [] and node.eps.deleted == ["ep-old"]
    assert "still listed" in vs.log.error.call_args.args[0] and not vs.cost.add.called


def test_vllm_still_loading_behind_a_running_endpoint_is_retried(node):
    node.answers += [httpx.Response(503, json={"error": "loading"})] * 4  # the client retries 3 times per call
    node()
    assert len(node.seen) == 5 and node.eps.deleted == []


@pytest.mark.parametrize("inputs, env, error", [
    ({"lora_adapter": "${{ nodes.finetune.outputs.lora_adapter }}"}, {}, "unresolved ref lora_adapter"),
    ({"keep_alive_min": 121}, {}, "keep_alive_min is 121"),
    ({}, {"ORCHAPOD_ENDPOINT_TOKEN": ""}, "set ORCHAPOD_ENDPOINT_TOKEN"),
    ({}, {"ORCHAPOD_CONTROL_URL": ""}, "ORCHAPOD_CONTROL_URL is required"),
    # billed from creation: up to 15 min to start + 30 min = $1.16 on an L40S, though 30 min alone is $0.78
    ({}, {"ORCHAPOD_MAX_COST_USD": "1.0"}, "costs up to $1.16, above this node's budget $1.00"),
    ({"platform": "gpu-b200"}, {}, "no price for gpu-b200"),
    ({"lora_adapter": "r2://someone-else/runs/r1/x/lora_adapter"}, {}, "the bucket the endpoint mounts"),
], ids=["unresolved", "keep-alive-cap", "no-token", "no-control-plane", "over-budget", "unpriced", "other-bucket"])
def test_refused_before_any_endpoint_is_created(node, monkeypatch, inputs, env, error):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(SystemExit) as e:
        node(**inputs)
    assert e.value.code == 1 and error in vs.log.error.call_args.args[0]
    assert node.eps.ops == [] and node.seen == []


def test_stub_registers_a_stub_endpoint_offline_so_compare_accepts_its_refs(node, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.delenv("ORCHAPOD_ENDPOINT_TOKEN")
    monkeypatch.setattr(vs, "endpoints", MagicMock(side_effect=AssertionError("no Nebius call under STUB")))
    out = node()
    assert ttl_posts() == [("/internal/ttl", {"action": "register_ttl", "keep_alive_min": 30,
                                              "endpoint_url": "http://stub.invalid",
                                              "endpoint_id": "stub-orchapod-12345678-serve-8b"})]
    assert out["model_ref"][0] == {"base_url": "http://stub.invalid/v1", "model": "tuned",
                                   "api_key_env": "ORCHAPOD_ENDPOINT_TOKEN", "base_model": BASE}
    assert out["base_model_ref"][0]["model"] == BASE and node.seen == [] and not vs.cost.add.called


def test_judge_eval_takes_its_model_ref_as_the_tuned_model_with_the_endpoint_token(node, mock_orchapod_io, tmp_path):
    """Lane B wiring (PLAN A2 D6): the artifact as vllm-serve writes it passes judge-eval's pairing rule."""
    je = load_container("judge-eval")
    ref, _ = node()["model_ref"]

    def download(uri, local_dir=None):
        (tmp_path / "dl").mkdir(exist_ok=True)
        (tmp_path / "dl" / "model_ref").write_text(json.dumps(ref))
        return tmp_path / "dl" / "model_ref"

    mock_orchapod_io.download_input.side_effect = download
    assert je.model_ref("tuned_model_ref", "r2://orchapod-artifacts/runs/r1/serve/model_ref") == ref
