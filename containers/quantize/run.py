"""
containers/quantize/run.py

Node: quantize
GPU: AWQ needs 1x H100 for calibration; GGUF is CPU-only

Inputs:
  model     — HF model ID (e.g. Qwen/Qwen3-4B-Instruct) or R2 URI to HF dir
  method    — "gguf" | "awq"
  precision — GGUF only: "q4_k_m" | "q5_k_m" | "q8_0" (default: q4_k_m)
  bits      — AWQ only: int (default: 4)
  hf_token  — optional HuggingFace token for private models

Outputs:
  gguf_file  — R2 URI (when method=gguf)
  awq_model  — R2 URI (when method=awq)

Environment:
  LLAMA_CPP_DIR — path to llama.cpp checkout (default: /opt/llama.cpp)
                  Must contain convert_hf_to_gguf.py and build/bin/llama-quantize
"""

import os
import subprocess
from pathlib import Path

from orchapod import io, log

LLAMA_CPP_DIR  = Path(os.environ.get("LLAMA_CPP_DIR", "/opt/llama.cpp"))
WORKSPACE_DIR  = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))


def resolve_model(model_input: str, hf_token: str | None) -> Path:
    """Download model from R2 or HuggingFace hub to /workspace/model."""
    dest = WORKSPACE_DIR / "model"
    if model_input.startswith("r2://"):
        log.info(f"Downloading model from R2: {model_input}")
        return io.download_input(model_input, dest)

    model_id = model_input.removeprefix("hf://")
    log.info(f"Downloading model from HuggingFace: {model_id}")
    from huggingface_hub import snapshot_download
    snapshot_download(
        repo_id=model_id,
        local_dir=str(dest),
        token=hf_token or None,
        ignore_patterns=["*.msgpack", "flax_model*", "tf_model*"],
    )
    return dest


def quantize_gguf(model_path: Path, precision: str) -> Path:
    """Convert HF model to GGUF using llama.cpp tools."""
    convert_script = LLAMA_CPP_DIR / "convert_hf_to_gguf.py"
    quantize_bin   = LLAMA_CPP_DIR / "build" / "bin" / "llama-quantize"

    if not convert_script.exists():
        raise RuntimeError(
            f"llama.cpp convert script not found at {convert_script}. "
            f"Set LLAMA_CPP_DIR or rebuild the Docker image."
        )
    if not quantize_bin.exists():
        raise RuntimeError(
            f"llama-quantize binary not found at {quantize_bin}. "
            f"Build llama.cpp with: cmake --build build --target llama-quantize"
        )

    log.info(f"Converting to GGUF f16 using {convert_script}")
    gguf_fp16 = WORKSPACE_DIR / "model_fp16.gguf"
    subprocess.run(
        ["python", str(convert_script), str(model_path),
         "--outfile", str(gguf_fp16), "--outtype", "f16"],
        check=True,
    )

    log.info(f"Quantizing to {precision.upper()}")
    gguf_quant = WORKSPACE_DIR / f"model_{precision}.gguf"
    subprocess.run(
        [str(quantize_bin), str(gguf_fp16), str(gguf_quant), precision.upper()],
        check=True,
    )

    log.info(f"GGUF done: {gguf_quant} ({gguf_quant.stat().st_size / 1e9:.2f} GB)")
    return gguf_quant


def quantize_awq(model_path: Path, bits: int) -> Path:
    """Quantize to AWQ using AutoAWQ."""
    log.info(f"Quantizing to AWQ {bits}-bit")
    from awq import AutoAWQForCausalLM
    from transformers import AutoTokenizer

    model     = AutoAWQForCausalLM.from_pretrained(str(model_path))
    tokenizer = AutoTokenizer.from_pretrained(str(model_path))

    quant_config = {"zero_point": True, "q_group_size": 128, "w_bit": bits, "version": "GEMM"}
    model.quantize(tokenizer, quant_config=quant_config)

    awq_path = Path("/workspace/awq_model")
    model.save_quantized(str(awq_path))
    tokenizer.save_pretrained(str(awq_path))

    log.info(f"AWQ done: {awq_path}")
    return awq_path


def main():
    inputs    = io.read_inputs()
    model_uri = inputs["model"]
    method    = inputs.get("method", "gguf")
    precision = inputs.get("precision", "q4_k_m")
    bits      = int(inputs.get("bits", 4))
    hf_token  = inputs.get("hf_token") or os.environ.get("HF_TOKEN")

    log.info("quantize starting")
    model_path = resolve_model(model_uri, hf_token)

    if method == "gguf":
        output_path = quantize_gguf(model_path, precision)
        io.write_output("gguf_file", output_path, kind="model",
                        metadata={"format": "gguf", "precision": precision})
    elif method == "awq":
        output_path = quantize_awq(model_path, bits)
        io.write_output("awq_model", output_path, kind="model",
                        metadata={"format": "awq", "bits": bits})
    else:
        raise ValueError(f"Unknown quantize method: {method}. Use 'gguf' or 'awq'.")

    log.info("quantize complete")


if __name__ == "__main__":
    main()
