"""
Tests for POST /internal/artifact, /internal/ttl, /internal/log
"""

import asyncio
import uuid

import pytest


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

async def test_register_ttl_stores_endpoint_url_in_outputs(client, db, seeded_node_run, no_bg_tasks):
    run, node_run = seeded_node_run

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


async def test_register_ttl_creates_endpoint_artifact(client, db, seeded_node_run, no_bg_tasks):
    from sqlmodel import select
    from api.models.db import Artifact, ArtifactKind

    run, node_run = seeded_node_run

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
# Endpoint expiry: deleted at expires_at, recorded as meta.deleted_at, no status change; re-armed at startup
# ---------------------------------------------------------------------------

class Endpoints:
    """NebiusServerless().endpoints as expiry uses it (contracts "NebiusServerless", platform-w5): delete(endpoint_id).
    `errors` are raised by the first deletes, in turn."""

    def __init__(self):
        self.deleted, self.errors = [], []

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
    for endpoint_id in ("ep-gone", "stub-orchapod-1234-serve"):
        await client.post("/internal/ttl", json={**TTL, "run_id": str(run.id), "endpoint_id": endpoint_id})
    await expiries()

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
    (("auth", 403, "permission denied"), 1, False),   # refused for good: never retried every 5 min
    (("bad_request", 400, "invalid id"), 1, False),
    (("rate_limit", 429, "slow down"), 2, True),      # tried again
])
async def test_a_4xx_other_than_404_or_429_ends_the_retries(client, db, seeded_node_run, endpoints, error, tries, deleted):
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
