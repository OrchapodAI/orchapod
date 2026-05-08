"""
containers/vllm-serve/run.py

Node: vllm-serve
Base image: vllm/vllm-openai:latest
GPU: 1x H100 80GB
LONG-RUNNING: pod stays alive for keep_alive_min minutes after server is ready.

Inputs:
  model                  — HF model ID or R2 URI to AWQ model dir
  max_model_len          — context length (default: 8192)
  keep_alive_min         — how long to keep pod alive (default: 60)
  served_model_name      — override name returned in /v1/models (optional)
  gpu_memory_utilization — fraction of GPU VRAM to use (default: 0.90)
  dtype                  — "bfloat16" | "float16" | "auto" (default: bfloat16)
  hf_token               — HuggingFace token for private models (optional)

Outputs (registered via /internal/ttl):
  endpoint_url   — public OpenAI-compatible URL
  openai_api_key — bearer token
"""

import json
import os
import secrets
import subprocess
import time
import urllib.request
from pathlib import Path

from orchapod import io, log

_PORT = 8000


def generate_api_key() -> str:
    return f"orchapod-{secrets.token_urlsafe(32)}"


def detect_public_url() -> str:
    """Detect the public URL for this pod across providers."""
    # Explicit override (CI, custom domains)
    if os.environ.get("ORCHAPOD_PUBLIC_URL"):
        return os.environ["ORCHAPOD_PUBLIC_URL"]
    # RunPod: stable proxy URL
    pod_id = os.environ.get("RUNPOD_POD_ID")
    if pod_id:
        return f"https://{pod_id}-{_PORT}.proxy.runpod.net/v1"
    # Vast.ai: exposes PUBLIC_IPADDR + VAST_TCP_PORT_{port}
    public_ip   = os.environ.get("PUBLIC_IPADDR")
    public_port = os.environ.get(f"VAST_TCP_PORT_{_PORT}", str(_PORT))
    if public_ip:
        return f"http://{public_ip}:{public_port}/v1"
    # Local / unknown
    return f"http://localhost:{_PORT}/v1"


def resolve_model(model_input: str, hf_token: str | None) -> str:
    """Return a vLLM-compatible model path or HF ID."""
    if model_input.startswith("r2://"):
        log.info(f"Downloading model from R2: {model_input}")
        dest = io.download_input(model_input, Path("/workspace/model"))
        return str(dest)
    return model_input.removeprefix("hf://")


def register_ttl_alarm(endpoint_url: str, keep_alive_min: int) -> None:
    """Notify control plane to terminate this pod after keep_alive_min minutes."""
    control_url = os.environ.get("ORCHAPOD_CONTROL_URL")
    if not control_url:
        log.info("ORCHAPOD_CONTROL_URL not set — skipping TTL registration")
        return
    run_id  = os.environ["ORCHAPOD_RUN_ID"]
    node_id = os.environ["ORCHAPOD_NODE_ID"]
    payload = json.dumps({
        "run_id":         run_id,
        "node_id":        node_id,
        "action":         "register_ttl",
        "keep_alive_min": keep_alive_min,
        "endpoint_url":   endpoint_url,
    }).encode()
    req = urllib.request.Request(
        f"{control_url}/internal/ttl",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)


def main():
    inputs = io.read_inputs()
    log.info("vllm-serve starting")

    model_input            = inputs["model"]
    max_model_len          = int(inputs.get("max_model_len", 8192))
    keep_alive_min         = int(inputs.get("keep_alive_min", 60))
    served_model_name      = inputs.get("served_model_name")
    gpu_memory_utilization = float(inputs.get("gpu_memory_utilization", 0.90))
    dtype                  = inputs.get("dtype", "bfloat16")
    hf_token               = inputs.get("hf_token") or os.environ.get("HF_TOKEN")

    model_arg = resolve_model(model_input, hf_token)
    api_key   = generate_api_key()

    cmd = [
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--model", model_arg,
        "--port", str(_PORT),
        "--host", "0.0.0.0",
        "--max-model-len", str(max_model_len),
        "--api-key", api_key,
        "--dtype", dtype,
        "--gpu-memory-utilization", str(gpu_memory_utilization),
    ]
    if served_model_name:
        cmd += ["--served-model-name", served_model_name]

    env = dict(os.environ)
    if hf_token:
        env["HF_TOKEN"] = hf_token

    log.info(f"Starting vLLM server (model={model_arg}, max_model_len={max_model_len})")
    proc = subprocess.Popen(cmd, env=env)

    # Wait for server ready (up to 240 s)
    for _ in range(120):
        try:
            urllib.request.urlopen(f"http://localhost:{_PORT}/health", timeout=2)
            log.info("vLLM server is ready")
            break
        except Exception:
            time.sleep(2)
    else:
        proc.kill()
        raise RuntimeError("vLLM server failed to start after 240 seconds")

    public_url = detect_public_url()
    log.info(f"Endpoint URL: {public_url}")

    # Write outputs so they appear in the run viewer immediately
    io.write_output("endpoint_url",   public_url,  kind="endpoint",
                    metadata={"url": public_url, "model": model_arg})
    io.write_output("openai_api_key", api_key,     kind="endpoint",
                    metadata={"api_key": api_key})

    # Register TTL alarm — control plane will terminate pod after N minutes
    register_ttl_alarm(public_url, keep_alive_min)
    log.info(f"Pod will auto-terminate in {keep_alive_min} minutes")

    proc.wait()
    log.info("vllm-serve exiting")


if __name__ == "__main__":
    main()
