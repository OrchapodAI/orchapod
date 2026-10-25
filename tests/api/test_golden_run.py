"""`make demo` (scripts/seed-golden-run.py): the golden run seeds into the API's database and object store, renders through
the API without a model call, replaces itself when seeded again, and --export writes back exactly what seeding reads."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models.db import AgentRun, Artifact, ArtifactKind, CancelToken, Model, NodeRun, Run, Spend
from api.agent import planner
from api.services import storage

_spec = importlib.util.spec_from_file_location("seed_golden_run", Path(__file__).parents[2] / "scripts/seed-golden-run.py")
golden = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(golden)
FIXTURE = json.loads(golden.FIXTURE.read_text())


class FakeS3:
    """The object store, by (bucket, key); presigning needs no network."""

    class exceptions:
        NoSuchKey = KeyError

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[Bucket, Key] = Body

    def get_object(self, Bucket, Key):
        body = self.objects[Bucket, Key]
        return {"ContentLength": len(body), "Body": io.BytesIO(body)}

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"http://store/{Params['Bucket']}/{Params['Key']}"


@pytest.fixture
def s3(monkeypatch, db):
    """The hosted app: its own bucket, the test database, no model call possible."""
    fake = FakeS3()
    monkeypatch.setenv("ORCHAPOD_R2_BUCKET", "hosted-bucket")
    monkeypatch.setattr(storage, "_get_client", lambda: fake)
    monkeypatch.setattr(storage, "ensure_bucket_exists", lambda: None)
    monkeypatch.setattr("api.database.create_tables", AsyncMock())
    monkeypatch.setattr("api.database.AsyncSessionLocal",
                        async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False))
    monkeypatch.setattr(planner, "write_report", AsyncMock(side_effect=AssertionError("the report must come cached")))
    return fake


async def test_the_golden_run_renders_from_the_seed_alone(client, db, s3):
    run_id = await golden.seed(FIXTURE)

    run = (await client.get(f"/runs/{run_id}")).json()
    assert run["status"] == "succeeded" and run["created_at"] == FIXTURE["run"]["created_at"]  # never today's spend
    assert run["gpu_provider"] == "nebius"  # its first GPU node's: not the last node's local-docker, which Run.gpu_provider holds
    summary = (await client.get(f"/runs/{run_id}/summary")).json()
    where = {n["node_id"]: (n["provider"], n["resource"] and n["resource"]["kind"]) for n in summary["nodes"]}
    assert (where["train"], where["serve"]) == (("nebius", "job"), ("local-docker", "endpoint"))  # nothing asked of Nebius
    assert [(n["node_id"], n["status"]) for n in summary["nodes"]] == [(n["node_id"], "succeeded") for n in FIXTURE["nodes"]]
    names = {(a["node_id"], a["name"]) for a in summary["artifacts"]}
    assert {(n["node_id"], "logs") for n in FIXTURE["nodes"]} <= names and ("evaluate", "eval_summary") in names
    nodes = (await client.get(f"/runs/{run_id}/nodes")).json()
    assert "r2://hosted-bucket/runs/" in json.dumps(nodes) and FIXTURE["bucket"] not in json.dumps([nodes, summary])

    report = (await client.get(f"/agent/runs/{run_id}/report")).json()
    assert report["ready"] and report["markdown"] == FIXTURE["agent_run"]["report_md"]

    link = next(a["download_url"] for a in summary["artifacts"] if a["name"] == "eval_summary")
    r = await client.get(link)
    assert r.status_code == 307
    verdicts = json.loads(s3.objects["hosted-bucket", r.headers["location"].split("/hosted-bucket/")[1]])
    assert verdicts["samples"] and {"n", "judged", "wins", "ties", "losses", "win_rate", "consistency"} <= set(verdicts)
    assert await db.scalar(select(func.count()).select_from(Spend)) == 0


def moved(fixture):
    """The fixture as seeding leaves it: its r2:// URIs, in the log lines too, point at the hosted bucket."""
    return json.loads(json.dumps(fixture).replace(f"r2://{fixture['bucket']}/", "r2://hosted-bucket/"))


