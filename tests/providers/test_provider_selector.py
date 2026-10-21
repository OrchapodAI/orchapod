"""provider_selector: a gpu node lands on vast.ai only when its provider_pref names it (contracts "provider selection")."""

from __future__ import annotations

import pytest

from api.services import provider_selector
from packages.providers.base import NoCapacity, Quote
from packages.providers.vastai import VastAIProvider
from packages.workflow_schema.models import ResourceSpec


@pytest.fixture
def asked(monkeypatch):
    """VASTAI_API_KEY set, Nebius not configured, vast.ai has capacity; returns the quotes vast.ai was asked for."""
    monkeypatch.setenv("VASTAI_API_KEY", "vast-key")
    monkeypatch.delenv("NEBIUS_PROJECT_ID", raising=False)
    monkeypatch.delenv("NEBIUS_IAM_TOKEN", raising=False)
    monkeypatch.setattr(provider_selector, "_providers", {})  # rebuilt from this env
    asked = []

    async def quote(self, gpu_spec):  # vast.ai would say yes, and provision next
        asked.append(gpu_spec)
        return Quote(provider="vastai", price_per_hour=1.0, available=True, gpu_type=gpu_spec.gpu_type)

    monkeypatch.setattr(VastAIProvider, "quote", quote)
    return asked


async def test_without_nebius_a_gpu_node_fails_instead_of_falling_back_to_vastai(asked):
    for resources in (ResourceSpec(), ResourceSpec(provider_pref=[]), None):
        with pytest.raises(NoCapacity, match="NEBIUS_PROJECT_ID"):
            await provider_selector.pick_provider(resources)
    assert asked == []

    provider, _ = await provider_selector.pick_provider(ResourceSpec(provider_pref=["nebius", "vastai"]))
    assert provider.name == "vastai" and len(asked) == 1  # named explicitly: allowed


async def test_cost_estimate_prices_only_providers_the_node_may_use(asked):
    assert await provider_selector.get_cost_estimate(ResourceSpec()) == [] and asked == []
    quotes = await provider_selector.get_cost_estimate(ResourceSpec(provider_pref=["nebius", "vastai"]))
    assert [q["provider"] for q in quotes] == ["vastai"] and len(asked) == 1
