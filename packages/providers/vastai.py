"""
packages/providers/vastai.py

Vast.ai GPU provider — primary provider for testing/development.
Uses the vastai Python SDK (pip install vastai).

Key quirks:
  - SDK calls are synchronous; wrapped in asyncio.to_thread() throughout.
  - Instance IDs are integers; stored as str in Pod.pod_id.
  - env must be passed as a space-separated "-e KEY=VALUE" string.
  - On-demand (dph_total order, no bidding) for reliability in dev.
"""

from __future__ import annotations
import asyncio
import os
from typing import AsyncIterator

from .base import GPUProvider, GPUSpec, Quote, Pod, ProvisionError


# Our GPU name → Vast.ai gpu_name filter substring
GPU_MAP = {
    "H100":  "H100",
    "A100":  "A100",
    "4090":  "RTX 4090",
    "3090":  "RTX 3090",
}

_TERMINAL_STATUSES = {"exited", "error", "destroyed", "deleted"}


def _env_to_str(env: dict[str, str]) -> str:
    """Convert env dict to Vast.ai's '-e KEY=VALUE' string format."""
    import json
    parts = []
    for k, v in env.items():
        # Values may contain spaces (JSON blobs). Vast.ai accepts quoted values.
        escaped = v.replace('"', '\\"')
        parts.append(f'-e {k}="{escaped}"')
    return " ".join(parts)


class VastAIProvider:
    name = "vastai"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ["VASTAI_API_KEY"]
        from vastai import VastAI
        self.client = VastAI(api_key=self.api_key)

    # ------------------------------------------------------------------
    # quote
    # ------------------------------------------------------------------

    async def quote(self, gpu_spec: GPUSpec) -> Quote:
        try:
            offers = await asyncio.to_thread(self._search_offers, gpu_spec, limit=1)
            if not offers:
                return Quote(
                    provider=self.name,
                    price_per_hour=0.0,
                    available=False,
                    gpu_type=gpu_spec.gpu_type,
                )
            best = offers[0]
            return Quote(
                provider=self.name,
                price_per_hour=float(best.get("dph_total", 9.99)),
                available=True,
                gpu_type=best.get("gpu_name", gpu_spec.gpu_type),
                note="on-demand",
            )
        except Exception:
            return Quote(
                provider=self.name,
                price_per_hour=0.0,
                available=False,
                gpu_type=gpu_spec.gpu_type,
            )

    # ------------------------------------------------------------------
    # provision
    # ------------------------------------------------------------------

    async def provision(
        self,
        gpu_spec: GPUSpec,
        image: str,
        env: dict[str, str],
    ) -> Pod:
        offers = await asyncio.to_thread(self._search_offers, gpu_spec, limit=5)
        if not offers:
            raise ProvisionError(
                f"No Vast.ai offers available for {gpu_spec.gpu_type} x{gpu_spec.count}"
            )

        env_str = _env_to_str(env)

        for offer in offers:
            try:
                result = await asyncio.to_thread(
                    self.client.create_instance,
                    ID=offer["id"],
                    image=image,
                    env=env_str,
                    disk=100,
                    onstart="",
                )
                instance_id = result.get("new_contract")
                if instance_id is None:
                    continue
                return Pod(provider=self.name, pod_id=str(instance_id))
            except Exception:
                continue  # try next offer

        raise ProvisionError(
            f"Vast.ai: failed to create instance for {gpu_spec.gpu_type} after trying {len(offers)} offers"
        )

    # ------------------------------------------------------------------
    # wait
    # ------------------------------------------------------------------

    async def wait(self, pod: Pod) -> int:
        """Poll every 10 s until instance reaches a terminal status."""
        _POLL_INTERVAL = 10
        while True:
            instance = await self._get_instance(pod.pod_id)
            if instance is None:
                return 1  # instance disappeared

            status = (instance.get("actual_status") or "").lower()
            if status in _TERMINAL_STATUSES:
                raw = instance.get("exit_status")
                if raw is not None:
                    try:
                        return int(raw)
                    except (ValueError, TypeError):
                        pass
                # "exited" with no exit_status → assume success
                return 0 if status == "exited" else 1

            await asyncio.sleep(_POLL_INTERVAL)

    # ------------------------------------------------------------------
    # terminate
    # ------------------------------------------------------------------

    async def terminate(self, pod: Pod) -> None:
        await asyncio.to_thread(
            self.client.destroy_instance,
            ID=int(pod.pod_id),
        )

    # ------------------------------------------------------------------
    # stream_logs
    # ------------------------------------------------------------------

    async def stream_logs(self, pod: Pod) -> AsyncIterator[str]:
        # Vast.ai does not expose real-time log streaming via the Python SDK.
        # Containers push log lines via POST /internal/log themselves.
        return
        yield  # make this an async generator

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _search_offers(self, gpu_spec: GPUSpec, limit: int = 5) -> list[dict]:
        gpu_name = GPU_MAP.get(gpu_spec.gpu_type, gpu_spec.gpu_type)
        try:
            offers = self.client.search_offers(
                order="dph_total asc",
                limit=limit,
                query={
                    "gpu_name": {"ilike": f"%{gpu_name}%"},
                    "num_gpus": {"gte": gpu_spec.count},
                    "reliability2": {"gte": 0.95},
                    "rentable": {"eq": True},
                },
            )
            return offers if isinstance(offers, list) else []
        except Exception:
            return []

    async def _get_instance(self, pod_id: str) -> dict | None:
        try:
            instances = await asyncio.to_thread(
                self.client.get_instances,
            )
            if not isinstance(instances, list):
                return None
            for inst in instances:
                if str(inst.get("id")) == pod_id:
                    return inst
            return None
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

from .base import GPUProvider  # noqa: E402 (re-export for consumers)

PROVIDERS: dict[str, GPUProvider] = {}


def register_providers(runpod_key: str = "", vastai_key: str = "") -> None:
    if vastai_key:
        PROVIDERS["vastai"] = VastAIProvider(api_key=vastai_key)
    if runpod_key:
        from .runpod import RunPodProvider
        PROVIDERS["runpod"] = RunPodProvider(api_key=runpod_key)


async def pick_provider(resources) -> GPUProvider:
    """First-available from provider_pref list."""
    from .base import NoCapacity
    pref = getattr(resources, "provider_pref", None) or ["vastai", "runpod"]
    for name in pref:
        provider = PROVIDERS.get(name)
        if provider is None:
            continue
        gpu_spec = GPUSpec(gpu_type=resources.gpu.split("x")[-1], count=1)
        quote = await provider.quote(gpu_spec)
        if quote.available:
            return provider
    raise NoCapacity("No GPU provider has available capacity for this spec.")
