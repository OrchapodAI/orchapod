"""Unit tests for containers/tf-finetune/run.py (docs/contracts.md "ML nodes → tf-finetune")."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from orchapod.prices import PRICES
from packages.workflow_schema.models import NODE_REGISTRY, NodeType, TFFinetuneInputs, TFFinetuneOutputs

from .conftest import load_container

ft = load_container("tf-finetune")

LLAMA = "meta-llama/Llama-3.1-8B-Instruct"
TRAIN, EVAL = "r2://orchapod-artifacts/runs/r1/prep/train_jsonl", "r2://orchapod-artifacts/runs/r1/prep/eval_jsonl"
ROW = '{"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]}\n'
JOB = "/v1/fine_tuning/jobs/ftjob-1"
SUFFIX = "run12345-finetune"
CKPTS = [
    {"id": "ftckpt-1", "step_number": 5, "metrics": {"train_loss": 1.2, "valid_loss": 0.9},
     "result_files": ["file-a", "file-b"]},
    {"id": "ftckpt-2", "step_number": 10, "metrics": {"train_loss": 0.8, "valid_loss": 1.1}, "result_files": ["file-c"]},
]


def job(status, **kw):
    return {"id": "ftjob-1", "object": "fine_tuning.job", "model": LLAMA, "status": status, "error": None, **kw}


def routes(**over):
    """A job that runs one poll, then succeeds; `over` replaces routes by name."""
    named = {
        "files": [{"id": "file-train"}, {"id": "file-eval"}],
        "create": job("validating_files"),
        "get": [job("running", trained_steps=5, total_steps=10),
                job("succeeded", trained_steps=10, total_steps=10, trained_tokens=4000)],
        "events": {"data": [{"created_at": 2, "level": "info", "message": "epoch 1 done"},
                            {"created_at": 1, "level": "warn", "message": "slow queue"}]},
        "cancel": job("cancelled", trained_tokens=1000),
        "list": {"data": []},
        **over,
    }
    return {
        ("POST", "/v1/files"): named["files"],
        ("POST", "/v1/fine_tuning/jobs"): named["create"],
        ("GET", "/v1/fine_tuning/jobs"): named["list"],
        ("GET", JOB): named["get"],
        ("GET", f"{JOB}/events"): named["events"],
        ("POST", f"{JOB}/cancel"): named["cancel"],
        ("GET", f"{JOB}/checkpoints"): {"data": CKPTS},
        ("GET", "/v1/files/file-a"): {"id": "file-a", "filename": "adapter_model.safetensors"},
        ("GET", "/v1/files/file-b"): {"id": "file-b", "filename": "../adapter_config.json"},
        ("GET", "/v1/files/file-a/content"): httpx.Response(200, content=b"weights"),
        ("GET", "/v1/files/file-b/content"): httpx.Response(200, content=b"{}"),
    }


@pytest.fixture
def node(mock_orchapod_io, monkeypatch, tmp_path, clock):
    """node(**inputs) runs main() with train/eval served from r2; returns ({name: (path, kind, metadata)}, metrics)."""
    for k, v in {"ORCHAPOD_RUN_ID": "run12345-abcd", "ORCHAPOD_NODE_ID": "finetune", "NEBIUS_API_KEY": "tf-key"}.items():
        monkeypatch.setenv(k, v)
    for k in ("STUB", "NEBIUS_BASE_URL", "ORCHAPOD_MAX_COST_USD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setitem(PRICES["token_factory_finetune"], LLAMA, 1e-6)
    monkeypatch.setattr(ft, "cost", MagicMock())
    (tmp_path / "out").mkdir()
    mock_orchapod_io.local_path.side_effect = lambda name: tmp_path / "out" / name
    files = {TRAIN: ROW * 3, EVAL: ROW}

    def download(uri, dest):
        path = Path(dest) / uri.rsplit("/", 1)[1]
        path.write_text(files[uri])
        return path

    mock_orchapod_io.download_input.side_effect = download

    def run(eval_text=None, **inputs):
        if eval_text is not None:
            files[EVAL] = eval_text
        mock_orchapod_io.write_output.reset_mock()
        mock_orchapod_io.write_metrics.reset_mock()
        mock_orchapod_io.read_inputs.return_value = {"train_data": TRAIN, **inputs}
        ft.main()
        outs = {c.args[0]: (Path(c.args[1]), c.kwargs["kind"], c.kwargs["metadata"])
                for c in mock_orchapod_io.write_output.call_args_list}
        return outs, mock_orchapod_io.write_metrics.call_args.args[0]

    return run


def last_error():
    return ft.log.error.call_args_list[-1].args[0]


def test_registry_row_and_defaults():
    row = NODE_REGISTRY[NodeType.TF_FINETUNE]
    assert (row["runtime"], row["inputs_schema"], row["outputs_schema"]) == ("api", TFFinetuneInputs, TFFinetuneOutputs)
    i = TFFinetuneInputs(train_data=TRAIN)
    assert (i.model, i.eval_data, i.n_epochs, i.hyperparameters, i.timeout_min) == (LLAMA, "", 2, {}, 60)
    assert set(TFFinetuneOutputs.model_fields) == {"job", "lora_adapter"}


def test_stub_writes_job_adapter_and_metrics(node, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.delenv("NEBIUS_API_KEY")
    outs, metrics = node()
    path, kind, meta = outs["job"]
    assert kind == "metrics" and json.loads(path.read_text()) == meta
    assert meta | {"job_id": None, "checkpoint_id": None} == {
        "job_id": None, "model": LLAMA, "status": "succeeded", "checkpoint_id": None, "checkpoint_step": 2,
        "train_loss": 0.5, "valid_loss": 0.5, "trained_tokens": 0}
    assert "-stub-" in meta["job_id"] and "-stub-" in meta["checkpoint_id"]
    adapter, kind, adapter_meta = outs["lora_adapter"]
    assert (kind, adapter_meta) == ("model", {"format": "peft", "base_model": LLAMA})
    assert [f.read_bytes()[:5] for f in adapter.iterdir()] == [b"stub-"]
    assert metrics["loss_curve"] == [{"step": 1, "train_loss": 1.0, "valid_loss": 1.0},
                                     {"step": 2, "train_loss": 0.5, "valid_loss": 0.5}]
    assert node()[0]["job"][2] == meta  # deterministic
    ft.cost.add.assert_not_called()  # 0 trained tokens, $0


def test_polls_every_15s_and_keeps_the_lowest_valid_loss(node, tf_routes, clock):
    seen = tf_routes(ft, routes())
    outs, metrics = node(eval_data=EVAL, hyperparameters={"lora_r": 16, "n_epochs": 3})

    assert b'filename="train.jsonl"' in seen[0].content and b'filename="eval.jsonl"' in seen[1].content
    assert json.loads(seen[2].content) == {
        "model": LLAMA, "training_file": "file-train", "validation_file": "file-eval",
        "hyperparameters": {"lora": True, "n_epochs": 3, "lora_r": 16}, "suffix": SUFFIX}
    assert clock == [15, 15]
    assert [(c.args, c.kwargs) for c in ft.log.progress.call_args_list] == [
        ((5, 10), {"extra": {"phase": "running"}}), ((10, 10), {"extra": {"phase": "succeeded"}})]
    assert [c.args[0] for c in ft.log.warn.call_args_list if "Token Factory:" in c.args[0]] == ["Token Factory: slow queue"]
    assert [c.args[0] for c in ft.log.info.call_args_list if "Token Factory:" in c.args[0]] == ["Token Factory: epoch 1 done"]

    path, _, meta = outs["job"]
    assert meta == {"job_id": "ftjob-1", "model": LLAMA, "status": "succeeded", "checkpoint_id": "ftckpt-1",
                    "checkpoint_step": 5, "train_loss": 1.2, "valid_loss": 0.9, "trained_tokens": 4000}
    adapter = outs["lora_adapter"][0]
    assert {f.name: f.read_bytes() for f in adapter.iterdir()} == {
        "adapter_model.safetensors": b"weights", "adapter_config.json": b"{}"}  # a remote name never leaves the dir
    assert metrics == {**meta, "wall_s": 30, "loss_curve": [{"step": 5, "train_loss": 1.2, "valid_loss": 0.9},
                                                           {"step": 10, "train_loss": 0.8, "valid_loss": 1.1}]}
    ft.cost.add.assert_called_once_with("token_factory", LLAMA, trained_tokens=4000)
    assert not any(r.url.path.endswith("/cancel") for r in seen)


@pytest.mark.parametrize("eval_data, eval_text", [("", None), (EVAL, ""), (EVAL, "\n")])
def test_no_eval_data_means_no_validation_file(node, tf_routes, eval_data, eval_text):
    seen = tf_routes(ft, routes())
    node(eval_text, eval_data=eval_data)
    assert [r.url.path for r in seen].count("/v1/files") == 1
    assert "validation_file" not in json.loads(seen[1].content)


def test_failed_job_exits_1_with_its_error_message(node, tf_routes):
    seen = tf_routes(ft, routes(get=job("failed", error={"code": "invalid_file", "message": "line 3: no assistant turn"})))
    with pytest.raises(SystemExit) as e:
        node()
    assert e.value.code == 1 and "line 3: no assistant turn" in last_error()
    assert not any(r.url.path.endswith("/cancel") for r in seen)
    assert "job" not in [c.args[0] for c in ft.io.write_output.call_args_list]


def test_timeout_cancels_the_job_and_bills_what_it_trained(node, tf_routes, clock):
    running = job("running", trained_steps=1, total_steps=10)
    seen = tf_routes(ft, routes(get=[running] * 5 + [job("succeeded", trained_tokens=4000)]))
    with pytest.raises(SystemExit) as e:
        node(timeout_min=1)
    assert e.value.code == 1 and "timeout" in last_error()
    assert clock == [15] * 5  # polled until past 60 s, never reaching the 6th answer
    assert [r.url.path for r in seen][-1] == f"{JOB}/cancel"
    ft.cost.add.assert_called_once_with("token_factory", LLAMA, trained_tokens=1000)


def test_sigterm_while_polling_cancels_the_job(node, tf_routes, monkeypatch):
    seen = tf_routes(ft, routes())

    def sigterm(_):
        raise SystemExit(143)  # what the SDK's SIGTERM handler raises

    monkeypatch.setattr(ft.time, "sleep", sigterm)
    with pytest.raises(SystemExit) as e:
        node()
    assert e.value.code == 143 and [r.url.path for r in seen][-1] == f"{JOB}/cancel"


@pytest.mark.parametrize("listed, found", [([job("running", suffix=SUFFIX)], True),
                                          ([job("cancelled", suffix=SUFFIX), job("running", suffix="other")], False)])
def test_lost_create_response_finds_the_job_by_suffix(node, tf_routes, listed, found):
    seen = tf_routes(ft, routes(create=httpx.Response(503), list={"data": listed}))
    if found:
        assert node()[0]["job"][2]["job_id"] == "ftjob-1"
    else:
        with pytest.raises(SystemExit):
            node()
        assert last_error().startswith("token_factory server 503")
    assert [r.method for r in seen if r.url.path == "/v1/fine_tuning/jobs"] == ["POST", "GET"]  # create is never re-sent


def test_transient_poll_failure_waits_for_the_next_poll(node, tf_routes, clock):
    tf_routes(ft, routes(get=[httpx.Response(503)] * 4 + [job("succeeded", trained_tokens=4000)]))
    assert node()[0]["job"][2]["status"] == "succeeded"
    assert [s for s in clock if s == 15] == [15, 15]  # the client's own backoff sleeps are shorter


def test_estimate_over_the_node_budget_fails_before_any_call(node, tf_routes, monkeypatch):
    monkeypatch.setitem(PRICES["token_factory_finetune"], LLAMA, 1e-3)
    monkeypatch.setenv("ORCHAPOD_MAX_COST_USD", "0.05")
    seen = tf_routes(ft, routes())
    with pytest.raises(SystemExit):
        node()  # ~65 tokens × 2 epochs × $0.001
    assert seen == [] and "ORCHAPOD_MAX_COST_USD" in last_error()
