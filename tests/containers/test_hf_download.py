"""
Unit tests for containers/hf-download/run.py
"""

import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from .conftest import load_container

d = load_container("hf-download")


# ---------------------------------------------------------------------------
# download_model
# ---------------------------------------------------------------------------

def test_download_model_calls_snapshot_download(tmp_path):
    with patch.object(d, "WORKSPACE_DIR", tmp_path), \
         patch("huggingface_hub.snapshot_download") as mock_dl:
        d.download_model("Qwen/Qwen3-4B-Instruct", hf_token=None)
    mock_dl.assert_called_once()
    kw = mock_dl.call_args.kwargs
    assert kw["repo_id"]         == "Qwen/Qwen3-4B-Instruct"
    assert kw["resume_download"] is True
    assert kw["token"]           is None


def test_download_model_passes_token(tmp_path):
    with patch.object(d, "WORKSPACE_DIR", tmp_path), \
         patch("huggingface_hub.snapshot_download") as mock_dl:
        d.download_model("meta-llama/Llama-3.1-8B-Instruct", hf_token="hf_tok123")
    assert mock_dl.call_args.kwargs["token"] == "hf_tok123"


def test_download_model_passes_revision(tmp_path):
    with patch.object(d, "WORKSPACE_DIR", tmp_path), \
         patch("huggingface_hub.snapshot_download") as mock_dl:
        d.download_model("Qwen/Qwen3-4B-Instruct", hf_token=None, revision="abc123def")
    assert mock_dl.call_args.kwargs["revision"] == "abc123def"


def test_download_model_passes_custom_ignore_patterns(tmp_path):
    with patch.object(d, "WORKSPACE_DIR", tmp_path), \
         patch("huggingface_hub.snapshot_download") as mock_dl:
        d.download_model("Qwen/Qwen3-4B-Instruct", hf_token=None, ignore_patterns=["*.bin"])
    assert mock_dl.call_args.kwargs["ignore_patterns"] == ["*.bin"]


def test_download_model_uses_default_ignore_when_none(tmp_path):
    with patch.object(d, "WORKSPACE_DIR", tmp_path), \
         patch("huggingface_hub.snapshot_download") as mock_dl:
        d.download_model("Qwen/Qwen3-4B-Instruct", hf_token=None)
    patterns = mock_dl.call_args.kwargs["ignore_patterns"]
    assert "*.msgpack" in patterns
    assert "flax_model*" in patterns


# ---------------------------------------------------------------------------
# _sha256_file
# ---------------------------------------------------------------------------

def test_sha256_file_matches_hashlib(tmp_path):
    f = tmp_path / "weights.bin"
    content = b"fake model weights " * 1000
    f.write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()
    assert d._sha256_file(f) == expected


# ---------------------------------------------------------------------------
# verify_sha256
# ---------------------------------------------------------------------------

def _make_sibling(rfilename: str, sha256: str | None):
    s = MagicMock()
    s.rfilename = rfilename
    if sha256 is not None:
        s.lfs = MagicMock()
        s.lfs.sha256 = sha256
    else:
        s.lfs = None
    return s


def test_verify_sha256_passes_when_all_match(tmp_path):
    content = b"real weights"
    (tmp_path / "model.safetensors").write_bytes(content)
    expected = hashlib.sha256(content).hexdigest()

    sibling = _make_sibling("model.safetensors", expected)
    with patch("huggingface_hub.HfApi") as MockApi:
        MockApi.return_value.model_info.return_value = MagicMock(siblings=[sibling])
        d.verify_sha256(tmp_path, "Qwen/Qwen3-4B-Instruct", hf_token=None)  # no exception


def test_verify_sha256_raises_on_hash_mismatch(tmp_path):
    (tmp_path / "model.safetensors").write_bytes(b"corrupted data")
    sibling = _make_sibling("model.safetensors", "0" * 64)  # wrong hash

    with patch("huggingface_hub.HfApi") as MockApi:
        MockApi.return_value.model_info.return_value = MagicMock(siblings=[sibling])
        with pytest.raises(RuntimeError, match="SHA256 verification failed"):
            d.verify_sha256(tmp_path, "Qwen/Qwen3-4B-Instruct", hf_token=None)


def test_verify_sha256_raises_on_missing_file(tmp_path):
    sibling = _make_sibling("model.safetensors", "a" * 64)
    # Do NOT create the file

    with patch("huggingface_hub.HfApi") as MockApi:
        MockApi.return_value.model_info.return_value = MagicMock(siblings=[sibling])
        with pytest.raises(RuntimeError, match="SHA256 verification failed"):
            d.verify_sha256(tmp_path, "Qwen/Qwen3-4B-Instruct", hf_token=None)


