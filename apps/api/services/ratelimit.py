"""
apps/api/services/ratelimit.py

Per-IP token buckets on the routes that spend or start runs (D6; docs/contracts.md "Run control API"): past a bucket's
burst, 429 with Retry-After. The address is request.client.host: the prod API runs uvicorn with --forwarded-allow-ips "*"
behind Caddy, which overwrites X-Forwarded-For, and api:8000 is not published.
ponytail: the buckets live in this process, like the budget grants, which the one API worker allows; with more workers or
hosts they move to Redis. Many addresses together can still drain the anonymous share of the day: the day cap and the
kill switch are the backstop.
"""

from __future__ import annotations

import ipaddress
import math
from time import monotonic

from fastapi import HTTPException, Request

# bucket → (burst, seconds per token). plan: POST /agent/plan and /workflows/from-prompt (Nemotron Super); run: every
# way a run starts (/agent/run, start, retry, /inference/deploy); compare: POST /compare (two model calls; at 10 then 1
# per 6 s one address alone drained the $1.50 anonymous share in about 10 minutes); write: POST/PUT/DELETE /workflows,
# POST /runs and cancel, POST /models (junk rows would push the golden run out of the 500-row lists).
RATES = {"plan": (5, 12.0), "run": (5, 12.0), "compare": (3, 60.0), "write": (10, 30.0)}
# (bucket, address) → (tokens left, monotonic() then), in last-use order: the oldest come first
_buckets: dict[tuple[str, str], tuple[float, float]] = {}


def address(request: Request) -> str:
    """The caller's address: IPv6 per /64, the block one subscriber usually holds; an IPv4-mapped one as its IPv4."""
    host = request.client.host if request.client else ""
    try:
        a = ipaddress.ip_address(host)
    except ValueError:
        return host
    if a.version == 6:
        a = a.ipv4_mapped or a
    return str(ipaddress.ip_network(f"{a}/64", strict=False)) if a.version == 6 else str(a)


def limit(bucket: str):
    """A route dependency: one token from this address's `bucket`, else 429 with Retry-After (seconds). Async, so it runs
    on the event loop, where no two requests interleave in it (FastAPI runs a sync dependency in its threadpool)."""
    async def take(request: Request) -> None:
        burst, every = RATES[bucket]
        now, key = monotonic(), (bucket, address(request))
        tokens, then = _buckets.pop(key, (burst, now))  # re-inserted below, at the end: last-use order
        tokens = min(burst, tokens + (now - then) / every)
        _buckets[key] = (tokens - 1 if tokens >= 1 else tokens, now)
        while _buckets:  # forget refilled buckets (the same as no entry) from the front, up to the first one in use
            oldest = next(iter(_buckets))
            left, at = _buckets[oldest]
            if left + (now - at) / RATES[oldest[0]][1] < RATES[oldest[0]][0]:
                break
            del _buckets[oldest]
        if tokens < 1:
            wait = math.ceil((1 - tokens) * every)
            raise HTTPException(status_code=429, detail=f"too many requests from your address; try again in {wait} s",
                                headers={"Retry-After": str(wait)})
    return take
