"""D6 public-demo hardening of the HTTP surface (docs/contracts.md "Config" and "Run control API"): the CORS
allow-list, per-IP rate limits, the deep /health and the shallow /livez."""

from __future__ import annotations

import asyncio
import time
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from api import main
from api.services import ratelimit

RATES = ratelimit.RATES  # the real ones: tests/api/conftest.py turns them off for every other test

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


# --- per-IP rate limits ----------------------------------------------------------

@pytest.fixture
def limits(monkeypatch):
    """The real buckets, STUB answers (no network) and a clock the test moves."""
    monkeypatch.setattr(ratelimit, "RATES", RATES)
    monkeypatch.setenv("STUB", "1")
    clock = [1000.0]
    monkeypatch.setattr(ratelimit, "monotonic", lambda: clock[0])
    return clock


def caller(ip):
    """A client at this address; the `client` fixture's database overrides apply to the shared app."""
    return AsyncClient(transport=ASGITransport(app=main.app, client=(ip, 1234)), base_url="http://test")


async def test_each_address_gets_a_burst_then_429_with_retry_after(client, limits):
    assert RATES == {"plan": (5, 12.0), "run": (5, 12.0), "compare": (10, 6.0)}  # contracts "Run control API"
    plan = {"intent": "synthetic movie likes"}
    async with caller("203.0.113.7") as a, caller("198.51.100.9") as b:
        assert [(await a.post("/agent/plan", json=plan)).status_code for _ in range(5)] == [200] * 5
        r = await a.post("/agent/plan", json=plan, headers={"Origin": "http://localhost:3000"})
        assert (r.status_code, r.headers["Retry-After"]) == (429, "12")
        assert r.headers["access-control-expose-headers"] == "Retry-After"  # the web app can read it
        assert (await b.post("/agent/plan", json=plan)).status_code == 200  # another address, its own bucket
        limits[0] += 12  # one token back
        assert [(await a.post("/agent/plan", json=plan)).status_code for _ in range(2)] == [200, 429]


async def test_routes_that_spend_alike_share_a_bucket_and_the_limit_comes_first(client, limits):
    run = uuid.uuid4()
    async with caller("203.0.113.7") as a:
        codes = [(await a.post("/agent/run", json={})).status_code, (await a.post(f"/runs/{run}/start")).status_code,
                 (await a.post(f"/runs/{run}/nodes/x/retry")).status_code,
                 (await a.post("/inference/deploy", json={})).status_code, (await a.post(f"/runs/{run}/start")).status_code]
        assert codes == [422, 404, 404, 422, 404]  # each one took a token
        assert (await a.post("/agent/run", json={})).status_code == 429
        codes = [(await a.post("/workflows/from-prompt", json={"prompt": "movie likes"})).status_code for _ in range(5)]
        assert codes == [201] * 5 and (await a.post("/agent/plan", json={"intent": "x"})).status_code == 429
        assert [(await a.post("/compare", json={})).status_code for _ in range(11)] == [422] * 10 + [429]


def request(peer, xff=None):
    return Request({"type": "http", "client": (peer, 1),
                    "headers": [(b"x-forwarded-for", xff.encode())] if xff is not None else []})


def test_the_address_is_the_peer_unless_a_trusted_proxy_forwarded_it(monkeypatch):
    monkeypatch.delenv("ORCHAPOD_TRUSTED_PROXIES", raising=False)
    assert ratelimit.address(request("10.0.0.2", "1.2.3.4")) == "10.0.0.2"  # nobody is trusted by default
    monkeypatch.setenv("ORCHAPOD_TRUSTED_PROXIES", "10.0.0.0/8, 192.0.2.1")
    assert ratelimit.address(request("10.0.0.2", "6.6.6.6, 1.2.3.4")) == "1.2.3.4"  # a client can prepend anything
    assert ratelimit.address(request("10.0.0.2", "1.2.3.4, 192.0.2.1")) == "1.2.3.4"  # two proxies in a row
    assert ratelimit.address(request("10.0.0.2")) == "10.0.0.2"
    assert ratelimit.address(request("5.5.5.5", "1.2.3.4")) == "5.5.5.5"  # an untrusted peer's header counts for nothing
    assert ratelimit.address(request("2001:db8:1:2:a:b:c:d")) == "2001:db8:1:2::/64"  # one subscriber's IPv6 block


async def test_idle_addresses_are_forgotten_once_there_are_many(client, limits):
    idle = {("plan", f"10.0.{i // 256}.{i % 256}"): (0.0, limits[0] - 60) for i in range(10_001)}  # refilled by now
    ratelimit._buckets.update(idle)
    async with caller("203.0.113.7") as a:
        assert (await a.post("/agent/plan", json={"intent": "x"})).status_code == 200
    assert list(ratelimit._buckets) == [("plan", "203.0.113.7")]


# --- /health and /livez ----------------------------------------------------------

async def down():
    raise ConnectionRefusedError("postgres down")


@pytest.fixture
def deps(db, monkeypatch):
    """The database is the test's (the module's own engine would keep an aiosqlite thread alive past the tests); Redis
    and object storage are up or down as the test says."""
    from api.services import events, storage
    monkeypatch.setattr("api.database.engine", db.bind)
    up = SimpleNamespace(redis=True, storage=True, redis_hangs=False)

    async def ping():
        if up.redis_hangs:
            await asyncio.sleep(10)
        if not up.redis:
            raise ConnectionError("redis down")

    def head_bucket():
        if not up.storage:
            raise ConnectionError("storage down")

    monkeypatch.setattr(events.event_bus, "_redis", SimpleNamespace(ping=ping))
    monkeypatch.setattr(storage, "head_bucket", head_bucket)
    return up


async def test_health_names_the_dependencies_that_failed(client, deps, monkeypatch):
    r = await client.get("/health")
    assert (r.status_code, r.json()) == (200, {"status": "ok"})
    deps.redis = deps.storage = False
    r = await client.get("/health")
    assert (r.status_code, r.json()) == (503, {"status": "fail", "failed": ["redis", "storage"]})
    deps.redis = deps.storage = True
    monkeypatch.setattr(main, "_database", down)
    r = await client.get("/health")
    assert (r.status_code, r.json()) == (503, {"status": "fail", "failed": ["database"]})


async def test_a_hung_dependency_fails_health_within_the_timeout(client, deps, monkeypatch):
    monkeypatch.setattr(main, "HEALTH_TIMEOUT_S", 0.2)
    deps.redis_hangs = True
    started = time.monotonic()
    r = await client.get("/health")
    assert (r.status_code, r.json()["failed"]) == (503, ["redis"]) and time.monotonic() - started < 2


async def test_livez_answers_while_every_dependency_is_down(client, deps, monkeypatch):
    deps.redis = deps.storage = False
    monkeypatch.setattr(main, "_database", down)
    assert (await client.get("/health")).json()["failed"] == ["database", "redis", "storage"]
    r = await client.get("/livez")
    assert (r.status_code, r.json()) == (200, {"status": "ok"})