def test_verify_sha256_skips_non_lfs_files(tmp_path):
    """Config / tokenizer files have no LFS metadata — should be silently skipped."""
    sibling = _make_sibling("config.json", sha256=None)

    with patch("huggingface_hub.HfApi") as MockApi:
        MockApi.return_value.model_info.return_value = MagicMock(siblings=[sibling])
        d.verify_sha256(tmp_path, "Qwen/Qwen3-4B-Instruct", hf_token=None)  # no exception


def test_verify_sha256_skips_gracefully_on_api_error(tmp_path):
    """If HF Hub is unreachable, verification is skipped with a warning — not a crash."""
    with patch("huggingface_hub.HfApi") as MockApi:
        MockApi.return_value.model_info.side_effect = Exception("connection refused")
        d.verify_sha256(tmp_path, "Qwen/Qwen3-4B-Instruct", hf_token=None)  # no exception


def test_verify_sha256_handles_no_lfs_files(tmp_path):
    """Model with no LFS files (rare) should not crash."""
    sibling = _make_sibling("config.json", sha256=None)  # non-LFS only

    with patch("huggingface_hub.HfApi") as MockApi:
        MockApi.return_value.model_info.return_value = MagicMock(siblings=[sibling])
        d.verify_sha256(tmp_path, "some/tiny-model", hf_token=None)  # no exception


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_calls_download_and_verify_and_writes_output(mock_orchapod_io, tmp_path):
    mock_orchapod_io.read_inputs.return_value = {
        "model_id": "Qwen/Qwen3-4B-Instruct",
    }
    fake_dir = tmp_path / "hf_model"
    fake_dir.mkdir()

    with patch.object(d, "download_model", return_value=fake_dir) as mock_dl, \
         patch.object(d, "verify_sha256")  as mock_verify:
        d.main()

    mock_dl.assert_called_once_with("Qwen/Qwen3-4B-Instruct", None, None, None)
    mock_verify.assert_called_once_with(fake_dir, "Qwen/Qwen3-4B-Instruct", None)

    mock_orchapod_io.write_output.assert_called_once()
    args, kwargs = mock_orchapod_io.write_output.call_args
    assert args[0] == "hf_model"
    assert kwargs["kind"] == "model"
    assert kwargs["metadata"]["format"] == "hf"
    assert kwargs["metadata"]["model_id"] == "Qwen/Qwen3-4B-Instruct"


def test_main_passes_token_from_inputs(mock_orchapod_io, tmp_path):
    mock_orchapod_io.read_inputs.return_value = {
        "model_id": "meta-llama/Llama-3.1-8B-Instruct",
        "hf_token": "hf_secret",
    }
    fake_dir = tmp_path / "hf_model"
    fake_dir.mkdir()

    with patch.object(d, "download_model", return_value=fake_dir) as mock_dl, \
         patch.object(d, "verify_sha256"):
        d.main()

    assert mock_dl.call_args.args[1] == "hf_secret"


def test_main_passes_revision(mock_orchapod_io, tmp_path):
    mock_orchapod_io.read_inputs.return_value = {
        "model_id": "Qwen/Qwen3-4B-Instruct",
        "revision": "v0.1",
    }
    fake_dir = tmp_path / "hf_model"
    fake_dir.mkdir()

    with patch.object(d, "download_model", return_value=fake_dir) as mock_dl, \
         patch.object(d, "verify_sha256"):
        d.main()

    assert mock_dl.call_args.args[2] == "v0.1"
    metadata = mock_orchapod_io.write_output.call_args.kwargs["metadata"]
    assert metadata["revision"] == "v0.1"


def test_main_parses_ignore_patterns_from_json_string(mock_orchapod_io, tmp_path):
    mock_orchapod_io.read_inputs.return_value = {
        "model_id": "Qwen/Qwen3-4B-Instruct",
        "ignore_patterns": '["*.bin", "*.pt"]',
    }
    fake_dir = tmp_path / "hf_model"
    fake_dir.mkdir()

    with patch.object(d, "download_model", return_value=fake_dir) as mock_dl, \
         patch.object(d, "verify_sha256"):
        d.main()

    assert mock_dl.call_args.args[3] == ["*.bin", "*.pt"]
