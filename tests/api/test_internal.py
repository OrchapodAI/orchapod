"""
Tests for POST /internal/artifact, /internal/ttl, /internal/log
"""

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

    result = await db.exec(select(Artifact).where(Artifact.node_run_id == node_run.id))
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
    })

    result = await db.exec(
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
