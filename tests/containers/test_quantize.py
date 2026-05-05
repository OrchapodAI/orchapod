"""
Tests for containers/quantize/run.py

Covers the two entry points a standalone user hits:
  - resolve_model: HF ID vs R2 URI branching
  - quantize_gguf: correct subprocess args + failure when tools are missing
  - quantize_awq: delegates to AutoAWQ correctly
  - main(): full flow wired together
"""

from pathlib import Path
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------

def test_resolve_model_r2_uri_calls_download(quantize_mod, mock_orchapod_io):
    mock_orchapod_io.download_input.return_value = Path("/workspace/model")

    result = quantize_mod.resolve_model("r2://orchapod-artifacts/runs/abc/model", hf_token=None)

    mock_orchapod_io.download_input.assert_called_once_with(
        "r2://orchapod-artifacts/runs/abc/model", Path("/workspace/model")
    )
    assert result == Path("/workspace/model")


def test_resolve_model_hf_id_calls_snapshot_download(quantize_mod):
    with patch("huggingface_hub.snapshot_download") as mock_dl:
        quantize_mod.resolve_model("Qwen/Qwen3-4B-Instruct", hf_token=None)

    mock_dl.assert_called_once()
    call_kwargs = mock_dl.call_args.kwargs
    assert call_kwargs["repo_id"] == "Qwen/Qwen3-4B-Instruct"
    assert call_kwargs["token"] is None


def test_resolve_model_hf_prefix_stripped(quantize_mod):
    with patch("huggingface_hub.snapshot_download") as mock_dl:
        quantize_mod.resolve_model("hf://Qwen/Qwen3-4B-Instruct", hf_token="tok123")

    call_kwargs = mock_dl.call_args.kwargs
    assert call_kwargs["repo_id"] == "Qwen/Qwen3-4B-Instruct"
    assert call_kwargs["token"] == "tok123"


# ---------------------------------------------------------------------------
# quantize_gguf
# ---------------------------------------------------------------------------

def test_quantize_gguf_raises_if_convert_script_missing(quantize_mod, tmp_path):
    with patch.object(quantize_mod, "LLAMA_CPP_DIR", tmp_path):
        try:
            quantize_mod.quantize_gguf(tmp_path / "model", "q4_k_m")
            assert False, "should have raised"
        except RuntimeError as e:
            assert "convert_hf_to_gguf.py" in str(e)


def test_quantize_gguf_raises_if_quantize_bin_missing(quantize_mod, tmp_path):
    # Create the convert script but not the binary
    (tmp_path / "convert_hf_to_gguf.py").touch()
    (tmp_path / "build" / "bin").mkdir(parents=True)

    with patch.object(quantize_mod, "LLAMA_CPP_DIR", tmp_path):
        try:
            quantize_mod.quantize_gguf(tmp_path / "model", "q4_k_m")
            assert False, "should have raised"
        except RuntimeError as e:
            assert "llama-quantize" in str(e)


def test_quantize_gguf_calls_correct_subprocesses(quantize_mod, tmp_path):
    # Set up the expected tool paths
    convert_script = tmp_path / "convert_hf_to_gguf.py"
    quantize_bin   = tmp_path / "build" / "bin" / "llama-quantize"
    convert_script.touch()
    quantize_bin.parent.mkdir(parents=True)
    quantize_bin.touch()

    model_path = tmp_path / "model"
    model_path.mkdir()

    with patch.object(quantize_mod, "LLAMA_CPP_DIR", tmp_path):
        with patch("subprocess.run") as mock_run:
            # Make the fp16 GGUF appear to exist after conversion
            fp16_path = Path("/workspace/model_fp16.gguf")
            quant_path = Path("/workspace/model_q4_k_m.gguf")
            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = 2_000_000_000
                quantize_mod.quantize_gguf(model_path, "q4_k_m")

    assert mock_run.call_count == 2

    convert_call = mock_run.call_args_list[0]
    assert str(convert_script) in convert_call.args[0]
    assert "--outtype" in convert_call.args[0]
    assert "f16" in convert_call.args[0]

    quant_call = mock_run.call_args_list[1]
    assert str(quantize_bin) in quant_call.args[0]
    assert "Q4_K_M" in quant_call.args[0]


# ---------------------------------------------------------------------------
# quantize_awq
# ---------------------------------------------------------------------------

def test_quantize_awq_calls_autoawq(quantize_mod, tmp_path):
    mock_model     = MagicMock()
    mock_tokenizer = MagicMock()

    with patch("awq.AutoAWQForCausalLM") as MockAWQ:
        with patch("transformers.AutoTokenizer") as MockTokenizer:
            MockAWQ.from_pretrained.return_value  = mock_model
            MockTokenizer.from_pretrained.return_value = mock_tokenizer

            quantize_mod.quantize_awq(tmp_path / "model", bits=4)

    mock_model.quantize.assert_called_once()
    quant_config = mock_model.quantize.call_args.kwargs["quant_config"]
    assert quant_config["w_bit"] == 4
    assert quant_config["q_group_size"] == 128

    mock_model.save_quantized.assert_called_once()
    mock_tokenizer.save_pretrained.assert_called_once()


# ---------------------------------------------------------------------------
# main() — full flow
# ---------------------------------------------------------------------------

def test_main_gguf_flow(quantize_mod, mock_orchapod_io):
    from orchapod.io import Inputs

    mock_orchapod_io.read_inputs.return_value = Inputs(_data={
        "model":     "Qwen/Qwen3-4B-Instruct",
        "method":    "gguf",
        "precision": "q4_k_m",
    })

    with patch.object(quantize_mod, "resolve_model", return_value=Path("/workspace/model")):
        with patch.object(quantize_mod, "quantize_gguf", return_value=Path("/workspace/model_q4_k_m.gguf")):
            quantize_mod.main()

    mock_orchapod_io.write_output.assert_called_once()
    call_kwargs = mock_orchapod_io.write_output.call_args
    assert call_kwargs.args[0] == "gguf_file"
    assert call_kwargs.kwargs["metadata"]["format"] == "gguf"
    assert call_kwargs.kwargs["metadata"]["precision"] == "q4_k_m"


def test_main_unknown_method_raises(quantize_mod, mock_orchapod_io):
    from orchapod.io import Inputs

    mock_orchapod_io.read_inputs.return_value = Inputs(_data={
        "model":  "Qwen/Qwen3-4B-Instruct",
        "method": "tpu",
    })

    with patch.object(quantize_mod, "resolve_model", return_value=Path("/workspace/model")):
        try:
            quantize_mod.main()
            assert False, "should have raised"
        except ValueError as e:
            assert "tpu" in str(e)