def logged(fixture):
    """(node_id, ts, level, message) of the fixture's `logs` artifacts in run order, without their PROGRESS lines: those went
    to /internal/progress, which stores nothing, so a live run's history has none either."""
    run = fixture["run"]["id"]
    return [(n["node_id"], r["ts"], r["level"], r["message"]) for n in fixture["nodes"]
            for r in map(json.loads, fixture["objects"].get(f"runs/{run}/{n['node_id']}/logs", "").splitlines())
            if r["level"] != "PROGRESS"]


async def lines(client, run_id, **params):
    r = await client.get(f"/runs/{run_id}/logs", params={"limit": 2000, **params})
    assert r.status_code == 200
    return [(x["node_id"], x["ts"], x["level"], x["message"]) for x in r.json()]


async def test_the_seeded_run_keeps_the_log_lines_its_nodes_wrote(client, db, s3):
    run_id = await golden.seed(FIXTURE)
    expected = logged(moved(FIXTURE))
    assert len(expected) > 5

    assert await lines(client, run_id) == expected
    last = expected[-1][0]
    assert await lines(client, run_id, node_id=last) == [x for x in expected if x[0] == last]
    await golden.seed(FIXTURE)  # seeded again: the run is replaced with its lines, none twice
    assert await lines(client, run_id) == expected


async def test_seeding_replaces_a_run_started_by_the_agent(client, db, s3):
    """The live golden run was started by /agent/run, so the hosted database holds its cancel token: reseeding there must
    replace the run, not stop at the token's foreign key (Postgres, 2026-10-25)."""
    run_id = await golden.seed(FIXTURE)
    db.add(CancelToken(run_id=run_id, sha256="0" * 64))
    await db.commit()
    assert await golden.seed(FIXTURE) == run_id
    assert await db.scalar(select(func.count()).select_from(CancelToken).where(CancelToken.run_id == run_id)) == 0


async def test_seeding_trims_and_redacts_the_log_lines_like_internal_log(client, db, s3, monkeypatch):
    monkeypatch.setattr("api.services.logs.LOG_KEEP", 3)
    last = FIXTURE["nodes"][-1]["node_id"]
    key = f"runs/{FIXTURE['run']['id']}/{last}/logs"
    secret = json.dumps({"ts": "2026-10-25T09:00:00+00:00", "level": "INFO", "message": "export NEBIUS_API_KEY=sk-live ok"})
    fixture = {**FIXTURE, "objects": {**FIXTURE["objects"], key: FIXTURE["objects"][key].rstrip("\n") + "\n" + secret + "\n"}}

    run_id = await golden.seed(fixture)

    assert await lines(client, run_id) == [*logged(moved(fixture))[-3:-1], (last, "2026-10-25T09:00:00+00:00", "INFO",
                                                                      "export NEBIUS_API_KEY=[redacted] ok")]


async def test_seeding_again_replaces_the_run(db, s3):
    run_id = await golden.seed(FIXTURE)
    node = await db.scalar(select(NodeRun).where(NodeRun.run_id == run_id))
    db.add(Artifact(node_run_id=node.id, name="stray", kind=ArtifactKind.LOG, uri="r2://hosted-bucket/stray"))
    await db.commit()

    assert await golden.seed(FIXTURE) == run_id
    counts = [await db.scalar(select(func.count()).select_from(t)) for t in (Run, NodeRun, Artifact, Model, AgentRun)]
    assert counts == [1, len(FIXTURE["nodes"]), len(FIXTURE["artifacts"]), len(FIXTURE["models"]), 1]


async def test_export_writes_back_what_seeding_reads(db, s3):
    run_id = await golden.seed(FIXTURE)
    assert await golden.export(run_id) == {**moved(FIXTURE), "bucket": "hosted-bucket"}


async def test_export_never_writes_a_token_into_the_fixture(db, s3):
    run_id = await golden.seed(FIXTURE)
    node = await db.scalar(select(NodeRun).where(NodeRun.run_id == run_id))
    db.add(Artifact(node_run_id=node.id, name="old_key", kind=ArtifactKind.ENDPOINT, uri="https://e.example/v1",
                    meta={"api_key": "sk-live"}))  # stored before /internal/artifact redacted (R10)
    await db.commit()
    assert "sk-live" not in json.dumps(await golden.export(run_id))
