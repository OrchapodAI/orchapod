"""Unit tests for containers/hf-download/run.py (docs/contracts.md "ML nodes → hf-download")."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from huggingface_hub.errors import GatedRepoError

from packages.workflow_schema.models import HFDownloadInputs

from .conftest import load_container

d = load_container("hf-download")

MODEL = "Qwen/Qwen2.5-Math-1.5B-Instruct"
WEIGHTS = b"real weights"


def sibling(name, sha=None):
    return SimpleNamespace(rfilename=name, lfs=SimpleNamespace(sha256=sha) if sha else None)


@pytest.fixture
def node(mock_orchapod_io, monkeypatch, tmp_path):
    """node(**inputs) runs main() into tmp_path; returns ({name: (dir, kind, metadata)}, metrics)."""
    monkeypatch.setattr(d, "WORKSPACE_DIR", tmp_path)
    monkeypatch.delenv("STUB", raising=False)

    def run(**inputs):
        mock_orchapod_io.read_inputs.return_value = {"model_id": MODEL, **inputs}
        d.main()
        outs = {c.args[0]: (c.args[1], c.kwargs["kind"], c.kwargs["metadata"])
                for c in mock_orchapod_io.write_output.call_args_list}
        return outs, mock_orchapod_io.write_metrics.call_args.args[0]

    return run


@pytest.fixture
def hub():
    """A fake Hub: snapshot_download (checked against the real signature) writes the repo's files its ignore_patterns
    let through; model_info lists the SHA-256 of the LFS ones (the flax file is ignored by default)."""
    from huggingface_hub.utils import filter_repo_objects

    files = {"config.json": b"{}", "model.safetensors": WEIGHTS, "flax_model.msgpack": b"flax"}

    def download(repo_id, *, local_dir, ignore_patterns, **_):
        (local_dir / ".cache" / "huggingface").mkdir(parents=True)
        (local_dir / ".cache" / "huggingface" / "x.metadata").write_text("bookkeeping")
        for name in filter_repo_objects(files, ignore_patterns=ignore_patterns):
            (local_dir / name).write_bytes(files[name])

    siblings = [sibling("config.json")] + [sibling(n, hashlib.sha256(files[n]).hexdigest())
                                           for n in ("model.safetensors", "flax_model.msgpack")]
    with patch("huggingface_hub.snapshot_download", autospec=True, side_effect=download) as dl, \
         patch("huggingface_hub.HfApi") as api:
        api.return_value.model_info.return_value = SimpleNamespace(siblings=siblings)
        yield SimpleNamespace(download=dl, info=api.return_value.model_info, siblings=siblings)


def test_inputs_carry_no_token():
    assert set(HFDownloadInputs.model_fields) == {"model_id", "revision", "ignore_patterns"}  # HF_TOKEN is env only
    assert HFDownloadInputs(model_id=MODEL).revision == "main"


def test_downloads_verifies_and_writes_hf_model_with_metrics(node, hub, tmp_path):
    outs, metrics = node()
    path, kind, meta = outs["hf_model"]
    assert (path, kind, meta) == (tmp_path / "hf_model", "model", {"format": "hf", "model_id": MODEL, "revision": "main"})
    assert hub.download.call_args.kwargs == {"revision": "main", "local_dir": path, "ignore_patterns": d.DEFAULT_IGNORE}
    hub.info.assert_called_once_with(MODEL, revision="main", files_metadata=True)
    assert not (path / ".cache").exists()  # download bookkeeping is not uploaded
    assert metrics == {"files": 2, "bytes": 2 + len(WEIGHTS), "sha256_verified": True}  # the ignored flax file is not missing


def test_revision_and_json_ignore_patterns_reach_the_hub(node, hub):
    node(revision="v1.0", ignore_patterns='["*.bin", "*.pt"]')
    assert hub.download.call_args.kwargs["ignore_patterns"] == ["*.bin", "*.pt"]
    assert hub.download.call_args.kwargs["revision"] == hub.info.call_args.kwargs["revision"] == "v1.0"


@pytest.mark.parametrize("bad", ["mismatch", "missing"])
def test_a_file_that_does_not_match_the_hub_exits_1(node, hub, bad):
    if bad == "mismatch":
        hub.siblings[1].lfs.sha256 = "0" * 64
    else:
        hub.siblings.append(sibling("model-00002.safetensors", "a" * 64))
    with pytest.raises(SystemExit) as e:
        node()
    assert e.value.code == 1 and "sha256" in d.log.error.call_args.args[0]


def test_no_hub_metadata_skips_the_check_with_a_warning(node, hub):
    hub.info.side_effect = OSError("connection refused")
    assert node()[1]["sha256_verified"] is False
    d.log.warn.assert_called_once()


def test_a_gated_model_without_access_says_set_hf_token(node, hub):
    hub.download.side_effect = GatedRepoError("401 gated", response=SimpleNamespace(headers={}, request=None))
    with pytest.raises(SystemExit) as e:
        node()
    assert e.value.code == 1 and "set HF_TOKEN and accept the licence" in d.log.error.call_args.args[0]


def test_stub_writes_a_fixed_directory_without_the_hub(node, hub, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    outs, metrics = node()
    path = outs["hf_model"][0]
    assert json.loads((path / "config.json").read_text()) == {"stub": True, "model_id": MODEL, "revision": "main"}
    assert metrics["files"] == 1 and metrics["sha256_verified"] is False
    hub.download.assert_not_called()
    hub.info.assert_not_called()
