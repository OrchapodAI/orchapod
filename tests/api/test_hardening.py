"""D6 public-demo hardening of the HTTP surface (docs/contracts.md "Config" and "Run control API"): the CORS
allow-list, per-IP rate limits, the deep /health and the shallow /livez."""

from __future__ import annotations

import asyncio
import inspect
import sys
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
    assert RATES == {"plan": (5, 12.0), "run": (5, 12.0), "compare": (3, 60.0),  # contracts "Run control API"
                     "write": (10, 30.0)}
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
        assert [(await a.post("/compare", json={})).status_code for _ in range(4)] == [422] * 3 + [429]


async def test_simultaneous_requests_never_pass_more_than_the_burst(client, limits):
    """take() is async, so it runs on the event loop; a sync one runs in the threadpool, where two requests can read
    the same tokens (and a size change breaks an iteration)."""
    assert inspect.iscoroutinefunction(ratelimit.limit("plan"))  # the race below shows only some of the time
    switch = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)  # the worst case for a GIL hand-off between reading and writing a bucket
    try:
        async with caller("203.0.113.7") as a:
            replies = await asyncio.gather(*(a.post("/compare", json={}) for _ in range(40)))
    finally:
        sys.setswitchinterval(switch)
    assert sorted(r.status_code for r in replies) == [422] * 3 + [429] * 37


def request(peer, xff=None):
    return Request({"type": "http", "client": (peer, 1),
                    "headers": [(b"x-forwarded-for", xff.encode())] if xff is not None else []})


def test_the_address_is_the_client_uvicorn_reports():
    # prod: uvicorn --forwarded-allow-ips "*" behind Caddy, which overwrites X-Forwarded-For; the app reads no header
    assert ratelimit.address(request("203.0.113.7", "6.6.6.6")) == "203.0.113.7"
    assert ratelimit.address(request("::ffff:203.0.113.7")) == "203.0.113.7"  # an IPv4-mapped address is not ::/64
    assert ratelimit.address(request("2001:db8:1:2:a:b:c:d")) == "2001:db8:1:2::/64"  # one subscriber's IPv6 block


async def test_buckets_stay_in_last_use_order_and_refilled_ones_go_from_the_front(client, limits):
    ratelimit._buckets[("plan", "203.0.113.7")] = (2.0, limits[0] - 1)  # in use, and the oldest entry
    ratelimit._buckets.update({("plan", f"10.0.{i // 256}.{i % 256}"): (0.0, limits[0] - 60) for i in range(1000)})
    ratelimit._buckets[("plan", "198.51.100.9")] = (0.0, limits[0])  # emptied just now: not refilled
    async with caller("203.0.113.7") as a:
        assert (await a.post("/agent/plan", json={"intent": "x"})).status_code == 200
    assert list(ratelimit._buckets) == [("plan", "198.51.100.9"), ("plan", "203.0.113.7")]


# --- /health and /livez ----------------------------------------------------------

async def down():
    raise ConnectionRefusedError("postgres down")


@pytest.fixture
def deps(db, monkeypatch):
    """The database is the test's (the module's own engine would keep an aiosqlite thread alive past the tests); Redis
    and object storage are up or down as the test says."""
    from api.services import events, storage
    monkeypatch.setattr("api.database.engine", db.bind)
    monkeypatch.setattr(main, "_health", None)
    monkeypatch.setattr(main, "HEALTH_TTL_S", 0)  # a fresh check per request, unless a test says otherwise
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


async def test_health_runs_one_check_at_a_time_and_reuses_it_for_10_s(client, deps, monkeypatch):
    """A flood of probes during a storage brownout must not pin the executor's threads."""
    from api.services import storage
    calls, clock, fake = [], [100.0], storage.head_bucket
    monkeypatch.setattr(main, "HEALTH_TTL_S", 10)
    monkeypatch.setattr(main, "monotonic", lambda: clock[0])
    monkeypatch.setattr(storage, "head_bucket", lambda: calls.append(1) or fake())

    replies = await asyncio.gather(*(client.get("/health") for _ in range(20)))
    assert {r.status_code for r in replies} == {200} and len(calls) == 1  # one check, shared
    deps.storage = False
    clock[0] += 9.9
    assert (await client.get("/health")).status_code == 200 and len(calls) == 1  # reused
    clock[0] += 0.1
    r = await client.get("/health")
    assert (r.status_code, r.json()["failed"], len(calls)) == (503, ["storage"], 2)


async def test_livez_answers_while_every_dependency_is_down(client, deps, monkeypatch):
    deps.redis = deps.storage = False
    monkeypatch.setattr(main, "_database", down)
    assert (await client.get("/health")).json()["failed"] == ["database", "redis", "storage"]
    r = await client.get("/livez")
    assert (r.status_code, r.json()) == (200, {"status": "ok"})


