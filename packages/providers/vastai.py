"""
packages/providers/vastai.py

Vast.ai GPU provider — fallback provider for MVP.
Forked from CryDevOk/vastai-mcp (23-tool community MCP), hardened for reliability.

Implementation effort: ~4 days (MCP fork needs reliability work)
GPU types: H100 SXM5 at $1.49–$2.20/hr (varies by host)

Key quirk: instances are bid-priced and CAN be interrupted.
MVP uses on-demand (bidding=False) — accept 10-20% premium, defer spot handling to V1.

Vast.ai API docs: https://vast.ai/docs/api
"""

from __future__ import annotations
import asyncio
import os
from typing import AsyncIterator

from .base import GPUProvider, GPUSpec, Quote, Pod, ProvisionError


class VastAIProvider:
    name = "vastai"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ["VASTAI_API_KEY"]
        # TODO: initialise vastai SDK / REST client
        # import vastai; self.client = vastai.VastAI(api_key=self.api_key)

    async def quote(self, gpu_spec: GPUSpec) -> Quote:
        """
        Query Vast.ai for cheapest on-demand offer matching the spec.
        In production: call /bundles endpoint with gpu_name filter.
        """
        # TODO: real API call
        # offers = self.client.search_offers(gpu_name="H100_SXM5", order="dph_total asc")
        # cheapest = offers[0]
        return Quote(
            provider=self.name,
            price_per_hour=1.59,   # TODO: real quote
            available=True,
            gpu_type="H100 SXM5",
            note="on-demand (bidding=False)"
        )

    async def provision(
        self,
        gpu_spec: GPUSpec,
        image: str,
        env: dict[str, str],
    ) -> Pod:
        """
        Create a Vast.ai instance from the cheapest matching offer.
        MVP: on-demand only (no spot/bid).
        """
        # TODO: implement
        # offer_id = (await self._find_offer(gpu_spec)).id
        # instance = self.client.create_instance(
        #     offer_id=offer_id,
        #     image=image,
        #     env=env,
        #     onstart="",   # startup script if needed
        #     bidding=False,
        # )
        raise NotImplementedError("VastAIProvider.provision() — implement in week 5-6")

    async def stream_logs(self, pod: Pod) -> AsyncIterator[str]:
        # TODO: vastai logs {instance_id} via SSH or API
        while True:
            await asyncio.sleep(1)
            yield "[Vast.ai] log streaming not yet implemented"

    async def wait(self, pod: Pod) -> int:
        # TODO: poll instance status until exited
        raise NotImplementedError("VastAIProvider.wait()")

    async def terminate(self, pod: Pod) -> None:
        # self.client.destroy_instance(pod.pod_id)
        raise NotImplementedError("VastAIProvider.terminate()")


# ---------------------------------------------------------------------------
# Provider registry — add new providers here
# ---------------------------------------------------------------------------
# Import at bottom of file to avoid circular imports in executor

PROVIDERS: dict[str, GPUProvider] = {}

def register_providers(runpod_key: str, vastai_key: str) -> None:
    from .runpod import RunPodProvider
    PROVIDERS["runpod"] = RunPodProvider(api_key=runpod_key)
    PROVIDERS["vastai"] = VastAIProvider(api_key=vastai_key)


async def pick_provider(resources) -> GPUProvider:
    """
    MVP routing: first-available from provider_pref list.
    V1: price-aware routing with reliability scoring.
    """
    from .base import NoCapacity
    pref = getattr(resources, "provider_pref", None) or ["runpod", "vastai"]
    for name in pref:
        provider = PROVIDERS.get(name)
        if provider is None:
            continue
        gpu_spec = GPUSpec(gpu_type=resources.gpu.split("x")[-1], count=1)
        quote = await provider.quote(gpu_spec)
        if quote.available:
            return provider
    raise NoCapacity("No GPU provider has available capacity for this spec.")
