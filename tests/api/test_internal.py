"""
Tests for POST /internal/artifact, /internal/ttl, /internal/log
"""

import asyncio
import uuid

import pytest

from api.services.redact import REDACTED


# ---------------------------------------------------------------------------
# POST /internal/artifact
# ---------------------------------------------------------------------------

async def test_register_artifact_creates_record_and_updates_outputs(client, db, seeded_node_run):
    from sqlmodel import select
    from api.models.db import Artifact, NodeRun

    run, node_run = seeded_node_run

    resp = await client.post("/internal/artifact", json={
        "run_id":  str(run.id),
        "node_id": "node",
        "artifact": {
            "name":     "gguf_file",
            "uri":      "r2://orchapod-artifacts/runs/abc/node/gguf_file",
            "kind":     "model",
            "metadata": {"format": "gguf", "precision": "q4_k_m"},
        },
    })

    assert resp.status_code == 201

    result = await db.scalars(select(Artifact).where(Artifact.node_run_id == node_run.id))
    artifact = result.first()
    assert artifact is not None
    assert artifact.name == "gguf_file"
    assert artifact.uri  == "r2://orchapod-artifacts/runs/abc/node/gguf_file"
    assert artifact.meta["precision"] == "q4_k_m"

    await db.refresh(node_run)
    assert node_run.outputs["gguf_file"] == "r2://orchapod-artifacts/runs/abc/node/gguf_file"


async def test_register_artifact_unknown_run_returns_404(client):
    resp = await client.post("/internal/artifact", json={
        "run_id":  str(uuid.uuid4()),
        "node_id": "node",
        "artifact": {"name": "x", "uri": "r2://x", "kind": "model"},
    })

    assert resp.status_code == 404


async def test_register_artifact_unknown_kind_returns_422(client, seeded_node_run):
    run, _ = seeded_node_run

    resp = await client.post("/internal/artifact", json={
        "run_id":  str(run.id),
        "node_id": "node",
        "artifact": {"name": "x", "uri": "r2://x", "kind": "banana"},
    })

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /internal/ttl
# ---------------------------------------------------------------------------

async def test_register_ttl_stores_endpoint_url_in_outputs(client, db, seeded_node_run, no_bg_tasks, endpoints):
    run, node_run = seeded_node_run
    endpoints.urls["ep-1"] = "https://pod-abc-8000.proxy.runpod.net/v1"

    resp = await client.post("/internal/ttl", json={
        "run_id":         str(run.id),
        "node_id":        "node",
        "action":         "register_ttl",
        "keep_alive_min": 60,
        "endpoint_url":   "https://pod-abc-8000.proxy.runpod.net/v1",
        "endpoint_id":    "ep-1",
    })

    assert resp.status_code == 202
    assert resp.json()["keep_alive_min"] == 60

    await db.refresh(node_run)
    assert node_run.outputs["endpoint_url"] == "https://pod-abc-8000.proxy.runpod.net/v1"


async def test_register_ttl_creates_endpoint_artifact(client, db, seeded_node_run, no_bg_tasks, endpoints):
    from sqlmodel import select
    from api.models.db import Artifact, ArtifactKind

    run, node_run = seeded_node_run
    endpoints.urls["ep-1"] = "https://pod-abc-8000.proxy.runpod.net/v1"

    await client.post("/internal/ttl", json={
        "run_id":         str(run.id),
        "node_id":        "node",
        "action":         "register_ttl",
        "keep_alive_min": 30,
        "endpoint_url":   "https://pod-abc-8000.proxy.runpod.net/v1",
        "endpoint_id":    "ep-1",
    })

    result = await db.scalars(
        select(Artifact).where(
            Artifact.node_run_id == node_run.id,
            Artifact.kind        == ArtifactKind.ENDPOINT,
        )
    )
    artifact = result.first()
    assert artifact is not None
    assert artifact.uri == "https://pod-abc-8000.proxy.runpod.net/v1"
    assert artifact.meta["keep_alive_min"] == 30


async def test_register_ttl_unknown_run_returns_404(client, no_bg_tasks):
    resp = await client.post("/internal/ttl", json={
        "run_id":         str(uuid.uuid4()),
        "node_id":        "node",
        "action":         "register_ttl",
        "keep_alive_min": 60,
        "endpoint_url":   "https://example.com/v1",
        "endpoint_id":    "ep-1",
    })

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /internal/log
# ---------------------------------------------------------------------------

