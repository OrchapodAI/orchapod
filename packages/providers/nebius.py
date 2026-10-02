"""
packages/providers/nebius.py

Nebius AI Cloud GPU provider — H100 instances on Nebius infrastructure.

Nebius Compute API docs: https://nebius.com/docs/compute/
Authentication: IAM token via NEBIUS_IAM_TOKEN env var
               Service account key via NEBIUS_SA_KEY_FILE env var

Instance lifecycle:
  POST /instances                → create + start
  GET  /instances/{id}           → poll status until "RUNNING"
  POST /instances/{id}:stop      → stop
  DELETE /instances/{id}         → delete

Token Factory (OpenAI-compat inference):
  Base URL: https://api.studio.nebius.ai/v1
  Auth: Bearer NEBIUS_API_KEY

GPU naming: Nebius uses platform + GPU type (h100-sxm, a100-sxm).
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import AsyncIterator

import httpx

from .base import GPUProvider, GPUSpec, Quote, Pod, ProvisionError

# Nebius Compute REST API (eu-north1 is the primary GPU region)
_COMPUTE_BASE = "https://compute.api.eu-north1.nebius.cloud/compute/v1"
_IAM_BASE     = "https://iam.api.eu-north1.nebius.cloud/iam/v1"

# Nebius Token Factory (OpenAI-compatible inference API)
NEBIUS_API_BASE = "https://api.studio.nebius.ai/v1"

# GPU type mappings: canonical → Nebius platform string
_GPU_MAP: dict[str, str] = {
    "H100":      "gpu-h100-sxm",
    "H100_SXM":  "gpu-h100-sxm",
    "H200":      "gpu-h200-sxm",
    "A100":      "gpu-a100",
    "A100_80GB": "gpu-a100",
    "4090":      "gpu-l40s",   # closest Nebius consumer-class GPU
}

# Approximate on-demand prices USD/hr (eu-north1, 2026)
_PRICES: dict[str, float] = {
    "gpu-h100-sxm": 2.49,
    "gpu-h200-sxm": 3.10,
    "gpu-a100":     1.89,
    "gpu-l40s":     0.99,
}

# Disk image — Nebius-maintained PyTorch image with CUDA drivers
_DEFAULT_IMAGE = "projects/nebius-public/images/pytorch-2-3-cuda-12-1"

_PROVISION_TIMEOUT = 600   # seconds


def _iam_token() -> str:
    token = os.environ.get("NEBIUS_IAM_TOKEN", "")
    if not token:
        raise ProvisionError(
            "NEBIUS_IAM_TOKEN is not set. "
            "Generate one via: nebius iam get-access-token"
        )
    return token


def _folder_id() -> str:
    fid = os.environ.get("NEBIUS_FOLDER_ID", "")
    if not fid:
        raise ProvisionError("NEBIUS_FOLDER_ID is not set. Find it in the Nebius console.")
    return fid


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_iam_token()}",
        "Content-Type": "application/json",
    }


class NebiusProvider:
    """Nebius AI Cloud GPU provider."""

    name = "nebius"

    async def quote(self, gpu_spec: GPUSpec) -> Quote:
        gpu_platform = _GPU_MAP.get(gpu_spec.gpu_type, "gpu-h100-sxm")
        price = _PRICES.get(gpu_platform, 2.49)
        # Nebius H100 instances are generally available in eu-north1
        return Quote(
            provider="nebius",
            price_per_hour=price * gpu_spec.count,
            available=True,
            gpu_type=gpu_platform,
            region="eu-north1",
            note="Nebius AI Cloud · eu-north1",
        )

    async def provision(
        self,
        gpu_spec: GPUSpec,
        image: str,
        env: dict[str, str],
        ports: list[int] = [],
    ) -> Pod:
        gpu_platform = _GPU_MAP.get(gpu_spec.gpu_type, "gpu-h100-sxm")
        folder_id    = _folder_id()

        # Build startup script — pulls + runs the container image
        env_exports = "\n".join(f"export {k}={v!r}" for k, v in env.items())
        exposed_ports = " ".join(f"-p {p}:{p}" for p in ports)
        startup_script = f"""#!/bin/bash
set -e
{env_exports}