# --- workflow YAML ---------------------------------------------------------------

def alias_bomb(levels=6):
    """The reviewer's alias chain, bounded: under 1 KB of YAML, 9 copies per level once expanded (json.dumps, deepcopy)."""
    lines = ["x0: &a0 [" + ", ".join(['"xxxxxxxx"'] * 9) + "]"]
    lines += [f"x{i}: &a{i} [" + ", ".join([f"*a{i - 1}"] * 9) + "]" for i in range(1, levels)]
    return ("name: w\nanchors:\n" + "\n".join("  " + line for line in lines)
            + f'\nnodes:\n  - id: d\n    type: data-prep\n    inputs: {{dataset: "hf://x", extra: *a{levels - 1}}}\n')


async def test_workflow_yaml_with_an_alias_is_refused_before_it_expands(client, db):
    from api.executor.dag import compile_dag
    from api.models.db import Workflow
    from sqlmodel import select

    bomb = alias_bomb()
    assert len(bomb) < 1000
    r = await client.post("/workflows", json={"name": "w", "yaml": bomb})
    assert r.status_code == 422 and "alias" in r.json()["detail"]
    ok = await client.post("/workflows", json={"name": "w", "yaml": "name: w\nnodes:\n  - {id: d, type: data-prep, "
                                                                     "inputs: {dataset: &ds hf://x}}\n"})
    assert ok.status_code == 201  # an anchor alone is harmless
    assert (await client.put(f"/workflows/{ok.json()['id']}", json={"yaml": bomb})).status_code == 422
    assert [w.yaml for w in await db.scalars(select(Workflow))] == [ok.json()["yaml"]]
    with pytest.raises(ValueError, match="alias"):
        compile_dag(bomb, {})  # the executor and the planner compile through it too


async def test_endpoint_extend_is_gone(client, db, seeded_node_run):
    """It had no limit, guard, kill switch or admin check, and a signed extend_min: -60 lowered today's spend."""
    run, _ = seeded_node_run  # a running vllm-serve node, which the route used to extend
    assert (await client.post(f"/inference/extend/{run.id}", json={"extend_min": -60})).status_code == 404
    await db.refresh(run)
    assert run.cost_usd is None



# --- writes ----------------------------------------------------------------------

DRAFT = "name: w\nnodes:\n  - {id: d, type: data-prep, inputs: {dataset: hf://x}}\n"


async def test_a_workflow_with_runs_is_read_only_to_anonymous_callers(client, db, monkeypatch):
    from api.models.db import Run
    monkeypatch.setenv("ORCHAPOD_ADMIN_TOKEN", "s3cret")
    monkeypatch.setenv("ORCHAPOD_ANON_SCALE", "1")  # full caps for the public do not make it the admin
    ran, draft = [(await client.post("/workflows", json={"name": "w", "yaml": DRAFT})).json()["id"] for _ in range(2)]
    db.add(Run(workflow_id=uuid.UUID(ran), user_id=uuid.uuid4()))
    await db.commit()

    for r in (await client.put(f"/workflows/{ran}", json={"yaml": DRAFT}), await client.delete(f"/workflows/{ran}")):
        assert r.status_code == 409 and "save a copy" in r.json()["detail"]
    assert (await client.put(f"/workflows/{ran}", json={"name": "golden"}, headers={"X-Orchapod-Admin": "s3cret"})
            ).status_code == 200
    assert (await client.put(f"/workflows/{draft}", json={"yaml": DRAFT})).status_code == 200  # no runs: anyone edits
    assert (await client.delete(f"/workflows/{draft}")).status_code == 204


async def test_writes_share_a_bucket(client, limits):
    run = uuid.uuid4()
    async with caller("203.0.113.7") as a:
        made = [(await a.post("/workflows", json={"name": "w", "yaml": DRAFT})).json()["id"] for _ in range(5)]
        codes = [(await a.put(f"/workflows/{made[0]}", json={"name": "x"})).status_code,
                 (await a.delete(f"/workflows/{made[1]}")).status_code,
                 (await a.post("/runs", json={"workflow_id": str(run)})).status_code,
                 (await a.post(f"/runs/{run}/cancel")).status_code, (await a.post("/models", json={})).status_code]
        assert codes == [200, 204, 404, 404, 422]  # with the 5 creates, each took a token
        assert (await a.post("/workflows", json={"name": "w", "yaml": DRAFT})).status_code == 429
        assert (await a.post("/agent/plan", json={"intent": "x"})).status_code == 200  # the other buckets are apart