async def test_log_endpoint_returns_204(client):
    resp = await client.post("/internal/log", json={
        "run_id":  str(uuid.uuid4()),
        "node_id": "node",
        "ts":      "2026-05-05T10:00:00Z",
        "level":   "INFO",
        "message": "vLLM server is ready",
    })

    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# POST /internal/log keeps the lines for GET /runs/{id}/logs (contracts "Run control API")
# ---------------------------------------------------------------------------

def line(run, message, node="node", level="INFO"):
    return {"run_id": str(run.id), "node_id": node, "ts": "2026-10-25T10:00:00+00:00", "level": level, "message": message}


async def post_lines(client, run, *messages, node="node"):
    for message in messages:
        assert (await client.post("/internal/log", json=line(run, message, node))).status_code == 204


async def logs(client, run, **params):
    r = await client.get(f"/runs/{run.id}/logs", params=params)
    assert r.status_code == 200
    return r.json()


async def test_log_lines_are_kept_oldest_first_and_filtered_by_node(client, seeded_node_run):
    run, _ = seeded_node_run
    for i, node in enumerate("abab"):
        await post_lines(client, run, f"line {i}", node=node)

    assert [(row["node_id"], row["message"]) for row in await logs(client, run)] == [
        ("a", "line 0"), ("b", "line 1"), ("a", "line 2"), ("b", "line 3")]
    assert [row["message"] for row in await logs(client, run, node_id="b")] == ["line 1", "line 3"]
    assert [row["message"] for row in await logs(client, run, limit=3)] == ["line 1", "line 2", "line 3"]  # the last 3
    assert await logs(client, run, node_id="b", limit=1) == [
        {"ts": "2026-10-25T10:00:00+00:00", "level": "INFO", "node_id": "b", "message": "line 3"}]


async def test_logs_default_to_the_last_500_within_1_to_2000_and_need_a_known_run(client, db, seeded_node_run):
    from api.models.db import NodeLog
    run, _ = seeded_node_run
    db.add_all(NodeLog(run_id=run.id, node_id="node", ts="t", level="INFO", message=f"line {i}") for i in range(600))
    await db.commit()

    default = await logs(client, run)
    assert (len(default), default[0]["message"], default[-1]["message"]) == (500, "line 100", "line 599")
    assert len(await logs(client, run, limit=2000)) == 600
    for bad in (0, 2001):
        assert (await client.get(f"/runs/{run.id}/logs", params={"limit": bad})).status_code == 422
    assert (await client.get(f"/runs/{uuid.uuid4()}/logs")).status_code == 404


async def test_only_the_last_lines_of_each_run_are_kept(client, db, seeded_node_run, monkeypatch):
    from sqlalchemy import func
    from sqlmodel import select
    from api.models.db import NodeLog, Run
    monkeypatch.setattr("api.services.logs.LOG_KEEP", 3)
    run, _ = seeded_node_run
    other = Run(user_id=uuid.uuid4())
    db.add(other)
    await db.commit()

    await post_lines(client, other, "other 0")
    await post_lines(client, run, *(f"line {i}" for i in range(5)))

    assert [row["message"] for row in await logs(client, run)] == ["line 2", "line 3", "line 4"]
    assert [row["message"] for row in await logs(client, other)] == ["other 0"]  # a run is trimmed against its own lines
    assert await db.scalar(select(func.count()).select_from(NodeLog)) == 4  # deleted, not just hidden


async def test_log_lines_are_cut_at_2000_chars_and_redacted_like_public_outputs(client, db, seeded_node_run):
    from tests.api.test_executor import published
    run, node_run = seeded_node_run
    secrets = ('env NEBIUS_API_KEY=sk-123, {"api_key": "sk-456"}, Authorization: Bearer abc.def; x-amz-security-token=t0k '
               'max_tokens=512 token_count: 7 api_key_env=NEBIUS_API_KEY')
    redacted = ('env NEBIUS_API_KEY=[redacted], {"api_key": "[redacted]"}, Authorization: [redacted]; '
                'x-amz-security-token=[redacted] max_tokens=512 token_count: 7 api_key_env=NEBIUS_API_KEY')

    grows = "api_key=a " * 300  # cut at 2000 chars, each short value then becomes "[redacted]": cut again, still 2000
    await post_lines(client, run, secrets, "x" * 2500, grows)
    await client.post("/internal/log", json=line(run, "boom api_key=sk-789", level="ERROR"))

    expected = [redacted, "x" * 2000, ("api_key=[redacted] " * 200)[:2000], "boom api_key=[redacted]"]
    assert [row["message"] for row in await logs(client, run)] == expected
    assert [e["message"] for e in published() if e["type"] == "log"] == expected
    await db.refresh(node_run)
    assert node_run.error == "boom api_key=[redacted]"  # the node's error is public too


