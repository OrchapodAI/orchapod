"""
containers/quantize/run.py — node quantize (cpu). Contract: docs/contracts.md "ML nodes → quantize".

GGUF on CPU with llama.cpp: the HF model (a Hugging Face id, or hf-download's `hf_model` directory) is converted to
an f16 GGUF and quantized to `precision` (q4_k_m, q5_k_m, q8_0) → `gguf_file`. keep_f16 also writes the f16 file as
`gguf_f16`, the honest baseline judge-eval compares against (R11). AWQ needs a GPU job, so it exits 1 here.
STUB=1 writes 4-byte GGUF files with no download.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

from orchapod import io, log

LLAMA_CPP_DIR = Path(os.environ.get("LLAMA_CPP_DIR", "/app"))  # the llama.cpp full image: convert script + binaries
WORKSPACE_DIR = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
PRECISIONS = ("q4_k_m", "q5_k_m", "q8_0")


def fail(reason: str):
    log.error(reason)
    sys.exit(1)


def resolve_model(model: str) -> Path:
    """An r2 directory (hf-download's hf_model) or a Hugging Face id → a local HF model directory."""
    dest = WORKSPACE_DIR / "model"
    if model.startswith("r2://"):
        return io.download_directory(model, dest)
    from huggingface_hub import snapshot_download

    snapshot_download(model.removeprefix("hf://"), local_dir=dest,
                      ignore_patterns=["*.msgpack", "flax_model*", "tf_model*", "*.h5"])  # HF_TOKEN from the env
    return dest


def run(step: str, argv: list[str]) -> None:
    log.info(f"{step}: {' '.join(argv)}")
    code = subprocess.run(argv).returncode  # its output goes to the node's stdout
    if code:
        fail(f"{step} failed (exit {code}); llama.cpp's output is above")


def main():
    inputs = io.read_inputs()
    start = time.monotonic()
    model, method = str(inputs.get("model") or ""), inputs.get("method") or "gguf"
    precision = str(inputs.get("precision") or "q4_k_m").lower()
    keep_f16 = str(inputs.get("keep_f16")).lower() in ("true", "1")
    if not model or "${{" in model:
        fail(f"unresolved ref model: {model!r}")
    if method == "awq":  # ponytail: no AWQ in this CPU image; a GPU job image adds it once there is GPU quota
        fail("AWQ needs a GPU job; use gguf")
    if method != "gguf" or precision not in PRECISIONS:
        fail(f"method {method!r} / precision {precision!r}: use gguf with one of {', '.join(PRECISIONS)}")

    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    f16, out = WORKSPACE_DIR / "model-f16.gguf", WORKSPACE_DIR / f"model-{precision}.gguf"
    if os.environ.get("STUB") == "1":
        f16.write_bytes(b"GGUF")
        out.write_bytes(b"GGUF")
    else:
        src = resolve_model(model)
        run("convert", [sys.executable, str(LLAMA_CPP_DIR / "convert_hf_to_gguf.py"), str(src),
                        "--outfile", str(f16), "--outtype", "f16"])
        run("quantize", [str(LLAMA_CPP_DIR / "llama-quantize"), str(f16), str(out), precision.upper()])

    size, f16_size = out.stat().st_size, f16.stat().st_size
    meta = {"format": "gguf", "base_model": model}
    io.write_output("gguf_file", out, kind="model", metadata={**meta, "precision": precision, "size_bytes": size})
    if keep_f16:
        io.write_output("gguf_f16", f16, kind="model", metadata={**meta, "precision": "f16", "size_bytes": f16_size})
    io.write_metrics({"method": "gguf", "precision": precision, "size_bytes": size, "f16_size_bytes": f16_size,
                      "wall_s": round(time.monotonic() - start)})
    log.info(f"quantize complete: {precision} {size / 1e9:.2f} GB (f16 {f16_size / 1e9:.2f} GB)")


if __name__ == "__main__":
    main()
