"""
containers/quantize/run.py

Node: quantize
Base image: nvidia/cuda:12.4.1-devel-ubuntu22.04 + autoawq + llama.cpp tools
GPU: required for AWQ calibration; GGUF can run CPU-only but uses same image
Demo runtime: GGUF ~5 min CPU, AWQ ~8 min on H100

Standalone use: user points at a HF model ID or R2 URI — no pipeline required.

Inputs:
  model     — HF model ID (e.g. "Qwen/Qwen3-4B-Instruct") or R2 URI
  method    — "gguf" | "awq"
  precision — GGUF only: "q4_k_m" | "q5_k_m" | "q8_0" (default: q4_k_m)
  bits      — AWQ only: int (default: 4)
  hf_token  — optional HuggingFace token for gated models

Outputs:
  gguf_file  — R2 URI (when method=gguf)
  awq_model  — R2 URI (when method=awq)

LLAMA_CPP_DIR env var must point to a llama.cpp checkout with built binaries.
The Dockerfile sets LLAMA_CPP_DIR=/opt/llama.cpp and builds llama-quantize.
"""

import os
import subprocess
from pathlib import Path

from orchapod import io, log


LLAMA_CPP_DIR = Path(os.environ.get("LLAMA_CPP_DIR", "/opt/llama.cpp"))


def resolve_model(model_input: str, hf_token: str | None) -> Path:
    """Download model to local workspace. Returns local directory path."""
    dest = Path("/workspace/model")

    if model_input.startswith("r2://"):
        log.info(f"Downloading model from R2: {model_input}")
        return io.download_input(model_input, dest)

    # HuggingFace model ID — strip optional hf:// prefix
    model_id = model_input.removeprefix("hf://")
    log.info(f"Downloading model from HuggingFace Hub: {model_id}")
    from huggingface_hub import snapshot_download
    snapshot_download(
        repo_id=model_id,
        local_dir=str(dest),
        token=hf_token or None,
        ignore_patterns=["*.msgpack", "*.h5", "flax_model*", "rust_model*"],
    )
    return dest


def quantize_gguf(model_path: Path, precision: str) -> Path:
    """Convert HF model → GGUF using llama.cpp tools."""
    convert_script = LLAMA_CPP_DIR / "convert_hf_to_gguf.py"
    quantize_bin   = LLAMA_CPP_DIR / "build" / "bin" / "llama-quantize"

    if not convert_script.exists():
        raise RuntimeError(
            f"llama.cpp convert script not found at {convert_script}. "
            "Ensure LLAMA_CPP_DIR points to a valid llama.cpp checkout."
        )
    if not quantize_bin.exists():
        raise RuntimeError(
            f"llama-quantize binary not found at {quantize_bin}. "
            "Build llama.cpp with: cmake --build build -t llama-quantize"
        )

    gguf_fp16  = Path("/workspace/model_fp16.gguf")
    gguf_quant = Path(f"/workspace/model_{precision}.gguf")

    log.info("Step 1/2: Converting HF model to GGUF (fp16)")
    subprocess.run(
        ["python", str(convert_script), str(model_path),
         "--outfile", str(gguf_fp16), "--outtype", "f16"],
        check=True,
    )
    log.info(f"fp16 GGUF written: {gguf_fp16} ({gguf_fp16.stat().st_size / 1e9:.2f} GB)")

    log.info(f"Step 2/2: Quantizing to {precision.upper()}")
    subprocess.run(
        [str(quantize_bin), str(gguf_fp16), str(gguf_quant), precision.upper()],
        check=True,
    )
    size_gb = gguf_quant.stat().st_size / 1e9
    log.info(f"Quantized GGUF ready: {gguf_quant} ({size_gb:.2f} GB)")
    return gguf_quant


def quantize_awq(model_path: Path, bits: int) -> Path:
    """Quantize model to AWQ format using AutoAWQ."""
    from awq import AutoAWQForCausalLM
    from transformers import AutoTokenizer

    log.info(f"Loading model for AWQ {bits}-bit calibration")
    model     = AutoAWQForCausalLM.from_pretrained(str(model_path), safetensors=True)
    tokenizer = AutoTokenizer.from_pretrained(str(model_path))

    quant_config = {
        "zero_point": True,
        "q_group_size": 128,
        "w_bit": bits,
        "version": "GEMM",
    }
    log.info(f"Running AWQ calibration (q_group_size=128, w_bit={bits})")
    model.quantize(tokenizer, quant_config=quant_config)

    awq_path = Path("/workspace/awq_model")
    model.save_quantized(str(awq_path))
    tokenizer.save_pretrained(str(awq_path))
    log.info(f"AWQ model saved: {awq_path}")
    return awq_path


def main():
    inputs    = io.read_inputs()
    model_uri = inputs["model"]
    method    = inputs.get("method", "gguf")
    precision = inputs.get("precision", "q4_k_m")
    bits      = int(inputs.get("bits", 4))
    hf_token  = inputs.get("hf_token")

    log.info(f"quantize starting — method={method}, model={model_uri}")

    model_path = resolve_model(model_uri, hf_token)
    log.info(f"Model ready at {model_path}")

    if method == "gguf":
        output_path = quantize_gguf(model_path, precision)
        io.write_output(
            "gguf_file", output_path, kind="model",
            metadata={"format": "gguf", "precision": precision, "source": model_uri},
        )
    elif method == "awq":
        output_path = quantize_awq(model_path, bits)
        io.write_output(
            "awq_model", output_path, kind="model",
            metadata={"format": "awq", "bits": bits, "source": model_uri},
        )
    else:
        raise ValueError(f"Unknown method '{method}'. Use 'gguf' or 'awq'.")

    log.info("quantize complete")


if __name__ == "__main__":
    main()