async def test_a_line_with_nul_or_a_lone_surrogate_is_stored_without_them(client, seeded_node_run):
    """Postgres refuses NUL in text, and no database takes a lone surrogate (a node that decodes bytes with surrogateescape
    sends them): the line used to be a 500, and with it the node's error update. clean() drops the first and replaces the
    second, so the stored line is the text the node meant."""
    from api.services.logs import clean
    assert clean("a\x00b\ud800c\udc00d\U0001F600") == "ab?c?d\U0001F600"  # NUL gone; a lone surrogate "?"; a real emoji stays
    run, node_run = seeded_node_run
    for sent in ('"x\\u0000y"', '"x\\ud800y"', '"api_key=k\\u0000k tail"'):  # JSON escapes: httpx would not send a raw surrogate
        body = ('{"run_id": "%s", "node_id": "node", "ts": "t", "level": "ERROR", "message": %s}' % (run.id, sent)).encode()
        assert (await client.post("/internal/log", content=body, headers={"Content-Type": "application/json"})).status_code == 204
    assert [row["message"] for row in await logs(client, run)] == ["xy", "x?y", f"api_key={REDACTED} tail"]


@pytest.mark.parametrize("field, limit", [("node_id", 128), ("ts", 64), ("level", 16)])
async def test_a_log_line_longer_than_its_field_limit_is_refused_and_the_table_agrees(client, db, seeded_node_run, field, limit):
    """node_id, ts and level are short by nature; a node (it holds the internal secret) cannot fill the table with a megabyte
    of one: 422 beyond the limit, and the column is a VARCHAR of that length on Postgres."""
    from api.models.db import NodeLog
    run, _ = seeded_node_run
    at_limit = {**line(run, "m"), field: "x" * limit}
    assert (await client.post("/internal/log", json=at_limit)).status_code == 204
    assert (await client.post("/internal/log", json={**at_limit, field: "x" * (limit + 1)})).status_code == 422
    assert NodeLog.__table__.c[field].type.length == limit


# ---------------------------------------------------------------------------
# Endpoint expiry: deleted at expires_at, recorded as meta.deleted_at, no status change; re-armed at startup
# ---------------------------------------------------------------------------

class Endpoints:
    """NebiusServerless().endpoints as the TTL routes use it (contracts "NebiusServerless", platform-w5): get(id) reports
    the endpoint's URL (`urls`, else https://ep.example); delete(id) raises `errors`, in turn, first."""

    def __init__(self):
        self.deleted, self.errors, self.got, self.urls = [], [], [], {}

    def get(self, endpoint_id):
        self.got.append(endpoint_id)
        return {"id": endpoint_id, "state": "RUNNING", "url": self.urls.get(endpoint_id, "https://ep.example")}

    def delete(self, endpoint_id):
        self.deleted.append(endpoint_id)
        if self.errors:
            raise self.errors.pop(0)


@pytest.fixture
def endpoints(db, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from api.routes import internal
    fake, slept = Endpoints(), []

    async def sleep(seconds):  # time passes at once; each wait is recorded
        slept.append(round(seconds))

    monkeypatch.setattr(internal, "_endpoints", lambda: fake)
    monkeypatch.setattr(internal, "sleep", sleep)
    monkeypatch.setattr(internal, "_ttl_tasks", {})  # no_bg_tasks tests leave MagicMocks in the module's
    monkeypatch.setattr(internal, "AsyncSessionLocal", async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False))
    fake.slept = slept
    yield fake
    for task in list(internal._ttl_tasks.values()):
        task.cancel()


async def expiries():
    from api.routes import internal
    await asyncio.wait_for(asyncio.gather(*internal._ttl_tasks.values()), 5)  # a stuck expiry fails, never hangs


TTL = {"node_id": "node", "action": "register_ttl", "keep_alive_min": 30, "endpoint_url": "https://ep.example",
       "endpoint_id": "ep-1"}


