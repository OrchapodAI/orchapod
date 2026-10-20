"""
packages/sdk-py/orchapod/cost.py

Spend of one node. Clients pass on_usage=cost.add; io writes the summary as cost_json at exit.
"""

from __future__ import annotations

import os

from orchapod.prices import PRICES

_items: dict[tuple[str, str], dict] = {}


class BudgetExceeded(RuntimeError):
    """Node spend passed ORCHAPOD_MAX_COST_USD, the smaller of the run and day budgets left."""


def add(provider: str, model: str, in_tokens: int = 0, out_tokens: int = 0,
        usd: float | None = None, calls: int = 1, **extra) -> None:
    """Record one billed call or batch, aggregated per (provider, model); usd=None prices it from PRICES.
    extra: credits (tavily), gpu_hours (nebius_serverless), trained_tokens (fine-tune)."""
    if usd is None:
        usd = _price(provider, model, in_tokens, out_tokens, **extra)
    item = _items.setdefault((provider, model), {
        "provider": provider, "model": model, "calls": 0, "in_tokens": 0, "out_tokens": 0, "usd": 0.0})
    item["calls"] += calls
    item["in_tokens"] += in_tokens
    item["out_tokens"] += out_tokens
    item["usd"] += usd
    for k, v in extra.items():
        item[k] = item.get(k, 0) + v
    cap = os.environ.get("ORCHAPOD_MAX_COST_USD")
    if cap and total() > float(cap):
        raise BudgetExceeded(f"node spend ${total():.4f} passed ORCHAPOD_MAX_COST_USD ${float(cap):.4f}")


def _price(provider: str, model: str, in_tokens: int, out_tokens: int,
           credits: float = 0, gpu_hours: float = 0, trained_tokens: int = 0, **_) -> float:
    try:
        if provider == "tavily":
            return credits * PRICES["tavily"]["credit"]
        if provider == "nebius_serverless":  # model = "<platform>/<preset>"
            return gpu_hours * PRICES["nebius_serverless"][model.split("/")[0]]
        if trained_tokens:
            return trained_tokens * PRICES["token_factory_finetune"][model]
        p = PRICES[provider][model]
        return (in_tokens * p["in"] + out_tokens * p["out"]) / 1_000_000
    except KeyError:  # unpriced calls fail closed (R5)
        raise LookupError(f"no price for {provider} {model} in orchapod.prices.PRICES") from None


def total() -> float:
    return sum(i["usd"] for i in _items.values())


def summary() -> dict:
    """The cost_json envelope: {"usd", "items": [{provider, model, calls, in_tokens, out_tokens, usd, ...}]}."""
    return {"usd": round(total(), 6), "items": [{**i, "usd": round(i["usd"], 6)} for i in _items.values()]}
