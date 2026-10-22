"""Unit tests for containers/quantize/run.py (docs/contracts.md "ML nodes → quantize")."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from packages.workflow_schema.models import QuantizeInputs, QuantizeOutputs

from .conftest import load_container

q = load_container("quantize")

HF_MODEL = "r2://orchapod-artifacts/runs/r1/download/hf_model"
LORA = "r2://orchapod-artifacts/runs/r1/train/lora_adapter"


@pytest.fixture
def node(mock_orchapod_io, monkeypatch, tmp_path):
    """node(**inputs) runs main(); returns ({name: (path, kind, metadata)}, metrics). Subprocesses are recorded in
    node.argv; the fake convert/quantize/convert-lora write files of 300, 100 and 50 bytes."""
    monkeypatch.setattr(q, "WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(q, "LLAMA_CPP_DIR", Path("/llama"))
    monkeypatch.delenv("STUB", raising=False)
    mock_orchapod_io.download_directory.side_effect = lambda uri, dest: Path(dest)
    argv, codes = [], []

    def subprocess_run(cmd):
        argv.append(cmd)
        out = cmd[cmd.index("--outfile") + 1] if "--outfile" in cmd else cmd[-2]
        Path(out).write_bytes(b"GGUF" + b"\0" * (46 if cmd[1].endswith("convert_lora_to_gguf.py") else 296 if "--outfile" in cmd else 96))
        return type("Done", (), {"returncode": codes.pop(0) if codes else 0})

    monkeypatch.setattr(q.subprocess, "run", subprocess_run)

    def run(**inputs):
        mock_orchapod_io.read_inputs.return_value = {"model": HF_MODEL, "method": "gguf", **inputs}
        q.main()
        outs = {c.args[0]: (Path(c.args[1]), c.kwargs["kind"], c.kwargs["metadata"])
                for c in mock_orchapod_io.write_output.call_args_list}
        return outs, mock_orchapod_io.write_metrics.call_args.args[0]

    run.argv, run.codes = argv, codes
    return run


def test_schema_has_keep_f16_and_no_token():
    assert set(QuantizeInputs.model_fields) == {"model", "method", "precision", "bits", "keep_f16", "lora_adapter"}
    assert QuantizeInputs(model="x", method="gguf").keep_f16 is False
    assert QuantizeInputs(model="x", method="gguf").lora_adapter is None
    assert set(QuantizeOutputs.model_fields) == {"gguf_file", "gguf_f16", "gguf_lora", "awq_model"}


def test_gguf_converts_to_f16_then_quantizes_and_keeps_f16(node, mock_orchapod_io, tmp_path):
    outs, metrics = node(keep_f16=True)
    mock_orchapod_io.download_directory.assert_called_once_with(HF_MODEL, tmp_path / "model")  # a dir, not one object
    convert, quantize = node.argv
    assert convert[1:] == ["/llama/convert_hf_to_gguf.py", str(tmp_path / "model"), "--outfile",
                           str(tmp_path / "model-f16.gguf"), "--outtype", "f16"]
    assert quantize == ["/llama/llama-quantize", str(tmp_path / "model-f16.gguf"), str(tmp_path / "model-q4_k_m.gguf"),
                        "Q4_K_M"]
    assert outs["gguf_file"][1:] == ("model", {"format": "gguf", "precision": "q4_k_m", "base_model": HF_MODEL,
                                               "size_bytes": 100})
    assert outs["gguf_f16"][1:] == ("model", {"format": "gguf", "precision": "f16", "base_model": HF_MODEL,
                                              "size_bytes": 300})
    assert metrics == {"method": "gguf", "precision": "q4_k_m", "size_bytes": 100, "f16_size_bytes": 300, "wall_s": 0}


def test_an_hf_model_from_hf_download_is_named_by_its_hub_id(node, mock_orchapod_io):
    def download(uri, dest):
        Path(dest).mkdir(parents=True)
        (Path(dest) / "orchapod_source.json").write_text(json.dumps({"model_id": "Qwen/Qwen2.5-Math-1.5B-Instruct"}))
        return Path(dest)

    mock_orchapod_io.download_directory.side_effect = download
    outs, _ = node(keep_f16=True)
    assert {outs[n][2]["base_model"] for n in ("gguf_file", "gguf_f16")} == {"Qwen/Qwen2.5-Math-1.5B-Instruct"}


def test_without_keep_f16_only_the_quantized_file_is_written(node):
    outs, _ = node(precision="q8_0")
    assert set(outs) == {"gguf_file"} and node.argv[1][-1] == "Q8_0"


def test_a_hugging_face_id_is_downloaded_from_the_hub(node, tmp_path):
    with patch("huggingface_hub.snapshot_download") as dl:
        outs, _ = node(model="hf://Qwen/Qwen2.5-Math-1.5B-Instruct")
    assert dl.call_args.args == ("Qwen/Qwen2.5-Math-1.5B-Instruct",)
    assert dl.call_args.kwargs["local_dir"] == tmp_path / "model"
    assert outs["gguf_file"][2]["base_model"] == "hf://Qwen/Qwen2.5-Math-1.5B-Instruct"


def test_a_failed_conversion_exits_1(node):
    node.codes.append(2)
    with pytest.raises(SystemExit) as e:
        node()
    assert e.value.code == 1 and q.log.error.call_args.args[0].startswith("convert failed (exit 2)")
    assert len(node.argv) == 1  # nothing is quantized after a failed conversion


@pytest.mark.parametrize("inputs, error", [
    ({"method": "awq"}, "AWQ needs a GPU job; use gguf"),
    ({"model": "${{ nodes.download.outputs.hf_model }}"}, "unresolved ref model"),
    ({"precision": "q2_k"}, "precision"),
    ({"lora_adapter": "${{ nodes.train.outputs.lora_adapter }}"}, "unresolved ref lora_adapter"),
])
def test_refused_before_any_download(node, mock_orchapod_io, inputs, error):
    with pytest.raises(SystemExit) as e:
        node(**inputs)
    assert e.value.code == 1 and error in q.log.error.call_args.args[0]
    mock_orchapod_io.download_directory.assert_not_called()
    assert node.argv == []


def test_stub_writes_four_byte_gguf_files_offline(node, mock_orchapod_io, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    outs, metrics = node(keep_f16=True, lora_adapter=LORA)
    assert {n: p.read_bytes() for n, (p, _, _) in outs.items()} == {"gguf_file": b"GGUF", "gguf_f16": b"GGUF",
                                                                     "gguf_lora": b"GGUF"}
    assert (metrics["size_bytes"], metrics["f16_size_bytes"], metrics["lora_size_bytes"]) == (4, 4, 4)
    assert node.argv == [] and not mock_orchapod_io.download_directory.called


def peft_dir(uri, dest):
    """io.download_directory: the adapter's dir holds a PEFT config; the model's is empty."""
    Path(dest).mkdir(parents=True, exist_ok=True)
    if uri == LORA:
        (Path(dest) / "adapter_config.json").write_text(json.dumps({"peft_type": "LORA", "r": 16, "lora_alpha": 16}))
    return Path(dest)


def test_a_lora_adapter_becomes_a_gguf_lora_against_the_models_config(node, mock_orchapod_io, tmp_path):
    """The CPU fallback (R24): judge-eval serves the base GGUF with this adapter (llama-server --lora). The adapter is
    fetched and checked first (a few MB), before the multi-GB model; Token Factory's unprefixed tensor names and PEFT's
    prefixed ones convert alike (llama.cpp b11223, checked on a real model)."""
    mock_orchapod_io.download_directory.side_effect = peft_dir
    outs, metrics = node(lora_adapter=LORA)
    assert [c.args for c in mock_orchapod_io.download_directory.call_args_list] == [
        (LORA, tmp_path / "lora"), (HF_MODEL, tmp_path / "model")]
    lora, convert, quantize = node.argv
    assert lora[1:] == ["/llama/convert_lora_to_gguf.py", str(tmp_path / "lora"), "--base", str(tmp_path / "model"),
                        "--outfile", str(tmp_path / "lora.gguf"), "--outtype", "f32"]
    assert convert[1] == "/llama/convert_hf_to_gguf.py" and quantize[0] == "/llama/llama-quantize"
    assert outs["gguf_lora"] == (tmp_path / "lora.gguf", "model", {"format": "gguf", "base_model": HF_MODEL, "type": "lora",
                                                                   "precision": "f32", "size_bytes": 50})
    assert set(outs) == {"gguf_file", "gguf_lora"} and metrics["lora_size_bytes"] == 50


def test_an_adapter_without_its_peft_config_exits_1_before_the_model_download(node, mock_orchapod_io, tmp_path):
    """tf-finetune leaves lora_adapter empty when the best checkpoint has no result_files (R19)."""
    mock_orchapod_io.download_directory.side_effect = peft_dir
    with pytest.raises(SystemExit) as e:
        node(lora_adapter=LORA.replace("train", "empty"))
    assert e.value.code == 1 and "no adapter_config.json" in q.log.error.call_args.args[0]
    assert mock_orchapod_io.download_directory.call_count == 1 and node.argv == []
