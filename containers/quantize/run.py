"""
containers/quantize/run.py

Node: quantize
Base image: python:3.12 + llama-cpp-python[server] + autoawq
GPU: AWQ needs 1x H100 for calibration; GGUF is CPU-only
Demo runtime: GGUF ~5 min CPU, AWQ ~8 min on H100

Inputs:
  model     — R2 URI to HF format model directory
  method    — "gguf" | "awq"
  precision — GGUF only: "q4_k_m" | "q5_k_m" | "q8_0" (default: q4_k_m)
  bits      — AWQ only: int (default: 4)

Outputs:
  gguf_file  — R2 URI (when method=gguf)
  awq_model  — R2 URI (when method=awq)
"""

import subprocess
from pathlib import Path

from orchapod import io, log


def quantize_gguf(model_path: Path, precision: str) -> Path:
    """Convert to GGUF using llama.cpp tools."""
    log.info(f"Converting to GGUF with precision {precision}")
    gguf_fp16 = Path("/workspace/model_fp16.gguf")
    # Step 1: convert HF → GGUF f16
    subprocess.run([
        "python", "-m", "llama_cpp.llama_cpp.scripts.convert_hf_to_gguf",
        str(model_path), "--outfile", str(gguf_fp16), "--outtype", "f16",
    ], check=True)

    # Step 2: quantize to target precision
    gguf_quant = Path(f"/workspace/model_{precision}.gguf")
    subprocess.run([
        "llama-quantize", str(gguf_fp16), str(gguf_quant), precision.upper(),
    ], check=True)

    log.info(f"GGUF quantization complete: {gguf_quant} ({gguf_quant.stat().st_size / 1e9:.2f} GB)")
    return gguf_quant


def quantize_awq(model_path: Path, bits: int) -> Path:
    """Quantize to AWQ using AutoAWQ."""
    log.info(f"Quantizing to AWQ {bits}-bit")
    from awq import AutoAWQForCausalLM
    from transformers import AutoTokenizer

    model = AutoAWQForCausalLM.from_pretrained(str(model_path))
    tokenizer = AutoTokenizer.from_pretrained(str(model_path))

    quant_config = {"zero_point": True, "q_group_size": 128, "w_bit": bits, "version": "GEMM"}
    model.quantize(tokenizer, quant_config=quant_config)

    awq_path = Path("/workspace/awq_model")
    model.save_quantized(str(awq_path))
    tokenizer.save_pretrained(str(awq_path))

    log.info(f"AWQ quantization complete: {awq_path}")
    return awq_path


def main():
    inputs = io.read_inputs()
    log.info("quantize starting")

    model_uri = inputs["model"]
    method    = inputs.get("method", "gguf")
    precision = inputs.get("precision", "q4_k_m")
    bits      = int(inputs.get("bits", 4))

    log.info(f"Downloading model from R2: {model_uri}")
    model_path = io.download_input(model_uri, "/workspace/model")

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
