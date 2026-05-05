"""
packages/providers/runpod.py

RunPod GPU provider — primary provider for MVP.
Uses RunPod's Pods API (NOT Serverless — cold-start is unfit for training).

Implementation effort: ~3 days
GPU types in MVP: NVIDIA H100 80GB HBM3
  - Secure cloud: $2.49/hr
  - Community cloud: $1.99/hr

Docs: https://docs.runpod.io/pods/overview
SDK:  pip install runpod
"""

from __future__ import annotations
import asyncio
import os
from typing import AsyncIterator

import runpod  # pip install runpod

from .base import GPUProvider, GPUSpec, Quote, Pod, ProvisionError


# GPU type mapping: our spec → RunPod GPU name
GPU_MAP = {
    "H100": "NVIDIA H100 80GB HBM3",
    "A100": "NVIDIA A100 80GB",
    "4090": "NVIDIA GeForce RTX 4090",
}

# Approximate on-demand prices (update from RunPod API in production)
PRICE_MAP = {
    "NVIDIA H100 80GB HBM3": 2.49,
    "NVIDIA A100 80GB": 1.89,
    "NVIDIA GeForce RTX 4090": 0.69,
}


class RunPodProvider:
    name = "runpod"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ["RUNPOD_API_KEY"]
        runpod.api_key = self.api_key

    async def quote(self, gpu_spec: GPUSpec) -> Quote:
        gpu_name = GPU_MAP.get(gpu_spec.gpu_type, gpu_spec.gpu_type)
        price = PRICE_MAP.get(gpu_name, 9.99)
        # TODO: call RunPod API to check live availability
        return Quote(
            provider=self.name,
            price_per_hour=price,
            available=True,  # TODO: real availability check
            gpu_type=gpu_name,
        )

    async def provision(
        self,
        gpu_spec: GPUSpec,
        image: str,
        env: dict[str, str],
    ) -> Pod:
        gpu_name = GPU_MAP.get(gpu_spec.gpu_type, gpu_spec.gpu_type)
        try:
            pod = runpod.create_pod(
                name="orchapod-node",
                image_name=image,
                gpu_type_id=gpu_name,
                cloud_type="SECURE",          # SECURE for reliability; COMMUNITY for cost
                container_disk_in_gb=100,
                volume_in_gb=100,             # model weight storage
                volume_mount_path="/workspace",
                env=env,
                ports="8000/tcp",             # for vllm-serve
            )
        except Exception as e:
            raise ProvisionError(f"RunPod provision failed: {e}") from e

        return Pod(
            provider=self.name,
            pod_id=pod["id"],
        )

    async def stream_logs(self, pod: Pod) -> AsyncIterator[str]:
        # RunPod does not expose a real-time log stream via the Python SDK.
        # Containers push log lines themselves via POST /internal/log.
        # This method is only called by run_workflow.py (pipeline path), not
        # the standalone path in runs.py, so a no-op is safe for now.
        return
        yield  # make this an async generator

    async def wait(self, pod: Pod) -> int:
        """Poll pod status every 10 s until the container exits. Returns exit code."""
        _TERMINAL = {"EXITED", "DEAD", "TERMINATED"}
        _POLL_INTERVAL = 10

        while True:
            info = runpod.get_pod(pod.pod_id)
            if info is None:
                return 1  # pod disappeared unexpectedly

            status = info.get("desiredStatus", "")
            if status in _TERMINAL:
                runtime   = info.get("runtime") or {}
                container = runtime.get("container") or {}
                exit_code = container.get("exitCode")
                return exit_code if exit_code is not None else 0

            await asyncio.sleep(_POLL_INTERVAL)

    async def terminate(self, pod: Pod) -> None:
        runpod.terminate_pod(pod.pod_id)
