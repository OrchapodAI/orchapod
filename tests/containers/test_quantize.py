"""Unit tests for containers/quantize/run.py (docs/contracts.md "ML nodes → quantize")."""

from pathlib import Path
from unittest.mock import patch

import pytest

from packages.workflow_schema.models import QuantizeInputs, QuantizeOutputs

from .conftest import load_container

q = load_container("quantize")

HF_MODEL = "r2://orchapod-artifacts/runs/r1/download/hf_model"


@pytest.fixture
def node(mock_orchapod_io, monkeypatch, tmp_path):
    """node(**inputs) runs main(); returns ({name: (path, kind, metadata)}, metrics). Subprocesses are recorded in
    node.argv; the fake convert/quantize write files of 300 and 100 bytes."""
    monkeypatch.setattr(q, "WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(q, "LLAMA_CPP_DIR", Path("/llama"))
    monkeypatch.delenv("STUB", raising=False)
    mock_orchapod_io.download_directory.side_effect = lambda uri, dest: Path(dest)
    argv, codes = [], []

    def subprocess_run(cmd):
        argv.append(cmd)
        out = cmd[cmd.index("--outfile") + 1] if "--outfile" in cmd else cmd[-2]
        Path(out).write_bytes(b"GGUF" + b"\0" * (296 if "--outfile" in cmd else 96))
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
    assert set(QuantizeInputs.model_fields) == {"model", "method", "precision", "bits", "keep_f16"}
    assert QuantizeInputs(model="x", method="gguf").keep_f16 is False
    assert set(QuantizeOutputs.model_fields) == {"gguf_file", "gguf_f16", "awq_model"}


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
])
def test_refused_before_any_download(node, mock_orchapod_io, inputs, error):
    with pytest.raises(SystemExit) as e:
        node(**inputs)
    assert e.value.code == 1 and error in q.log.error.call_args.args[0]
    mock_orchapod_io.download_directory.assert_not_called()
    assert node.argv == []


def test_stub_writes_four_byte_gguf_files_offline(node, mock_orchapod_io, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    outs, metrics = node(keep_f16=True)
    assert {n: p.read_bytes() for n, (p, _, _) in outs.items()} == {"gguf_file": b"GGUF", "gguf_f16": b"GGUF"}
    assert (metrics["size_bytes"], metrics["f16_size_bytes"]) == (4, 4)
    assert node.argv == [] and not mock_orchapod_io.download_directory.called
