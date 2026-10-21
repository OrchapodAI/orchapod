"""
apps/api/services/ratelimit.py

Per-IP token buckets on the routes that spend or start runs (D6; docs/contracts.md "Run control API"): past a bucket's
burst, 429 with Retry-After. ponytail: the buckets live in this process, like the budget grants, which the one API
worker allows; with more workers or hosts they move to Redis.
"""

from __future__ import annotations

import ipaddress
import math
from time import monotonic

from fastapi import HTTPException, Request

from api import config

# bucket → (burst, seconds per token). plan: POST /agent/plan and /workflows/from-prompt (Nemotron Super); run: every
# way a run starts (/agent/run, start, retry, /inference/deploy); compare: POST /compare (two model calls).
RATES = {"plan": (5, 12.0), "run": (5, 12.0), "compare": (10, 6.0)}
_buckets: dict[tuple[str, str], tuple[float, float]] = {}  # (bucket, address) → (tokens left, monotonic() then)


def _proxies() -> list:
    """ORCHAPOD_TRUSTED_PROXIES (IPs or CIDRs) as networks; a bad entry raises."""
    return [ipaddress.ip_network(p.strip(), strict=False)
            for p in config.env("ORCHAPOD_TRUSTED_PROXIES").split(",") if p.strip()]


_proxies()  # a bad ORCHAPOD_TRUSTED_PROXIES stops the API at start, not at its first limited request


def address(request: Request) -> str:
    """The caller's address: the TCP peer or, when the peer is a trusted proxy, the nearest X-Forwarded-For hop that is not
    one (a client can prepend anything). IPv6 counts per /64, the block one subscriber usually holds."""
    proxies = _proxies()

    def ip(host: str):
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            return None

    def proxy(host: str) -> bool:
        return (a := ip(host)) is not None and any(a in net for net in proxies)

    host = request.client.host if request.client else ""
    if proxy(host):
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
        host = next((h for h in reversed(hops) if not proxy(h)), host)
    a = ip(host)
    return str(ipaddress.ip_network(f"{a}/64", strict=False)) if a and a.version == 6 else host


def limit(bucket: str):
    """A route dependency: one token from this address's `bucket`, else 429 with Retry-After (seconds)."""
    def take(request: Request) -> None:
        burst, every = RATES[bucket]
        now, key = monotonic(), (bucket, address(request))
        tokens, then = _buckets.get(key, (burst, now))
        tokens = min(burst, tokens + (now - then) / every)
        if tokens < 1:
            wait = math.ceil((1 - tokens) * every)
            raise HTTPException(status_code=429, detail=f"too many requests from your address; try again in {wait} s",
                                headers={"Retry-After": str(wait)})
        _buckets[key] = (tokens - 1, now)
        if len(_buckets) > 10_000:  # forget addresses whose buckets have refilled, which is the same as no entry
            for k in [k for k, (_, t) in _buckets.items() if now - t >= RATES[k[0]][0] * RATES[k[0]][1]]:
                del _buckets[k]
    return take
