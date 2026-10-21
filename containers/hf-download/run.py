"""
containers/hf-download/run.py — node hf-download (cpu). Contract: docs/contracts.md "ML nodes → hf-download".

Downloads a Hugging Face model snapshot (non-PyTorch weight formats skipped by default), checks every downloaded LFS
file against the Hub's SHA-256 and writes it as the `hf_model` directory for quantize and vllm-serve. A gated model
needs HF_TOKEN in the env (never an input) and its licence accepted. STUB=1 writes a fixed one-file directory offline.
"""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from orchapod import io, log

WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
DEFAULT_IGNORE = ["*.msgpack", "flax_model*", "tf_model*", "rust_model.ot", "*.ot", "*.h5"]  # not for PyTorch/llama.cpp
SOURCE = "orchapod_source.json"  # {model_id, revision} beside the files: a consumer handed the r2 dir knows the Hub id


def fail(reason: str):
    log.error(reason)
    sys.exit(1)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(local_dir: Path, model_id: str, revision: str, ignore: list[str]) -> bool:
    """Every LFS file the download should hold against the Hub's SHA-256; False when the Hub's metadata is unavailable."""
    from huggingface_hub import HfApi
    from huggingface_hub.utils import filter_repo_objects

    try:
        info = HfApi().model_info(model_id, revision=revision, files_metadata=True)
    except Exception as e:
        log.warn(f"no Hub metadata for {model_id}@{revision}, SHA-256 check skipped: {e}")
        return False
    lfs = {s.rfilename: s.lfs.sha256 for s in info.siblings or [] if getattr(s, "lfs", None)}
    checked = list(filter_repo_objects(sorted(lfs), ignore_patterns=ignore))  # ignored files were never downloaded
    for name in checked:
        if not (local_dir / name).is_file():
            fail(f"sha256 check: {name} is on the Hub but was not downloaded")
        if sha256(local_dir / name) != lfs[name]:
            fail(f"sha256 mismatch: {name} differs from the Hub's {model_id}@{revision}")
    log.info(f"SHA-256 verified for {len(checked)} LFS files")
    return True


def main():
    inputs = io.read_inputs()
    model_id, revision = inputs["model_id"], inputs.get("revision") or "main"
    ignore = inputs.get("ignore_patterns") or DEFAULT_IGNORE
    ignore = json.loads(ignore) if isinstance(ignore, str) else ignore
    dest = WORKSPACE_DIR / "hf_model"
    dest.mkdir(parents=True, exist_ok=True)
    verified = False
    if os.environ.get("STUB") == "1":
        (dest / "config.json").write_text(json.dumps({"stub": True, "model_id": model_id, "revision": revision}))
    else:
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError

        log.info(f"downloading {model_id}@{revision}")
        try:  # HF_TOKEN, when set, is read from the env by huggingface_hub
            snapshot_download(model_id, revision=revision, local_dir=dest, ignore_patterns=ignore)
        except GatedRepoError:
            fail(f"{model_id} is gated: set HF_TOKEN and accept the licence on huggingface.co")
        except RepositoryNotFoundError:
            fail(f"{model_id} is not on huggingface.co (a private model needs HF_TOKEN)")
        shutil.rmtree(dest / ".cache", ignore_errors=True)  # download bookkeeping, not model files
        verified = verify(dest, model_id, revision, ignore)
    (dest / SOURCE).write_text(json.dumps({"model_id": model_id, "revision": revision}))

    files = [f for f in dest.rglob("*") if f.is_file()]
    io.write_output("hf_model", dest, kind="model", metadata={"format": "hf", "model_id": model_id, "revision": revision})
    io.write_metrics({"files": len(files), "bytes": sum(f.stat().st_size for f in files), "sha256_verified": verified})
    log.info(f"hf-download complete: {model_id}@{revision}, {len(files)} files")


if __name__ == "__main__":
    main()