async def test_register_ttl_needs_the_endpoint_id_and_at_most_120_min(client, seeded_node_run, no_bg_tasks):
    run, _ = seeded_node_run
    body = {**TTL, "run_id": str(run.id)}
    for bad in ({k: v for k, v in body.items() if k != "endpoint_id"}, {**body, "keep_alive_min": 0},
                {**body, "keep_alive_min": 121}):
        assert (await client.post("/internal/ttl", json=bad)).status_code == 422


async def test_an_endpoint_is_deleted_at_its_expiry_and_no_status_changes(client, db, seeded_node_run, endpoints):
    from sqlmodel import select
    from api.models.db import Artifact, NodeStatus, RunStatus
    from api.services.events import event_bus
    run, node_run = seeded_node_run

    assert (await client.post("/internal/ttl", json={**TTL, "run_id": str(run.id)})).status_code == 202
    await expiries()

    assert endpoints.deleted == ["ep-1"]
    assert endpoints.slept[0] in (1199, 1200) and endpoints.slept[1] in (599, 600)  # a warning 10 min before, then expiry
    assert {"type": "endpoint_expiry", "node_run_id": str(node_run.id), "minutes_remaining": 10} in [
        c.args[1] for c in event_bus.publish.await_args_list]
    endpoint = await db.scalar(select(Artifact).where(Artifact.name == "endpoint_url"))
    await db.refresh(endpoint)
    assert endpoint.meta["endpoint_id"] == "ep-1" and endpoint.meta["deleted_at"]  # /compare stops trusting it
    for row in (run, node_run):
        await db.refresh(row)
    assert (run.status, node_run.status) == (RunStatus.RUNNING, NodeStatus.RUNNING)  # expiry changes no status


async def test_a_404_is_done_a_stub_endpoint_is_never_called_and_a_failed_delete_is_retried(client, db, seeded_node_run,
                                                                                           endpoints):
    from sqlmodel import select
    from api.models.db import Artifact
    from packages.providers.base import ProviderError
    run, _ = seeded_node_run
    endpoints.errors = [ProviderError("nebius_serverless", "server", 503, "busy"),
                        ProviderError("nebius_serverless", "bad_request", 404, "not found")]
    for endpoint_id, url in (("ep-gone", "https://ep.example"), ("stub-orchapod-1234-serve", "http://stub.invalid")):
        await client.post("/internal/ttl", json={**TTL, "run_id": str(run.id), "endpoint_id": endpoint_id,
                                                 "endpoint_url": url})
        await expiries()  # one at a time: the in-memory database shares one connection between their sessions
    assert endpoints.got == ["ep-gone"]  # a stub endpoint never exists at Nebius

    assert endpoints.deleted == ["ep-gone", "ep-gone"]  # the 503 is tried again, then the 404 means it is gone
    rows = (await db.scalars(select(Artifact).where(Artifact.name == "endpoint_url"))).all()
    for row in rows:
        await db.refresh(row)
    assert all(r.meta.get("deleted_at") for r in rows) and len(rows) == 2


