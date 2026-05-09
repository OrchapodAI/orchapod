"""
packages/providers/runpod.py

RunPod GPU provider — primary provider for MVP.
Uses RunPod's Pods API (NOT Serverless — cold-start is unfit for training).

Docs: https://docs.runpod.io/pods/overview
SDK:  pip install runpod
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import AsyncIterator

import httpx
import runpod  # pip install runpod

from .base import GPUProvider, GPUSpec, Quote, Pod, ProvisionError, NoCapacity

log = logging.getLogger(__name__)

# ── GPU type mapping ──────────────────────────────────────────────────────────

GPU_MAP = {
    "H100":  "NVIDIA H100 80GB HBM3",
    "A100":  "NVIDIA A100 80GB",
    "4090":  "NVIDIA GeForce RTX 4090",
    "3090":  "NVIDIA GeForce RTX 3090",
    "A40":   "NVIDIA A40",
    "L40S":  "NVIDIA L40S",
}

# Fallback prices ($/hr) used when live quote fails
FALLBACK_PRICE = {
    "NVIDIA H100 80GB HBM3":    2.49,
    "NVIDIA A100 80GB":         1.89,
    "NVIDIA GeForce RTX 4090":  0.69,
    "NVIDIA GeForce RTX 3090":  0.44,
    "NVIDIA A40":               0.79,
    "NVIDIA L40S":              1.14,
}

# Pod lifecycle states
_RUNNING_STATES  = {"RUNNING"}
_TERMINAL_STATES = {"EXITED", "DEAD", "STOPPED", "TERMINATED"}
_PENDING_STATES  = {"CREATED", "RESTARTING", "PAUSED", "STOPPING"}

# How long to wait for a pod to reach RUNNING before giving up
PROVISION_TIMEOUT_S = 600   # 10 minutes
PROVISION_POLL_S    = 10

# Log polling interval while the container runs
LOG_POLL_S = 3


class RunPodProvider:
    name = "runpod"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ["RUNPOD_API_KEY"]
        runpod.api_key = self.api_key

    # ── quote ─────────────────────────────────────────────────────────────────

    async def quote(self, gpu_spec: GPUSpec) -> Quote:
        """
        Query RunPod for live GPU availability and on-demand price.
        Falls back to hardcoded prices if the API call fails.
        """
        gpu_name = GPU_MAP.get(gpu_spec.gpu_type, gpu_spec.gpu_type)
        try:
            gpu_types = await asyncio.to_thread(self._fetch_gpu_types)
            for gt in gpu_types:
                if gt.get("id") == gpu_name or gt.get("displayName") == gpu_name:
                    secure = gt.get("secureCloud", False)
                    community = gt.get("communityCloud", False)
                    price = float(
                        gt.get("securePrice") or gt.get("communityPrice") or
                        FALLBACK_PRICE.get(gpu_name, 9.99)
                    )
                    return Quote(
                        provider=self.name,
                        price_per_hour=price,
                        available=secure or community,
                        gpu_type=gpu_name,
                        region="secure" if secure else ("community" if community else None),
                    )
        except Exception as exc:
            log.warning("RunPod live quote failed, using fallback price: %s", exc)

        return Quote(
            provider=self.name,
            price_per_hour=FALLBACK_PRICE.get(gpu_name, 9.99),
            available=True,   # optimistic fallback
            gpu_type=gpu_name,
            note="price is estimated — live check failed",
        )

    def _fetch_gpu_types(self) -> list[dict]:
        """Synchronous RunPod SDK call — run via asyncio.to_thread."""
        return runpod.get_gpus() or []

    # ── provision ────────────────────────────────────────────────────────────

    async def provision(
        self,
        gpu_spec: GPUSpec,
        image: str,
        env: dict[str, str],
    ) -> Pod:
        """
        Create a pod, then block until the container reaches RUNNING state.
        Raises ProvisionError if the pod doesn't start within PROVISION_TIMEOUT_S.
        """
        gpu_name = GPU_MAP.get(gpu_spec.gpu_type, gpu_spec.gpu_type)

        try:
            result = await asyncio.to_thread(
                runpod.create_pod,
                name="orchapod-node",
                image_name=image,
                gpu_type_id=gpu_name,
                cloud_type="SECURE",
                container_disk_in_gb=100,
                volume_in_gb=100,
                volume_mount_path="/workspace",
                env={k: str(v) for k, v in env.items()},
                ports="8000/tcp",
            )
        except Exception as exc:
            raise ProvisionError(f"RunPod create_pod failed: {exc}") from exc

        pod_id = result.get("id") or result.get("podId")
        if not pod_id:
            raise ProvisionError(f"RunPod returned no pod ID: {result}")

        log.info("Pod %s created — waiting for RUNNING state", pod_id)

        # Wait for the container to actually start
        deadline = time.monotonic() + PROVISION_TIMEOUT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(PROVISION_POLL_S)
            info = await asyncio.to_thread(runpod.get_pod, pod_id)
            state = _pod_state(info)
            log.debug("Pod %s state: %s", pod_id, state)
            if state in _RUNNING_STATES:
                ip = _extract_ip(info)
                return Pod(provider=self.name, pod_id=pod_id, public_ip=ip)
            if state in _TERMINAL_STATES:
                raise ProvisionError(
                    f"Pod {pod_id} reached terminal state {state} before running"
                )

        raise ProvisionError(
            f"Pod {pod_id} did not reach RUNNING within {PROVISION_TIMEOUT_S}s"
        )

    # ── stream_logs ──────────────────────────────────────────────────────────

    async def stream_logs(self, pod: Pod) -> AsyncIterator[str]:
        """
        Yield log lines from the running container by polling RunPod's
        GraphQL logs endpoint every LOG_POLL_S seconds.

        Stops automatically when the pod reaches a terminal state.
        Deduplicates lines so each line is yielded exactly once.
        """
        seen_bytes = 0

        while True:
            await asyncio.sleep(LOG_POLL_S)

            # Fetch full log blob
            try:
                raw = await self._fetch_logs(pod.pod_id)
            except Exception as exc:
                log.debug("Log fetch failed for pod %s: %s", pod.pod_id, exc)
                raw = ""

            # Yield only new content
            if len(raw) > seen_bytes:
                new_chunk = raw[seen_bytes:]
                seen_bytes = len(raw)
                for line in new_chunk.splitlines():
                    if line.strip():
                        yield line

            # Check if pod has finished
            try:
                info = await asyncio.to_thread(runpod.get_pod, pod.pod_id)
                state = _pod_state(info)
                if state in _TERMINAL_STATES:
                    # One final log flush
                    try:
                        raw = await self._fetch_logs(pod.pod_id)
                        if len(raw) > seen_bytes:
                            for line in raw[seen_bytes:].splitlines():
                                if line.strip():
                                    yield line
                    except Exception:
                        pass
                    return
            except Exception as exc:
                log.debug("Pod status check failed: %s", exc)

    async def _fetch_logs(self, pod_id: str) -> str:
        """
        Fetch the full log blob for a pod via RunPod's GraphQL API.
        Returns an empty string on failure (log fetching is best-effort).
        """
        query = """
        query PodLogs($podId: String!) {
            pod(input: { podId: $podId }) {
                logs
            }
        }
        """
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://api.runpod.io/graphql?api_key={self.api_key}",
                json={"query": query, "variables": {"podId": pod_id}},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("pod", {}).get("logs") or ""

    # ── wait ─────────────────────────────────────────────────────────────────

    async def wait(self, pod: Pod) -> int:
        """
        Block until the container exits.
        Returns 0 if the pod exited cleanly (EXITED), 1 for any error state.

        Polls every 15s — RunPod rate-limits heavy polling.
        """
        poll_interval = 15

        while True:
            await asyncio.sleep(poll_interval)
            try:
                info = await asyncio.to_thread(runpod.get_pod, pod.pod_id)
            except Exception as exc:
                log.warning("get_pod failed for %s: %s — retrying", pod.pod_id, exc)
                continue

            state = _pod_state(info)
            log.debug("Pod %s wait-state: %s", pod.pod_id, state)

            if state == "EXITED":
                # RunPod doesn't expose the container exit code directly.
                # Treat EXITED as success; failure is detected by the absence
                # of expected output artifacts (checked by the executor).
                return 0

            if state in ("DEAD", "TERMINATED"):
                return 1

            if state == "STOPPED":
                # Stopped via API (e.g. our cancel) — treat as cancelled (non-zero)
                return 2

    # ── terminate ────────────────────────────────────────────────────────────

    async def terminate(self, pod: Pod) -> None:
        await asyncio.to_thread(runpod.terminate_pod, pod.pod_id)
        log.info("Terminated pod %s", pod.pod_id)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _pod_state(info: dict) -> str:
    """
    Extract a normalised pod state string from a RunPod get_pod() response.
    RunPod uses 'desiredStatus' in older SDK versions and 'runtime' in newer.
    """
    # Try top-level desiredStatus (common in SDK responses)
    state = info.get("desiredStatus") or info.get("status") or ""
    return state.upper()


def _extract_ip(info: dict) -> str | None:
    """Pull the public IP from a RunPod pod info dict, if exposed."""
    runtime = info.get("runtime") or {}
    ports = runtime.get("ports") or []
    for p in ports:
        if p.get("isIpPublic"):
            return p.get("ip")
    return info.get("machine", {}).get("podHostId")
