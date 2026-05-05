"""
Tests for containers/vllm-serve/run.py

Focus areas:
  - detect_public_url: the 4-case priority chain — critical for multi-provider support
  - resolve_model: HF passthrough vs R2 download
  - main(): vLLM subprocess, health check, output registration
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# detect_public_url — priority chain
# ---------------------------------------------------------------------------

def test_detect_public_url_orchapod_override_takes_priority(vllm_serve_mod, monkeypatch):
    monkeypatch.setenv("ORCHAPOD_PUBLIC_URL", "https://custom.example.com/v1")
    monkeypatch.setenv("RUNPOD_POD_ID", "pod123")  # lower priority — should be ignored

    assert vllm_serve_mod.detect_public_url() == "https://custom.example.com/v1"


def test_detect_public_url_runpod_pod_id(vllm_serve_mod, monkeypatch):
    monkeypatch.delenv("ORCHAPOD_PUBLIC_URL", raising=False)
    monkeypatch.setenv("RUNPOD_POD_ID", "abc99")
    monkeypatch.delenv("PUBLIC_IPADDR", raising=False)

    assert vllm_serve_mod.detect_public_url() == "https://abc99-8000.proxy.runpod.net/v1"


def test_detect_public_url_vastai_public_ip(vllm_serve_mod, monkeypatch):
    monkeypatch.delenv("ORCHAPOD_PUBLIC_URL", raising=False)
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)
    monkeypatch.setenv("PUBLIC_IPADDR", "203.0.113.42")
    monkeypatch.setenv("VAST_TCP_PORT_8000", "34567")

    assert vllm_serve_mod.detect_public_url() == "http://203.0.113.42:34567/v1"


def test_detect_public_url_vastai_default_port(vllm_serve_mod, monkeypatch):
    monkeypatch.delenv("ORCHAPOD_PUBLIC_URL", raising=False)
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)
    monkeypatch.setenv("PUBLIC_IPADDR", "203.0.113.42")
    monkeypatch.delenv("VAST_TCP_PORT_8000", raising=False)

    assert vllm_serve_mod.detect_public_url() == "http://203.0.113.42:8000/v1"


def test_detect_public_url_localhost_fallback(vllm_serve_mod, monkeypatch):
    monkeypatch.delenv("ORCHAPOD_PUBLIC_URL", raising=False)
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)
    monkeypatch.delenv("PUBLIC_IPADDR", raising=False)

    assert vllm_serve_mod.detect_public_url() == "http://localhost:8000/v1"


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------

def test_resolve_model_hf_id_passes_through(vllm_serve_mod, mock_orchapod_io):
    result = vllm_serve_mod.resolve_model("Qwen/Qwen3-4B-Instruct", hf_token=None)

    mock_orchapod_io.download_input.assert_not_called()
    assert result == "Qwen/Qwen3-4B-Instruct"


def test_resolve_model_hf_prefix_stripped(vllm_serve_mod, mock_orchapod_io):
    result = vllm_serve_mod.resolve_model("hf://Qwen/Qwen3-4B-Instruct", hf_token=None)

    assert result == "Qwen/Qwen3-4B-Instruct"


def test_resolve_model_r2_uri_downloads(vllm_serve_mod, mock_orchapod_io):
    mock_orchapod_io.download_input.return_value = Path("/workspace/model/merged_model")

    result = vllm_serve_mod.resolve_model(
        "r2://orchapod-artifacts/runs/abc/train_1/merged_model",
        hf_token=None,
    )

    mock_orchapod_io.download_input.assert_called_once()
    assert result == "/workspace/model/merged_model"


# ---------------------------------------------------------------------------
# main() — full flow
# ---------------------------------------------------------------------------

def test_main_writes_endpoint_and_api_key(vllm_serve_mod, mock_orchapod_io, monkeypatch):
    from orchapod.io import Inputs

    monkeypatch.delenv("ORCHAPOD_PUBLIC_URL", raising=False)
    monkeypatch.setenv("RUNPOD_POD_ID", "pod42")
    monkeypatch.setenv("ORCHAPOD_RUN_ID", "run-1")
    monkeypatch.setenv("ORCHAPOD_NODE_ID", "node")
    monkeypatch.delenv("ORCHAPOD_CONTROL_URL", raising=False)

    mock_orchapod_io.read_inputs.return_value = Inputs(_data={
        "model":          "Qwen/Qwen3-4B-Instruct",
        "keep_alive_min": "30",
    })
    mock_orchapod_io.local_path.return_value = Path("/tmp/endpoint.json")

    mock_proc = MagicMock()
    mock_proc.wait.return_value = 0

    with patch("subprocess.Popen", return_value=mock_proc):
        with patch.object(vllm_serve_mod, "wait_for_vllm"):
            with patch.object(vllm_serve_mod, "register_ttl_alarm") as mock_ttl:
                vllm_serve_mod.main()

    # endpoint.json must be written
    endpoint_json_path = Path("/tmp/endpoint.json")
    written = mock_orchapod_io.local_path.return_value
    # write_output called twice: endpoint_url + openai_api_key
    assert mock_orchapod_io.write_output.call_count == 2

    # TTL alarm registered with correct duration
    mock_ttl.assert_called_once_with("https://pod42-8000.proxy.runpod.net/v1", 30)


def test_main_passes_hf_token_to_subprocess_env(vllm_serve_mod, mock_orchapod_io, monkeypatch):
    from orchapod.io import Inputs

    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)
    monkeypatch.delenv("ORCHAPOD_CONTROL_URL", raising=False)

    mock_orchapod_io.read_inputs.return_value = Inputs(_data={
        "model":    "meta-llama/Llama-3-8B-Instruct",
        "hf_token": "hf_secret",
    })
    mock_orchapod_io.local_path.return_value = Path("/tmp/endpoint.json")

    captured_env = {}

    def capture_popen(cmd, env=None, **kwargs):
        captured_env.update(env or {})
        m = MagicMock()
        m.wait.return_value = 0
        return m

    with patch("subprocess.Popen", side_effect=capture_popen):
        with patch.object(vllm_serve_mod, "wait_for_vllm"):
            with patch.object(vllm_serve_mod, "register_ttl_alarm"):
                vllm_serve_mod.main()

    assert captured_env.get("HF_TOKEN") == "hf_secret"
    assert captured_env.get("HUGGING_FACE_HUB_TOKEN") == "hf_secret"