async def test_the_startup_sweep_rearms_every_endpoint_not_yet_deleted(db, seeded_node_run, endpoints, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from api.models.db import Artifact, ArtifactKind
    from api.routes import internal
    run, node_run = seeded_node_run
    now = datetime.now(timezone.utc)

    def endpoint(endpoint_id, minutes, **meta):
        a = Artifact(node_run_id=node_run.id, name="endpoint_url", kind=ArtifactKind.ENDPOINT, uri=f"https://{endpoint_id}",
                     meta={"endpoint_id": endpoint_id, "expires_at": (now + timedelta(minutes=minutes)).isoformat(), **meta})
        db.add(a)
        return a
    expired = endpoint("ep-expired", -5)
    endpoint("ep-live", 60)
    endpoint("ep-deleted", -5, deleted_at=now.isoformat())
    db.add(Artifact(node_run_id=node_run.id, name="endpoint_url", kind=ArtifactKind.ENDPOINT, uri="https://legacy",
                    meta={"expires_at": now.isoformat()}))  # a vast.ai pod's, without an endpoint id: nothing to delete
    await db.commit()
    armed, arm = [], internal._arm
    monkeypatch.setattr(internal, "_arm", lambda a, run_id: armed.append((a.meta["endpoint_id"], run_id)))

    await internal.resume_ttls()  # an API restart: the timers lived only in memory

    assert sorted(armed) == [("ep-expired", run.id), ("ep-live", run.id)]
    arm(expired, run.id)  # one whose expiry passed while the API was down goes at once
    await expiries()
    assert (endpoints.deleted, endpoints.slept) == (["ep-expired"], [0])


async def test_an_endpoint_id_is_an_id_never_a_rest_path(client, db, seeded_node_run, endpoints):
    """The id becomes a REST path segment, and httpx resolves /endpoints/../jobs/x to /jobs/x: a node (which holds the
    internal secret, gpu Jobs running third-party code included) must not make the API delete any job or endpoint."""
    from datetime import datetime, timedelta, timezone
    from sqlmodel import select
    from api.models.db import Artifact, ArtifactKind
    from api.routes import internal
    run, node_run = seeded_node_run
    for bad in ("../jobs/aijob-1", "", "EP-1", "-ep", "e" * 64, "ep-1\n"):
        assert (await client.post("/internal/ttl", json={**TTL, "run_id": str(run.id), "endpoint_id": bad})).status_code == 422
    assert (await db.scalars(select(Artifact))).all() == []

    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()  # stored before this check
    db.add(Artifact(node_run_id=node_run.id, name="endpoint_url", kind=ArtifactKind.ENDPOINT, uri="https://x",
                    meta={"endpoint_id": "../jobs/aijob-1", "expires_at": past}))
    await db.commit()
    await internal.resume_ttls()
    assert (internal._ttl_tasks, endpoints.deleted) == ({}, [])


@pytest.mark.parametrize("error, tries, deleted", [
    (("bad_request", 400, "invalid id"), 1, False),   # refused for good: never retried every 5 min
    (("auth", 401, "unauthenticated"), 1, False),
    (("auth", 403, "permission denied"), 1, False),
    (("server", 408, "request timeout"), 2, True),    # transient: tried again
    (("bad_request", 409, "operation in progress"), 2, True),
    (("rate_limit", 429, "slow down"), 2, True),
    (("server", 499, "client closed"), 2, True),
    (("server", 503, "unavailable"), 2, True),
])
async def test_only_400_401_or_403_end_the_delete_retries(client, db, seeded_node_run, endpoints, error, tries, deleted):
    from sqlmodel import select
    from api.models.db import Artifact
    from packages.providers.base import ProviderError
    run, _ = seeded_node_run
    endpoints.errors = [ProviderError("nebius_serverless", *error)]
    await client.post("/internal/ttl", json={**TTL, "run_id": str(run.id)})
    await expiries()

    row = await db.scalar(select(Artifact).where(Artifact.name == "endpoint_url"))
    await db.refresh(row)
    assert (len(endpoints.deleted), bool(row.meta.get("deleted_at"))) == (tries, deleted)


async def test_registering_an_endpoint_again_supersedes_its_earlier_row(client, db, seeded_node_run, endpoints, monkeypatch):
    """One endpoint, one live expiry: a re-register (a retried registration) cancels the earlier timer, and neither the
    startup sweep nor /compare trusts the earlier row any longer."""
    from sqlmodel import select
    from api.models.db import Artifact
    from api.routes import compare, internal
    run, _ = seeded_node_run
    armed = []
    monkeypatch.setattr(internal, "_expire", lambda *a: armed.append(a[1]) or asyncio.sleep(3600))  # a timer that waits
    await client.post("/internal/ttl", json={**TTL, "run_id": str(run.id), "keep_alive_min": 60})
    first = next(iter(internal._ttl_tasks.values()))
    await client.post("/internal/ttl", json={**TTL, "run_id": str(run.id), "keep_alive_min": 30})
    await asyncio.sleep(0)

    old, new = sorted((await db.scalars(select(Artifact).where(Artifact.name == "endpoint_url"))).all(),
                      key=lambda a: a.meta["keep_alive_min"], reverse=True)
    await db.refresh(old)
    assert old.meta.get("superseded_at") and not new.meta.get("superseded_at")
    assert first.cancelled() and list(internal._ttl_tasks) == [str(new.id)]
    new.meta = {**new.meta, "deleted_at": "2026-10-24T00:00:00+00:00"}  # the newer row expired and was deleted
    await db.commit()
    assert not await compare._registered(db, "https://ep.example")  # the superseded row's later expiry trusts nothing
    internal._ttl_tasks.pop(str(new.id)).cancel()
    await internal.resume_ttls()
    assert internal._ttl_tasks == {}  # neither row is live


async def test_a_registration_never_extends_a_live_endpoint(client, db, seeded_node_run, endpoints, monkeypatch):
    """Another run's node (any holder of the internal secret, a gpu Job's third-party code included; endpoint ids are
    public in summaries) re-registers run A's endpoint with a later expiry, again and again: the endpoint must still be
    deleted at A's expiry, by A's timer. A sooner registration still takes over."""
    from sqlmodel import select
    from api.models.db import Artifact, NodeRun, Run, RunStatus
    from api.routes import internal
    run, _ = seeded_node_run
    other = Run(user_id=uuid.uuid4(), status=RunStatus.RUNNING)
    db.add(other)
    await db.flush()
    db.add(NodeRun(run_id=other.id, node_id="intruder", node_type="unsloth-train"))
    await db.commit()
    monkeypatch.setattr(internal, "_expire", lambda *a: asyncio.sleep(3600))  # timers that wait, as they would for real

    expiry = (await client.post("/internal/ttl", json={**TTL, "run_id": str(run.id), "keep_alive_min": 30})).json()["expires_at"]
    timer = next(iter(internal._ttl_tasks.values()))
    for _ in range(3):  # each time before the expiry
        r = await client.post("/internal/ttl", json={**TTL, "run_id": str(other.id), "node_id": "intruder",
                                                     "keep_alive_min": 120})
        assert (r.status_code, r.json()["expires_at"]) == (202, expiry)
    await asyncio.sleep(0)
    live = [a for a in await db.scalars(select(Artifact).where(Artifact.name == "endpoint_url")) if internal._live(a.meta)]
    assert [a.meta["expires_at"] for a in live] == [expiry] and live[0].node_run_id != (await db.scalar(
        select(NodeRun.id).where(NodeRun.node_id == "intruder")))
    assert list(internal._ttl_tasks.values()) == [timer] and not timer.cancelled()  # A's timer, kept

    sooner = await client.post("/internal/ttl", json={**TTL, "run_id": str(run.id), "keep_alive_min": 10})
    await asyncio.sleep(0)
    assert sooner.json()["expires_at"] < expiry and timer.cancelled() and len(internal._ttl_tasks) == 1


@pytest.mark.parametrize("usd", ["NaN", "Infinity", "-inf", "1e999", "lots", 6.01])  # $3 run cap: at most $6
async def test_a_cost_json_must_be_a_finite_amount_within_twice_the_run_cap(client, db, seeded_node_run, usd, caplog):
    """A compromised node (gpu Jobs run third-party code) must not poison Run.cost_usd, nor swamp it: one huge finite
    report would block the whole UTC day."""
    run, _ = seeded_node_run
    r = await client.post("/internal/artifact", json={"run_id": str(run.id), "node_id": "node", "artifact": {
        "name": "cost_json", "uri": "r2://b/runs/x/node/cost_json", "kind": "metrics", "metadata": {"usd": usd, "seq": 1}}})
    await db.refresh(run)
    assert (r.status_code, run.cost_usd) == (422, None) and "refused a cost_json" in caplog.text
    ok = await client.post("/internal/artifact", json={"run_id": str(run.id), "node_id": "node", "artifact": {
        "name": "cost_json", "uri": "r2://b/runs/x/node/cost_json", "kind": "metrics", "metadata": {"usd": 6.0, "seq": 2}}})
    await db.refresh(run)
    assert (ok.status_code, float(run.cost_usd)) == (201, 6.0)  # twice the cap is still accepted


async def test_timers_change_only_after_the_registration_is_committed(client, db, seeded_node_run, endpoints, monkeypatch):
    """A sooner re-register whose commit fails (the reviewer sent an endpoint_url that SQLite cannot encode) must leave
    the live timer alone; one whose event then fails (Redis down) is already armed."""
    from api.routes import internal
    from api.services.events import event_bus
    run_id = str(seeded_node_run[0].id)  # read now: the rollback below expires the test's objects
    monkeypatch.setattr(internal, "_expire", lambda *a: asyncio.sleep(3600))  # timers that wait, as they would for real
    await client.post("/internal/ttl", json={**TTL, "run_id": run_id, "keep_alive_min": 30})
    (live,) = internal._ttl_tasks.values()

    commit = db.commit

    async def broken():
        raise RuntimeError("cannot encode the row")

    monkeypatch.setattr(db, "commit", broken)
    with pytest.raises(RuntimeError):
        await client.post("/internal/ttl", json={**TTL, "run_id": run_id, "keep_alive_min": 1})
    monkeypatch.setattr(db, "commit", commit)
    await db.rollback()
    await asyncio.sleep(0)
    assert list(internal._ttl_tasks.values()) == [live] and not live.cancelled()

    event_bus.publish.side_effect = ConnectionError("redis down")
    with pytest.raises(ConnectionError):
        await client.post("/internal/ttl", json={**TTL, "run_id": run_id, "keep_alive_min": 1})
    await asyncio.sleep(0)
    assert live.cancelled() and len(internal._ttl_tasks) == 1  # the sooner registration's timer, armed before the event


async def test_only_internal_ttl_records_an_endpoint(client, db, seeded_node_run):
    """A node forging a live endpoint row through /internal/artifact could make the real registration supersede
    nothing, crash /internal/ttl or the startup sweep, or have /compare send the endpoint token to its own URL."""
    from sqlmodel import select
    from api.models.db import Artifact
    run, _ = seeded_node_run
    r = await client.post("/internal/artifact", json={"run_id": str(run.id), "node_id": "node", "artifact": {
        "name": "endpoint_url", "uri": "https://attacker.example", "kind": "endpoint",
        "metadata": {"endpoint_id": "ep-1", "expires_at": "2099-01-01T00:00:00+00:00"}}})
    assert r.status_code == 422 and (await db.scalars(select(Artifact))).all() == []


@pytest.mark.parametrize("reported, status", [
    ({"url": "https://attacker.example"}, 422),  # not the URL Nebius reports: the token would go there
    ({"url": None}, 422),                         # not running yet
    (RuntimeError("nebius down"), 502),
])
async def test_a_registration_stores_the_url_nebius_reports(client, db, seeded_node_run, endpoints, monkeypatch,
                                                           reported, status):
    from sqlmodel import select
    from api.models.db import Artifact
    from api.routes import internal
    run, node_run = seeded_node_run

    def get(endpoint_id):
        if isinstance(reported, Exception):
            raise reported
        return {"id": endpoint_id, **reported}

    monkeypatch.setattr(endpoints, "get", get)
    r = await client.post("/internal/ttl", json={**TTL, "run_id": str(run.id)})  # the node says https://ep.example
    assert (r.status_code, (await db.scalars(select(Artifact))).all(), internal._ttl_tasks) == (status, [], {})


async def test_a_registered_endpoint_is_the_url_nebius_reports(client, db, seeded_node_run, endpoints, monkeypatch):
    from api.routes import internal
    run, node_run = seeded_node_run
    monkeypatch.setattr(internal, "_expire", lambda *a: asyncio.sleep(3600))
    r = await client.post("/internal/ttl", json={**TTL, "run_id": str(run.id), "endpoint_url": "https://ep.example"})
    await db.refresh(node_run)
    assert (r.status_code, endpoints.got, node_run.outputs["endpoint_url"]) == (202, ["ep-1"], "https://ep.example")


async def test_the_startup_sweep_skips_a_row_it_cannot_read(db, seeded_node_run, endpoints, monkeypatch):
    """A junk or timezone-less expires_at (stored before endpoint rows came only from /internal/ttl) is logged and
    skipped: it never stops the API from starting, nor makes /compare fail."""
    from datetime import datetime, timedelta, timezone
    from api.models.db import Artifact, ArtifactKind
    from api.routes import compare, internal
    _, node_run = seeded_node_run
    later = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    for endpoint_id, expires_at in (("ep-junk", "soon"), ("ep-naive", "2099-01-01T00:00:00"), ("ep-good", later)):
        db.add(Artifact(node_run_id=node_run.id, name="endpoint_url", kind=ArtifactKind.ENDPOINT,
                        uri=f"https://{endpoint_id}.example", meta={"endpoint_id": endpoint_id, "expires_at": expires_at}))
    db.add(Artifact(node_run_id=node_run.id, name="endpoint_url", kind=ArtifactKind.ENDPOINT, uri="https://x.example",
                    meta=["not", "a", "dict"]))
    await db.commit()
    armed = []
    monkeypatch.setattr(internal, "_arm", lambda a, run_id: armed.append(a.meta["endpoint_id"]))

    await internal.resume_ttls()

    assert armed == ["ep-good"]
    assert not await compare._registered(db, "https://ep-naive.example")  # no 500 either
    assert await compare._registered(db, "https://ep-good.example")
