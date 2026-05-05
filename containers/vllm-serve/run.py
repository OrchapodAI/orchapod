"""
containers/vllm-serve/run.py

Node: vllm-serve
Base image: vllm/vllm-openai:latest
GPU: 1x H100 80GB
LONG-RUNNING: pod stays alive after main() returns (keep_alive_min TTL)

Standalone use: user points at a HF model ID or R2 URI and gets back an
OpenAI-compatible endpoint. No other nodes required.

Inputs:
  model                — HF model ID or R2 URI of a merged/AWQ model
  served_model_name    — name clients use in API calls (default: derived from model)
  max_model_len        — context length (default: 8192)
  gpu_memory_utilization — fraction of GPU memory to use (default: 0.90)
  keep_alive_min       — how long to keep the pod alive (default: 60)
  hf_token             — optional HuggingFace token for gated models
  dtype                — "bfloat16" | "float16" | "auto" (default: bfloat16)

Outputs:
  endpoint_url   — public OpenAI-compatible URL (e.g. https://xyz.proxy.runpod.net/v1)
  openai_api_key — generated bearer token for this endpoint

Public URL resolution order:
  1. ORCHAPOD_PUBLIC_URL  — injected by control plane (most reliable)
  2. RUNPOD_POD_ID        — RunPod proxy format
  3. PUBLIC_IPADDR        — Vast.ai / bare-metal: ip + VAST_TCP_PORT_8000
  4. localhost            — local dev / testing fallback
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


def resolve_model(model_input: str, hf_token: str | None) -> str:
    """
    Returns the argument to pass to vLLM --model.
    HF model IDs are passed through; R2 URIs are downloaded first.
    """
    if model_input.startswith("r2://"):
        log.info(f"Downloading model from R2: {model_input}")
        local = io.download_input(model_input, "/workspace/model")
        return str(local)

    model_id = model_input.removeprefix("hf://")
    log.info(f"Using HuggingFace model: {model_id}")
    return model_id


def detect_public_url() -> str:
    """Resolve the externally reachable URL for this pod's vLLM server."""
    # Control plane override (set by executor when it knows the pod's URL)
    if os.environ.get("ORCHAPOD_PUBLIC_URL"):
        return os.environ["ORCHAPOD_PUBLIC_URL"]

    # RunPod: proxy URL is deterministic from pod_id
    pod_id = os.environ.get("RUNPOD_POD_ID")
    if pod_id:
        return f"https://{pod_id}-{_PORT}.proxy.runpod.net/v1"

    # Vast.ai: public IP + TCP port mapped by the platform
    public_ip   = os.environ.get("PUBLIC_IPADDR")
    public_port = os.environ.get(f"VAST_TCP_PORT_{_PORT}", str(_PORT))
    if public_ip:
        return f"http://{public_ip}:{public_port}/v1"

    return f"http://localhost:{_PORT}/v1"


def wait_for_vllm(timeout_s: int = 300) -> None:
    health_url = f"http://localhost:{_PORT}/health"
    deadline   = time.time() + timeout_s
    while time.time() < deadline:
        try:
            urllib.request.urlopen(health_url, timeout=3)
            return
        except Exception:
            time.sleep(3)
    raise RuntimeError(f"vLLM server did not become healthy within {timeout_s}s")


def register_ttl_alarm(endpoint_url: str, keep_alive_min: int) -> None:
    control_url = os.environ.get("ORCHAPOD_CONTROL_URL")
    if not control_url:
        return
    payload = json.dumps({
        "run_id":         os.environ["ORCHAPOD_RUN_ID"],
        "node_id":        os.environ["ORCHAPOD_NODE_ID"],
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

    model_input  = inputs["model"]
    max_model_len = int(inputs.get("max_model_len", 8192))
    gpu_mem_util  = float(inputs.get("gpu_memory_utilization", 0.90))
    keep_alive    = int(inputs.get("keep_alive_min", 60))
    hf_token      = inputs.get("hf_token")
    dtype         = inputs.get("dtype", "bfloat16")

    model_arg = resolve_model(model_input, hf_token)

    # served_model_name defaults to the last path component for cleaner API calls
    default_name = Path(model_arg).name if "/" in model_arg or model_arg.startswith("/") else model_arg
    served_name  = inputs.get("served_model_name", default_name)

    api_key = f"orchapod-{secrets.token_urlsafe(32)}"

    log.info(f"vllm-serve starting — model={model_arg}, served_as={served_name}")

    env = dict(os.environ)
    if hf_token:
        env["HF_TOKEN"] = hf_token
        env["HUGGING_FACE_HUB_TOKEN"] = hf_token

    cmd = [
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--model",                  model_arg,
        "--served-model-name",      served_name,
        "--port",                   str(_PORT),
        "--host",                   "0.0.0.0",
        "--max-model-len",          str(max_model_len),
        "--gpu-memory-utilization", str(gpu_mem_util),
        "--api-key",                api_key,
        "--dtype",                  dtype,
        "--enable-lora",
    ]

    log.info(f"Launching vLLM: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, env=env)

    log.info("Waiting for vLLM to become healthy...")
    wait_for_vllm(timeout_s=300)
    log.info("vLLM server is ready")

    public_url = detect_public_url()
    log.info(f"Endpoint: {public_url}  (model name in API: {served_name})")

    endpoint_path = io.local_path("endpoint.json")
    with open(endpoint_path, "w") as f:
        json.dump({
            "endpoint_url":   public_url,
            "openai_api_key": api_key,
            "model":          model_arg,
            "served_model_name": served_name,
            "max_model_len":  max_model_len,
        }, f, indent=2)

    io.write_output("endpoint_url",   endpoint_path, kind="endpoint",
                    metadata={"url": public_url, "model": served_name})
    io.write_output("openai_api_key", endpoint_path, kind="endpoint",
                    metadata={"api_key": api_key})

    register_ttl_alarm(public_url, keep_alive)
    log.info(f"Pod will auto-terminate in {keep_alive} minutes")

    proc.wait()
    log.info("vllm-serve exiting")


if __name__ == "__main__":
    main()
