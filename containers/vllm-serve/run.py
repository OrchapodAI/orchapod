"""
containers/vllm-serve/run.py

Node: vllm-serve
Base image: vllm/vllm-openai:latest
GPU: 1x H100 80GB
LONG-RUNNING: pod stays alive after container exits (keep_alive_min TTL)

Inputs:
  model          — HF or AWQ model URI (R2 or HF hub)
  max_model_len  — context length (default: 8192)
  keep_alive_min — how long to keep the pod alive (default: 60)

Outputs:
  endpoint_url   — public OpenAI-compatible URL (e.g. https://xyz.orchapod.dev/v1)
  openai_api_key — generated bearer token

Demo behavior:
  - Serves for keep_alive_min minutes, then control plane terminates the pod
  - Canvas shows a "Try it" panel with a live chat box hitting this endpoint
"""

import json
import os
import secrets
import subprocess
import time
import urllib.request
from pathlib import Path

from orchapod import io, log


def generate_api_key() -> str:
    return f"orchapod-{secrets.token_urlsafe(32)}"


def register_ttl_alarm(endpoint_url: str, keep_alive_min: int) -> None:
    """Notify control plane to terminate this pod after keep_alive_min minutes."""
    control_url = os.environ.get("ORCHAPOD_CONTROL_URL")
    if not control_url:
        return
    run_id  = os.environ["ORCHAPOD_RUN_ID"]
    node_id = os.environ["ORCHAPOD_NODE_ID"]
    payload = json.dumps({
        "run_id": run_id,
        "node_id": node_id,
        "action": "register_ttl",
        "keep_alive_min": keep_alive_min,
        "endpoint_url": endpoint_url,
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

    model_uri      = inputs["model"]
    max_model_len  = int(inputs.get("max_model_len", 8192))
    keep_alive_min = int(inputs.get("keep_alive_min", 60))

    # Download model from R2 if it's an R2 URI
    if model_uri.startswith("r2://"):
        log.info(f"Downloading model from R2: {model_uri}")
        model_path = io.download_input(model_uri, "/workspace/model")
        model_arg = str(model_path)
    else:
        model_arg = model_uri   # HF hub ID

    api_key = generate_api_key()

    log.info(f"Starting vLLM server (max_model_len={max_model_len})")
    proc = subprocess.Popen([
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--model", model_arg,
        "--port", "8000",
        "--host", "0.0.0.0",
        "--max-model-len", str(max_model_len),
        "--api-key", api_key,
        "--dtype", "bfloat16",
        "--enable-lora",       # multi-LoRA support (V1)
    ])

    # Wait for server ready
    for _ in range(120):
        try:
            urllib.request.urlopen("http://localhost:8000/health", timeout=2)
            log.info("vLLM server is ready")
            break
        except Exception:
            time.sleep(2)
    else:
        raise RuntimeError("vLLM server failed to start after 240 seconds")

    # Determine public URL (RunPod exposes pod_id.proxy.runpod.net:8000)
    pod_id = os.environ.get("RUNPOD_POD_ID", "local")
    public_url = f"https://{pod_id}-8000.proxy.runpod.net/v1"
    log.info(f"Endpoint URL: {public_url}")

    # Write outputs (this makes the endpoint URL visible in the run viewer)
    endpoint_path = io.local_path("endpoint.json")
    with open(endpoint_path, "w") as f:
        json.dump({"endpoint_url": public_url, "openai_api_key": api_key,
                   "model": model_arg, "max_model_len": max_model_len}, f)

    io.write_output("endpoint_url",    endpoint_path, kind="endpoint",
                    metadata={"url": public_url, "model": model_arg})
    io.write_output("openai_api_key",  endpoint_path, kind="endpoint",
                    metadata={"api_key": api_key})

    # Register TTL alarm with control plane
    register_ttl_alarm(public_url, keep_alive_min)
    log.info(f"Pod will auto-terminate in {keep_alive_min} minutes")

    # Keep the container alive (vLLM server runs in background)
    proc.wait()
    log.info("vllm-serve exiting")


if __name__ == "__main__":
    main()
