"""
Unit tests for containers/vllm-serve/run.py
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from .conftest import load_container

v = load_container("vllm-serve")


# ---------------------------------------------------------------------------
# detect_public_url
# ---------------------------------------------------------------------------

def test_detect_public_url_uses_explicit_override(monkeypatch):
    monkeypatch.setenv("ORCHAPOD_PUBLIC_URL", "https://custom.orchapod.dev/v1")
    assert v.detect_public_url() == "https://custom.orchapod.dev/v1"


def test_detect_public_url_runpod(monkeypatch):
    monkeypatch.delenv("ORCHAPOD_PUBLIC_URL", raising=False)
    monkeypatch.setenv("RUNPOD_POD_ID", "abc123")
    assert v.detect_public_url() == "https://abc123-8000.proxy.runpod.net/v1"


def test_detect_public_url_vastai(monkeypatch):
    monkeypatch.delenv("ORCHAPOD_PUBLIC_URL", raising=False)
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)
    monkeypatch.setenv("PUBLIC_IPADDR", "1.2.3.4")
    monkeypatch.setenv("VAST_TCP_PORT_8000", "40001")
    assert v.detect_public_url() == "http://1.2.3.4:40001/v1"


def test_detect_public_url_vastai_default_port(monkeypatch):
    monkeypatch.delenv("ORCHAPOD_PUBLIC_URL", raising=False)
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)
    monkeypatch.setenv("PUBLIC_IPADDR", "1.2.3.4")
    monkeypatch.delenv("VAST_TCP_PORT_8000", raising=False)
    assert v.detect_public_url() == "http://1.2.3.4:8000/v1"


def test_detect_public_url_localhost_fallback(monkeypatch):
    monkeypatch.delenv("ORCHAPOD_PUBLIC_URL", raising=False)
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)
    monkeypatch.delenv("PUBLIC_IPADDR", raising=False)
    assert v.detect_public_url() == "http://localhost:8000/v1"


# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------

def test_resolve_model_hf_passthrough():
    result = v.resolve_model("Qwen/Qwen3-4B-Instruct", hf_token=None)
    assert result == "Qwen/Qwen3-4B-Instruct"


def test_resolve_model_strips_hf_prefix():
    result = v.resolve_model("hf://Qwen/Qwen3-4B-Instruct", hf_token=None)
    assert result == "Qwen/Qwen3-4B-Instruct"


def test_resolve_model_r2_uri_downloads(mock_orchapod_io):
    mock_orchapod_io.download_input.return_value = Path("/workspace/model")
    result = v.resolve_model("r2://orchapod-artifacts/runs/abc/model", hf_token=None)
    mock_orchapod_io.download_input.assert_called_once()
    assert result == "/workspace/model"


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def _make_mock_proc():
    proc = MagicMock()
    proc.wait.return_value = 0
    proc.kill.return_value = None
    return proc


def test_main_writes_two_outputs_and_registers_ttl(mock_orchapod_io, monkeypatch):
    monkeypatch.setenv("ORCHAPOD_RUN_ID",  "run-1")
    monkeypatch.setenv("ORCHAPOD_NODE_ID", "node")
    monkeypatch.delenv("ORCHAPOD_PUBLIC_URL", raising=False)
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)
    monkeypatch.delenv("PUBLIC_IPADDR", raising=False)

    mock_orchapod_io.read_inputs.return_value = {
        "model": "Qwen/Qwen3-4B-Instruct",
        "keep_alive_min": 30,
    }

    proc = _make_mock_proc()
    with patch("subprocess.Popen", return_value=proc), \
         patch("urllib.request.urlopen") as mock_urlopen:
        v.main()

    assert mock_orchapod_io.write_output.call_count == 2
    output_names = [c.args[0] for c in mock_orchapod_io.write_output.call_args_list]
    assert "endpoint_url"   in output_names
    assert "openai_api_key" in output_names

    # TTL alarm + health check both call urlopen
    assert mock_urlopen.call_count >= 1


def test_main_injects_hf_token_into_subprocess_env(mock_orchapod_io, monkeypatch):
    monkeypatch.setenv("ORCHAPOD_RUN_ID",  "run-2")
    monkeypatch.setenv("ORCHAPOD_NODE_ID", "node")
    monkeypatch.delenv("ORCHAPOD_PUBLIC_URL", raising=False)
    monkeypatch.delenv("RUNPOD_POD_ID", raising=False)
    monkeypatch.delenv("PUBLIC_IPADDR", raising=False)

    mock_orchapod_io.read_inputs.return_value = {
        "model": "Qwen/Qwen3-4B-Instruct",
        "hf_token": "hf-secret-token",
    }

    proc = _make_mock_proc()
    captured_env = {}
    def fake_popen(cmd, env):
        captured_env.update(env)
        return proc

    with patch("subprocess.Popen", side_effect=fake_popen), \
         patch("urllib.request.urlopen"):
        v.main()

    assert captured_env.get("HF_TOKEN") == "hf-secret-token"
