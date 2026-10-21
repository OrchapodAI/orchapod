"""POST /compare per contracts "Run control API" and "ModelRef": two refs streamed side by side over SSE, keys resolved
server-side under the pairing rule, refusals as HTTP errors before any 200, spend into the day ledger."""

from __future__ import annotations

import asyncio
import functools
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models.db import Artifact, ArtifactKind, Spend
from api.routes import compare as route
from packages.providers.tokenfactory import LIGHTNING, ULTRA, TokenFactory

TF = "https://api.tokenfactory.nebius.com/v1"
ENDPOINT = "https://ep-1.example.nebius.cloud"
MESSAGES = [{"role": "user", "content": "What does RESPA Section 8 forbid?"}]


def ref(base_url=TF, model=LIGHTNING, key="NEBIUS_API_KEY", base_model=None):
    return {"base_url": base_url, "model": model, "api_key_env": key, "base_model": base_model}


def events(r) -> list[dict]:
    assert r.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def answers(evs) -> dict[int, str]:
    return {i: "".join(e["delta"] for e in evs if e["i"] == i and "delta" in e) for i in (0, 1)}


@pytest.fixture(autouse=True)
def env(monkeypatch, db):
    for k in ("STUB", "ORCHAPOD_KILL_SWITCH", "ORCHAPOD_ADMIN_TOKEN", "ORCHAPOD_ANON_SCALE", "ORCHAPOD_MAX_RUN_USD",
              "ORCHAPOD_MAX_DAY_USD", "NEBIUS_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-key")
    monkeypatch.setenv("ORCHAPOD_ENDPOINT_TOKEN", "ep-token")
    # the answers' spend is written from their own tasks, in their own sessions
    monkeypatch.setattr("api.database.AsyncSessionLocal",
                        async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False))