# Install Docker if not present
which docker || (curl -fsSL https://get.docker.com | sh)

# Pull and run the Orchapod container
docker pull {image}
docker run --rm --gpus all {exposed_ports} \\
  {" ".join(f"-e {k}" for k in env)} \\
  {image}
"""

        payload = {
            "folderId": folder_id,
            "name": f"orchapod-{int(time.time())}",
            "zoneId": "eu-north1-a",
            "platformId": gpu_platform,
            "resourcesSpec": {
                "memory": str(48 * 1024 * 1024 * 1024),  # 48 GB RAM
                "cores": "16",
                "gpus": str(gpu_spec.count),
            },
            "bootDiskSpec": {
                "autoDelete": True,
                "diskSpec": {
                    "size": str(200 * 1024 * 1024 * 1024),  # 200 GB
                    "imageId": _DEFAULT_IMAGE,
                },
            },
            "networkInterfaceSpecs": [
                {
                    "subnetId": os.environ.get("NEBIUS_SUBNET_ID", ""),
                    "primaryV4AddressSpec": {"oneToOneNatSpec": {"ipVersion": "IPV4"}},
                }
            ],
            "metadata": {"user-data": startup_script},
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_COMPUTE_BASE}/instances",
                headers=_headers(),
                json=payload,
            )
            if resp.status_code not in (200, 201):
                raise ProvisionError(
                    f"Nebius instance creation failed: {resp.status_code} {resp.text}"
                )
            data = resp.json()

        # The API returns an Operation; extract the instance id from metadata
        instance_id = (
            data.get("metadata", {}).get("instanceId")
            or data.get("response", {}).get("id")
            or data.get("id", "")
        )
        if not instance_id:
            raise ProvisionError(f"Could not parse instance_id from response: {data}")

        # Poll until RUNNING
        deadline = time.time() + _PROVISION_TIMEOUT
        public_ip = None
        while time.time() < deadline:
            await asyncio.sleep(10)
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{_COMPUTE_BASE}/instances/{instance_id}",
                    headers=_headers(),
                )
            if r.status_code == 200:
                inst = r.json()
                status = inst.get("status", "")
                if status == "RUNNING":
                    ifaces = inst.get("networkInterfaces", [])
                    if ifaces:
                        nat = ifaces[0].get("primaryV4Address", {}).get("oneToOneNat", {})
                        public_ip = nat.get("address")
                    break
                if status in ("ERROR", "CRASHED"):
                    raise ProvisionError(f"Nebius instance entered {status} state")
        else:
            raise ProvisionError("Timed out waiting for Nebius instance to reach RUNNING")

        return Pod(
            provider="nebius",
            pod_id=instance_id,
            public_ip=public_ip,
            public_port=ports[0] if ports else None,
        )

    async def stream_logs(self, pod: Pod) -> AsyncIterator[str]:
        """
        Stream serial port output from the instance via the Nebius serial console API.
        Falls back to polling if the API is unavailable.
        """
        async with httpx.AsyncClient(timeout=60) as client:
            while True:
                try:
                    resp = await client.get(
                        f"{_COMPUTE_BASE}/instances/{pod.pod_id}/serialPortOutput",
                        headers=_headers(),
                    )
                    if resp.status_code == 200:
                        content = resp.json().get("contents", "")
                        for line in content.splitlines():
                            yield line
                except Exception:
                    pass
                await asyncio.sleep(5)

    async def wait(self, pod: Pod) -> int:
        """Poll until the instance stops (container exits → instance shuts down)."""
        deadline = time.time() + 7200  # 2hr hard cap
        while time.time() < deadline:
            await asyncio.sleep(15)
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    r = await client.get(
                        f"{_COMPUTE_BASE}/instances/{pod.pod_id}",
                        headers=_headers(),
                    )
                if r.status_code == 200:
                    status = r.json().get("status", "")
                    if status in ("STOPPED", "TERMINATED"):
                        return 0
                    if status in ("ERROR", "CRASHED"):
                        return 1
            except Exception:
                pass
        return 1  # timed out

    async def terminate(self, pod: Pod) -> None:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                await client.delete(
                    f"{_COMPUTE_BASE}/instances/{pod.pod_id}",
                    headers=_headers(),
                )
        except Exception:
            pass  # best-effort cleanup
