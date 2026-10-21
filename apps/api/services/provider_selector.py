"""
apps/api/services/provider_selector.py

GPU provider selection — picks the cheapest available provider for a node.
Called by the executor before provisioning a pod.

MVP: round-robin through provider_pref list, return first with available=True.
V1:  price-aware routing with reliability scoring + spot instance support.
"""

from __future__ import annotations

import os

from packages.providers.base import GPUProvider, GPUSpec, NoCapacity
from packages.providers.vastai import VastAIProvider
from packages.providers.local_docker import LocalDockerProvider

try:
    from packages.providers.nebius import NebiusProvider
except ImportError:
    NebiusProvider = None  # type: ignore


def _parse_gpu_spec(resource_str: str) -> GPUSpec:
    """
    Parse '1xH100' or 'H100' into a GPUSpec.
    resource_str comes from the workflow YAML resources.gpu field.
    """
    if "x" in resource_str:
        count_str, gpu_type = resource_str.split("x", 1)
        return GPUSpec(gpu_type=gpu_type.strip(), count=int(count_str))
    return GPUSpec(gpu_type=resource_str.strip())


def build_providers() -> dict[str, GPUProvider]:
    """
    Instantiate providers from environment keys.
    Any provider whose key is missing is silently omitted.
    """
    providers: dict[str, GPUProvider] = {}
    if os.environ.get("NEBIUS_PROJECT_ID") and NebiusProvider:
        providers["nebius"] = NebiusProvider()
    if os.environ.get("VASTAI_API_KEY"):
        providers["vastai"] = VastAIProvider()
    return providers


# Module-level singleton built once at import time
_providers: dict[str, GPUProvider] = {}


def get_providers() -> dict[str, GPUProvider]:
    global _providers
    if not _providers:
        _providers = build_providers()
    return _providers


async def pick_provider(resources) -> tuple[GPUProvider, GPUSpec]:
    """
    Choose the first available provider from the node's preference list (default ["nebius"]).
    vastai is used only when provider_pref names it, so a gpu node never lands there silently.
    Returns (provider, gpu_spec) so the caller can use the spec for provisioning.
    Raises NoCapacity if no provider has available GPUs.
    """
    providers = get_providers()
    pref: list[str] = getattr(resources, "provider_pref", None) or ["nebius"]
    gpu_str: str = getattr(resources, "gpu", "1xH100")
    gpu_spec = _parse_gpu_spec(gpu_str)

    for name in pref:
        provider = providers.get(name)
        if provider is None:
            continue
        try:
            quote = await provider.quote(gpu_spec)
            if quote.available:
                return provider, gpu_spec
        except Exception:
            continue

    raise NoCapacity(f"none of {pref} is configured with {gpu_str} capacity (nebius needs NEBIUS_PROJECT_ID)")


async def get_cost_estimate(resources) -> list[dict]:
    """
    Return cost quotes from all configured providers for a given resource spec.
    Used by the frontend to show a cost estimate before the user clicks Run.
    """
    providers = get_providers()
    gpu_str: str = getattr(resources, "gpu", "1xH100")
    gpu_spec = _parse_gpu_spec(gpu_str)

    quotes = []
    for name, provider in providers.items():
        try:
            q = await provider.quote(gpu_spec)
            quotes.append({
                "provider": name,
                "price_per_hour": q.price_per_hour,
                "available": q.available,
                "gpu_type": q.gpu_type,
                "note": q.note,
            })
        except Exception as e:
            quotes.append({"provider": name, "error": str(e)})

    return sorted(quotes, key=lambda q: q.get("price_per_hour", 9999))


_local_docker: LocalDockerProvider | None = None


async def pick_local_docker(resources) -> tuple[GPUProvider, GPUSpec]:
    """Return the LocalDockerProvider for CPU-runtime nodes.
    CPU nodes never need a GPU spec — we pass a dummy one so the protocol is satisfied.
    """
    global _local_docker
    if _local_docker is None:
        _local_docker = LocalDockerProvider()
    dummy_spec = GPUSpec(gpu_type="cpu", count=0)
    return _local_docker, dummy_spec