@pytest.fixture
def tf(monkeypatch):
    """Token Factory and our endpoints on httpx.MockTransport: replies[model] = (status, [deltas], usage)."""
    sent, replies = [], {}

    def handler(request):
        body = json.loads(request.content)
        sent.append((str(request.url), request.headers.get("authorization"), body))
        status, deltas, usage = replies[body["model"]]
        if status != 200:
            return httpx.Response(status, json={"detail": f"{body['model']} says no"})
        chunks = [{"choices": [{"index": 0, "delta": {"content": d}}]} for d in deltas]
        chunks.append({"choices": [], "usage": usage})
        return httpx.Response(200, text="".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(route, "TokenFactory", functools.partial(TokenFactory, http=http))
    return sent, replies


async def ledger(db) -> list[float]:
    return [float(s.usd) for s in await db.scalars(select(Spend).where(Spend.source == "compare"))]


async def register(db, node_run, uri, minutes=30, **meta):
    expires = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    db.add(Artifact(node_run_id=node_run.id, name="endpoint_url", kind=ArtifactKind.ENDPOINT, uri=uri,
                    meta={"expires_at": expires.isoformat(), **meta}))
    await db.commit()


async def test_streams_both_answers_side_by_side_in_stub(client, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    monkeypatch.delenv("NEBIUS_API_KEY")
    r = await client.post("/compare", json={"messages": MESSAGES, "refs": [ref(), ref(model="nvidia/other")]})

    assert r.status_code == 200
    evs = events(r)
    text = answers(evs)
    assert text[0].startswith("stub-") and text[1].startswith("stub-") and text[0] != text[1]
    assert sorted((e["i"], e["usd"]) for e in evs if e.get("done")) == [(0, 0.0), (1, 0.0)]
    for i in (0, 1):  # each answer's deltas come before its done event
        mine = [e for e in evs if e["i"] == i]
        assert mine[-1].get("done") and not any(e.get("done") for e in mine[:-1])


async def test_keys_resolve_server_side_and_spend_lands_in_the_day_ledger(client, db, seeded_node_run, tf):
    sent, replies = tf
    await register(db, seeded_node_run[1], ENDPOINT + "/v1")
    replies[LIGHTNING] = (200, ["Kick", "backs."], {"prompt_tokens": 1_000_000, "completion_tokens": 500_000})
    replies["tuned"] = (200, ["Referral ", "fees."], {"prompt_tokens": 9, "completion_tokens": 9})

    r = await client.post("/compare", json={"messages": MESSAGES, "max_tokens": 64,
                                            "refs": [ref(), ref(ENDPOINT + "/v1", "tuned", "ORCHAPOD_ENDPOINT_TOKEN", LIGHTNING)]})

    assert r.status_code == 200
    evs = events(r)
    assert answers(evs) == {0: "Kickbacks.", 1: "Referral fees."}
    done = {e["i"]: e for e in evs if e.get("done")}
    assert done[0]["usd"] == pytest.approx(0.06 + 0.12) and done[1]["usd"] == 0.0  # our endpoints bill GPU hours
    assert sorted((url, auth) for url, auth, _ in sent) == [  # each key went only to its own pair
        (TF + "/chat/completions", "Bearer tf-key"), (ENDPOINT + "/v1/chat/completions", "Bearer ep-token")]
    assert {b["max_tokens"] for *_, b in sent} == {64} and {b["temperature"] for *_, b in sent} == {0.0}
    assert await ledger(db) == [pytest.approx(0.18)]
    assert "tf-key" not in r.text and "ep-token" not in r.text


@pytest.mark.parametrize("bad", [
    ref("https://evil.example/v1"),                                  # our Token Factory key to someone else's URL
    ref(TF + "/../v1"),
    ref(ENDPOINT, key="ORCHAPOD_ENDPOINT_TOKEN"),                     # an endpoint nobody registered
    ref(TF, key="ORCHAPOD_ENDPOINT_TOKEN"),
    ref("http://169.254.169.254/v1", key=""),                         # no key, any URL: an open proxy
    ref(TF, key="HF_TOKEN"),
])
async def test_pairs_outside_the_rule_are_422_and_nothing_is_sent(client, db, tf, bad):
    sent, _ = tf
    r = await client.post("/compare", json={"messages": MESSAGES, "refs": [ref(), bad]})
    assert r.status_code == 422 and "refused ModelRef" in r.json()["detail"]
    assert sent == [] and await ledger(db) == []


async def test_an_endpoint_counts_only_while_its_registration_holds(client, db, seeded_node_run, tf, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    node_run = seeded_node_run[1]
    body = {"messages": MESSAGES, "refs": [ref(ENDPOINT, "tuned", "ORCHAPOD_ENDPOINT_TOKEN")] * 2}
    await register(db, node_run, ENDPOINT + "/v1", minutes=-1)                     # expired
    await register(db, node_run, ENDPOINT, deleted_at="2026-10-21T00:00:00+00:00")  # deleted at expiry
    assert (await client.post("/compare", json=body)).status_code == 422
    await register(db, node_run, ENDPOINT + "/v1/")
    assert (await client.post("/compare", json=body)).status_code == 200


@pytest.mark.parametrize("model, status, code", [
    ("meta-llama/Llama-3.1-8B-Instruct", 200, 422),  # unpriced: the client refuses before sending (R5)
    (ULTRA, 404, 422),                               # Token Factory rejects the request
    (ULTRA, 401, 502),                               # Token Factory fails
])
async def test_refusals_are_http_errors_before_any_200(client, db, tf, model, status, code):
    _, replies = tf
    replies[model] = (status, ["never"], {})
    replies[LIGHTNING] = (200, ["ok"], {"prompt_tokens": 1, "completion_tokens": 1})
    r = await client.post("/compare", json={"messages": MESSAGES, "refs": [ref(), ref(model=model)]})
    assert r.status_code == code and "refs[1]" in r.json()["detail"]
    assert await ledger(db) == []  # the answer that had started is closed, unread


async def test_a_failure_mid_stream_ends_that_answer_with_an_error(client, db, tf, monkeypatch):
    _, replies = tf
    replies[LIGHTNING] = (200, ["ok"], {"prompt_tokens": 10, "completion_tokens": 10})
    real = TokenFactory.stream_chat

    def breaks(self, messages, model, **kw):
        yield from real(self, messages, model, **kw)
        if model == ULTRA:
            raise httpx.ReadError("connection reset")

    monkeypatch.setattr(TokenFactory, "stream_chat", breaks)
    replies[ULTRA] = (200, ["half"], {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    r = await client.post("/compare", json={"messages": MESSAGES, "refs": [ref(), ref(model=ULTRA)]})

    done = {e["i"]: e for e in events(r) if e.get("done")}
    assert done[1]["usd"] is None and "mid-stream" in done[1]["error"] and "connection reset" not in r.text
    assert done[0]["usd"] == pytest.approx(10 * 0.06 / 1e6 + 10 * 0.24 / 1e6)
    assert sorted(await ledger(db)) == [pytest.approx(done[0]["usd"]), pytest.approx(1.0)]  # billed, then broke


async def test_spend_is_recorded_when_nobody_reads_the_stream(db, tf):
    _, replies = tf
    replies[LIGHTNING] = (200, ["a"], {"prompt_tokens": 1_000_000, "completion_tokens": 0})
    body = route.CompareRequest(messages=MESSAGES, refs=[ref(), ref()])

    response = await route.compare(body, db, 1.0)  # the client hangs up before reading a byte
    await asyncio.wait_for(asyncio.gather(*route._streams), 5)

    assert response.status_code == 200 and await ledger(db) == [pytest.approx(0.06)] * 2


async def test_kill_switch_budget_and_request_bounds(client, db, monkeypatch):
    body = {"messages": MESSAGES, "refs": [ref(), ref()]}
    monkeypatch.setenv("ORCHAPOD_KILL_SWITCH", "1")
    assert (await client.post("/compare", json=body)).status_code == 503
    monkeypatch.delenv("ORCHAPOD_KILL_SWITCH")
    db.add(Spend(source="planner", usd=Decimal("1.5")))  # an anonymous caller's day ($15 x 0.1) is spent
    await db.commit()
    assert (await client.post("/compare", json=body)).status_code == 402
    for bad in ({**body, "refs": [ref()]}, {**body, "max_tokens": 0}, {**body, "max_tokens": 4096},
                {**body, "messages": []}, {**body, "messages": [{"role": "tool", "content": "x"}]}):
        assert (await client.post("/compare", json=bad)).status_code == 422
