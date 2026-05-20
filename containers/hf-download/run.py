"""
containers/hf-download/run.py

Node: hf-download
GPU: CPU-only — no compute needed, just bandwidth + storage

Downloads a HuggingFace model to Cloudflare R2 and registers it in the
model registry so downstream nodes (quantize, vllm-serve) can reference it
by R2 URI instead of re-downloading on every run.

Inputs:
  model_id         — HF model ID, e.g. "Qwen/Qwen3-4B-Instruct"
  hf_token         — optional HuggingFace token for private/gated models
  revision         — optional git ref (branch / tag / commit SHA, default: main)
  ignore_patterns  — optional JSON list of glob patterns to skip
                     (default: drops non-PyTorch weight formats)

Outputs:
  hf_model  — R2 URI to the downloaded HF model directory (format: hf)

Design notes:
  - Uses hf_transfer (Rust extension, 5–10× faster than urllib) when installed.
    Enable with env var HF_HUB_ENABLE_HF_TRANSFER=1 (set in Dockerfile).
  - resume_download=True means interrupted runs auto-resume — satisfies the
    "resume on partial failure" acceptance criterion.
  - SHA256 verification is done explicitly after download by comparing each
    LFS file's hash against the HF Hub metadata.
"""

import hashlib
import os
from pathlib import Path

from orchapod import io, log

WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))

# Files that consume space but aren't needed for PyTorch / vLLM / llama.cpp
_DEFAULT_IGNORE = [
    "*.msgpack",
    "flax_model*",
    "tf_model*",
    "rust_model.ot",
    "*.ot",
    "*.h5",
]


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_model(
    model_id:        str,
    hf_token:        str | None,
    revision:        str | None = None,
    ignore_patterns: list[str] | None = None,
) -> Path:
    """
    Download model from HF Hub with resume-on-failure.
    Returns the local directory path.
    """
    from huggingface_hub import snapshot_download

    dest = WORKSPACE_DIR / "hf_model"
    dest.mkdir(parents=True, exist_ok=True)

    log.info(f"Downloading {model_id}  revision={revision or 'main'}  →  {dest}")
    snapshot_download(
        repo_id=model_id,
        local_dir=str(dest),
        token=hf_token or None,
        revision=revision or None,
        ignore_patterns=ignore_patterns or _DEFAULT_IGNORE,
        resume_download=True,
    )
    log.info(f"Download complete: {dest}")
    return dest


# ---------------------------------------------------------------------------
# SHA256 verification
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    """Compute SHA256 of a file, streaming in 8 MB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(local_dir: Path, model_id: str, hf_token: str | None) -> None:
    """
    Cross-check every LFS file in local_dir against the SHA256 recorded in
    HF Hub metadata. Non-LFS files (config.json, tokenizer files, etc.) are
    small git-managed blobs — snapshot_download already checks them; we skip.

    Raises RuntimeError listing all mismatches/missing files.
    """
    from huggingface_hub import HfApi

    api = HfApi()
    try:
        info = api.model_info(model_id, files_metadata=True, token=hf_token or None)
    except Exception as exc:
        log.warning(f"Could not fetch HF metadata for SHA256 check: {exc}. Skipping verification.")
        return

    lfs_files: dict[str, str] = {
        s.rfilename: s.lfs.sha256
        for s in (info.siblings or [])
        if getattr(s, "lfs", None) is not None
    }

    if not lfs_files:
        log.info("No LFS files found in repo metadata — verification skipped.")
        return

    log.info(f"Verifying SHA256 for {len(lfs_files)} LFS file(s)…")
    errors: list[str] = []

    for rfilename, expected in lfs_files.items():
        local_file = local_dir / rfilename
        if not local_file.exists():
            errors.append(f"  MISSING   {rfilename}")
            continue
        actual = _sha256_file(local_file)
        if actual != expected:
            errors.append(
                f"  MISMATCH  {rfilename}\n"
                f"            expected {expected[:24]}…\n"
                f"            got      {actual[:24]}…"
            )
        else:
            log.info(f"  ✓ {rfilename}  ({actual[:16]}…)")

    if errors:
        raise RuntimeError("SHA256 verification failed:\n" + "\n".join(errors))

    log.info(f"SHA256 OK — {len(lfs_files)} file(s) verified.")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    inputs   = io.read_inputs()
    model_id = inputs["model_id"]
    hf_token = inputs.get("hf_token") or os.environ.get("HF_TOKEN")
    revision = inputs.get("revision") or None

    raw_ignore = inputs.get("ignore_patterns")
    ignore_patterns: list[str] | None
    if isinstance(raw_ignore, list):
        ignore_patterns = raw_ignore
    elif isinstance(raw_ignore, str) and raw_ignore.strip():
        import json
        ignore_patterns = json.loads(raw_ignore)
    else:
        ignore_patterns = None

    log.info(f"hf-download  model_id={model_id}  revision={revision or 'main'}")

    local_dir = download_model(model_id, hf_token, revision, ignore_patterns)
    verify_sha256(local_dir, model_id, hf_token)

    io.write_output(
        "hf_model",
        local_dir,
        kind="model",
        metadata={
            "format":   "hf",
            "model_id": model_id,
            "revision": revision or "main",
        },
    )

    log.info("hf-download complete")


if __name__ == "__main__":
    main()
