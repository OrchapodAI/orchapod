"""D6 public-demo hardening of the HTTP surface (docs/contracts.md "Config" and "Run control API"): the CORS
allow-list, per-IP rate limits, the deep /health and the shallow /livez."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from api import main

PREFLIGHT = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type,x-orchapod-admin"}


async def allowed(client, origin):
    """What a browser on `origin` learns from a POST's preflight: the origin allowed (or None), and whether
    credentials are."""
    r = await client.options("/agent/plan", headers={"Origin": origin, **PREFLIGHT})
    return r.headers.get("access-control-allow-origin"), "access-control-allow-credentials" in r.headers


async def test_cors_allows_only_this_machines_pages_by_default(client):
    assert await allowed(client, "http://localhost:3000") == ("http://localhost:3000", False)
    assert await allowed(client, "http://127.0.0.1:3100") == ("http://127.0.0.1:3100", False)  # qa's `next dev` port
    for origin in ("https://evil.example", "http://localhost.evil.example", "null"):
        assert await allowed(client, origin) == (None, False)


async def test_cors_origins_are_an_exact_list_and_star_never_comes_with_credentials(monkeypatch):
    def app_with(origins):
        monkeypatch.setenv("ORCHAPOD_CORS_ORIGINS", origins)
        inner = FastAPI()
        inner.add_middleware(CORSMiddleware, **main.cors())
        return AsyncClient(transport=ASGITransport(app=inner), base_url="http://test")

    async with app_with(" https://app.example.com , https://b.example") as c:  # hosted: https://app.<domain>
        assert await allowed(c, "https://app.example.com") == ("https://app.example.com", False)
        assert await allowed(c, "http://localhost:3000") == (None, False)
    async with app_with("*") as c:
        assert await allowed(c, "https://anyone.example") == ("*", False)
