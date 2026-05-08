"""
Unit tests for containers/quantize/run.py
"""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from .conftest import load_container

q = load_container("quantize")


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------

def test_resolve_model_r2_uri_calls_download(mock_orchapod_io):
    mock_orchapod_io.download_input.return_value = Path("/workspace/model")
    result = q.resolve_model("r2://orchapod-artifacts/runs/abc/model", hf_token=None)
    mock_orchapod_io.download_input.assert_called_once()
    assert result == Path("/workspace/model")


def test_resolve_model_hf_id_uses_snapshot_download():
    with patch("huggingface_hub.snapshot_download") as mock_dl:
        q.resolve_model("Qwen/Qwen3-4B-Instruct", hf_token=None)
    mock_dl.assert_called_once()
    call_kwargs = mock_dl.call_args
    assert call_kwargs.kwargs["repo_id"] == "Qwen/Qwen3-4B-Instruct"
    assert call_kwargs.kwargs["token"] is None


def test_resolve_model_strips_hf_prefix():
    with patch("huggingface_hub.snapshot_download") as mock_dl:
        q.resolve_model("hf://Qwen/Qwen3-4B-Instruct", hf_token="tok")
    call_kwargs = mock_dl.call_args
    assert call_kwargs.kwargs["repo_id"] == "Qwen/Qwen3-4B-Instruct"
    assert call_kwargs.kwargs["token"] == "tok"


# ---------------------------------------------------------------------------
# quantize_gguf
# ---------------------------------------------------------------------------

def test_quantize_gguf_raises_if_convert_script_missing(tmp_path):
    fake_llama = tmp_path / "llama.cpp"
    fake_llama.mkdir()
    # Do not create convert_hf_to_gguf.py
    with patch.object(q, "LLAMA_CPP_DIR", fake_llama):
        with pytest.raises(RuntimeError, match="convert script not found"):
            q.quantize_gguf(tmp_path / "model", "q4_k_m")


def test_quantize_gguf_raises_if_quantize_bin_missing(tmp_path):
    fake_llama = tmp_path / "llama.cpp"
    fake_llama.mkdir()
    (fake_llama / "convert_hf_to_gguf.py").touch()
    # Do not create build/bin/llama-quantize
    with patch.object(q, "LLAMA_CPP_DIR", fake_llama):
        with pytest.raises(RuntimeError, match="llama-quantize binary not found"):
            q.quantize_gguf(tmp_path / "model", "q4_k_m")


def test_quantize_gguf_calls_correct_subprocesses(tmp_path):
    fake_llama = tmp_path / "llama.cpp"
    (fake_llama / "build" / "bin").mkdir(parents=True)
    (fake_llama / "convert_hf_to_gguf.py").touch()
    quantize_bin = fake_llama / "build" / "bin" / "llama-quantize"
    quantize_bin.touch()

    # Make the gguf_quant file exist so stat() works
    gguf_quant = Path("/workspace/model_q4_k_m.gguf")

    calls = []
    def fake_run(cmd, check):
        calls.append(cmd)
        if "--outfile" in cmd:
            Path(cmd[cmd.index("--outfile") + 1]).touch()
        else:
            gguf_quant.parent.mkdir(parents=True, exist_ok=True)
            gguf_quant.touch()

    with patch.object(q, "LLAMA_CPP_DIR", fake_llama), \
         patch("subprocess.run", side_effect=fake_run):
        q.quantize_gguf(tmp_path / "model", "q4_k_m")

    assert len(calls) == 2
    assert "--outtype" in calls[0]
    assert "Q4_K_M" in calls[1]


# ---------------------------------------------------------------------------
# quantize_awq
# ---------------------------------------------------------------------------

def test_quantize_awq_delegates_to_autoawq(tmp_path):
    mock_model = MagicMock()
    mock_tokenizer = MagicMock()
    with patch.dict("sys.modules", {
        "awq": MagicMock(AutoAWQForCausalLM=MagicMock(
            from_pretrained=MagicMock(return_value=mock_model)
        )),
        "transformers": MagicMock(AutoTokenizer=MagicMock(
            from_pretrained=MagicMock(return_value=mock_tokenizer)
        )),
    }):
        result = q.quantize_awq(tmp_path / "model", bits=4)

    mock_model.quantize.assert_called_once()
    mock_model.save_quantized.assert_called_once()
    assert result == Path("/workspace/awq_model")


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_gguf_flow(mock_orchapod_io):
    mock_orchapod_io.read_inputs.return_value = {
        "model": "Qwen/Qwen3-4B-Instruct",
        "method": "gguf",
        "precision": "q4_k_m",
    }
    with patch.object(q, "resolve_model", return_value=Path("/workspace/model")), \
         patch.object(q, "quantize_gguf", return_value=Path("/workspace/model_q4_k_m.gguf")):
        q.main()

    mock_orchapod_io.write_output.assert_called_once()
    args = mock_orchapod_io.write_output.call_args
    assert args.args[0] == "gguf_file"


def test_main_awq_flow(mock_orchapod_io):
    mock_orchapod_io.read_inputs.return_value = {
        "model": "Qwen/Qwen3-4B-Instruct",
        "method": "awq",
        "bits": "4",
    }
    with patch.object(q, "resolve_model", return_value=Path("/workspace/model")), \
         patch.object(q, "quantize_awq", return_value=Path("/workspace/awq_model")):
        q.main()

    args = mock_orchapod_io.write_output.call_args
    assert args.args[0] == "awq_model"


def test_main_unknown_method_raises(mock_orchapod_io):
    mock_orchapod_io.read_inputs.return_value = {
        "model": "Qwen/Qwen3-4B-Instruct",
        "method": "tpu-magic",
    }
    with patch.object(q, "resolve_model", return_value=Path("/workspace/model")):
        with pytest.raises(ValueError, match="Unknown quantize method"):
            q.main()
