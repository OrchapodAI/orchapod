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
  endpoint_url   — public OpenAI-compatible base URL (https://... /v1)
  openai_api_key — bearer token

Cloudflare Tunnel (KAN-28):
  If CLOUDFLARE_TUNNEL_TOKEN is set  → named tunnel → https://{run_id}.endpoints.orchapod.dev
  Otherwise                          → quick tunnel → https://<random>.trycloudflare.com
  Falls back to raw IP/RunPod URL if cloudflared is not installed or times out.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from subprocess import PIPE, STDOUT
from typing import Optional

from orchapod import io, log

_PORT = 8000
_TUNNEL_TIMEOUT = 90  # seconds to wait for tunnel URL


def generate_api_key() -> str:
    return f"orchapod-{secrets.token_urlsafe(32)}"


# ── Cloudflare Tunnel ─────────────────────────────────────────────────────────

def start_cloudflare_tunnel(port: int) -> tuple[Optional[str], Optional[subprocess.Popen]]:
    """
    Start a Cloudflare Tunnel and return (public_url, process).

    Quick tunnel  (no account):  cloudflared tunnel --url http://localhost:<port>
    Named tunnel  (with token):  cloudflared tunnel run --token <token>

    Returns (None, None) if cloudflared is not available or URL cannot be found.
    """
    # Check cloudflared is installed
    try:
        subprocess.run(["cloudflared", "--version"], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.CalledProcessError):
        log.info("cloudflared not found — skipping Cloudflare Tunnel")
        return None, None

    tunnel_token = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN")
    if tunnel_token:
        # Named tunnel — token already encodes which tunnel to run
        cmd = ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token", tunnel_token]
        log.info("Starting Cloudflare named tunnel")
    else:
        # Quick tunnel — free *.trycloudflare.com URL
        cmd = ["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"]
        log.info("Starting Cloudflare quick tunnel (*.trycloudflare.com)")

    proc = subprocess.Popen(cmd, stdout=PIPE, stderr=STDOUT, text=True, bufsize=1)

    found_url: list[str] = []

    def _reader():
        # Patterns to detect the public URL in cloudflared output
        quick_re = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
        named_ready_re = re.compile(r"Registered tunnel connection|INF.*connection.*registered", re.IGNORECASE)

        run_id = os.environ.get("ORCHAPOD_RUN_ID", "")

        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.rstrip()
            if line:
                log.info(f"[cloudflared] {line}")

            if not found_url:
                # Quick tunnel: URL printed directly
                m = quick_re.search(line)
                if m:
                    found_url.append(m.group(0))
                    return

                # Named tunnel: URL is deterministic once connection is registered
                if tunnel_token and named_ready_re.search(line):
                    if run_id:
                        found_url.append(f"https://{run_id}.endpoints.orchapod.dev")
                    else:
                        # Fallback: extract from token if possible
                        found_url.append("https://endpoints.orchapod.dev")
                    return

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()
    reader_thread.join(timeout=_TUNNEL_TIMEOUT)

    if found_url:
        log.info(f"Cloudflare Tunnel URL: {found_url[0]}")
        return found_url[0], proc
    else:
        log.info("Timed out waiting for Cloudflare Tunnel URL — falling back to raw URL")
        proc.terminate()
        return None, None


# ── Raw / provider URL fallback ───────────────────────────────────────────────

def detect_raw_url(port: int = _PORT) -> str:
    """Detect the raw (non-tunnel) public URL for this pod across providers."""
    # Explicit override (CI, custom domains)
    if os.environ.get("ORCHAPOD_PUBLIC_URL"):
        return os.environ["ORCHAPOD_PUBLIC_URL"]
    # RunPod: stable proxy URL
    pod_id = os.environ.get("RUNPOD_POD_ID")
    if pod_id:
        return f"https://{pod_id}-{port}.proxy.runpod.net"
    # Vast.ai: exposes PUBLIC_IPADDR + VAST_TCP_PORT_{port}
    public_ip   = os.environ.get("PUBLIC_IPADDR")
    public_port = os.environ.get(f"VAST_TCP_PORT_{port}", str(port))
    if public_ip:
        return f"http://{public_ip}:{public_port}"
    # Local / unknown
    return f"http://localhost:{port}"


# ── Model resolution ──────────────────────────────────────────────────────────

def resolve_model(model_input: str, hf_token: str | None) -> str:
    """Return a vLLM-compatible model path or HF ID."""
    if model_input.startswith("r2://"):
        log.info(f"Downloading model from R2: {model_input}")
        dest = io.download_input(model_input, Path("/workspace/model"))
        return str(dest)
    return model_input.removeprefix("hf://")


# ── TTL registration ──────────────────────────────────────────────────────────

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


# ── Main ──────────────────────────────────────────────────────────────────────

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
    vllm_proc = subprocess.Popen(cmd, env=env)

    # Wait for server ready (up to 240 s)
    for _ in range(120):
        try:
            urllib.request.urlopen(f"http://localhost:{_PORT}/health", timeout=2)
            log.info("vLLM server is ready")
            break
        except Exception:
            time.sleep(2)
    else:
        vllm_proc.kill()
        raise RuntimeError("vLLM server failed to start after 240 seconds")

    # ── Establish public URL ──────────────────────────────────────────────────
    tunnel_url, tunnel_proc = start_cloudflare_tunnel(_PORT)

    if tunnel_url:
        public_base = tunnel_url.rstrip("/")
    else:
        public_base = detect_raw_url(_PORT)

    openai_base_url = public_base + "/v1"
    log.info(f"Public endpoint base URL: {openai_base_url}")

    # Write outputs so they appear in the run viewer immediately
    io.write_output("endpoint_url",   openai_base_url, kind="endpoint",
                    metadata={"url": openai_base_url, "model": model_arg})
    io.write_output("openai_api_key", api_key,          kind="endpoint",
                    metadata={"api_key": api_key})

    # Register TTL alarm — control plane will terminate pod after N minutes
    register_ttl_alarm(openai_base_url, keep_alive_min)
    log.info(f"Pod will auto-terminate in {keep_alive_min} minutes")

    # Wait for vLLM to exit (pod terminated by TTL or external signal)
    vllm_proc.wait()

    # Clean up tunnel
    if tunnel_proc and tunnel_proc.poll() is None:
        tunnel_proc.terminate()

    log.info("vllm-serve exiting")


if __name__ == "__main__":
    main()
