"""
Tests for POST /nodes/run and GET /runs/{run_id}
"""

import uuid
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# POST /nodes/run
# ---------------------------------------------------------------------------

async def test_submit_valid_node_type_returns_202(client):
    with patch("asyncio.create_task"):
        resp = await client.post("/nodes/run", json={
            "node_type": "vllm-serve",
            "inputs": {"model": "Qwen/Qwen3-4B-Instruct", "keep_alive_min": 60},
        })

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "provisioning_gpu"
    assert "run_id" in body
    assert "node_run_id" in body
    assert body["status_url"].startswith("/runs/")


async def test_submit_invalid_node_type_returns_422(client):
    resp = await client.post("/nodes/run", json={
        "node_type": "does-not-exist",
        "inputs": {},
    })

    assert resp.status_code == 422
    assert "does-not-exist" in resp.json()["detail"]


async def test_submit_creates_run_in_db(client, db):
    from sqlmodel import select
    from api.models.db import Run

    with patch("asyncio.create_task"):
        resp = await client.post("/nodes/run", json={
            "node_type": "quantize",
            "inputs": {"model": "Qwen/Qwen3-4B-Instruct", "method": "gguf"},
        })

    run_id = resp.json()["run_id"]
    run = await db.get(Run, uuid.UUID(run_id))

    assert run is not None
    assert run.workflow_id is None  # standalone run has no workflow


# ---------------------------------------------------------------------------
# GET /runs/{run_id}
# ---------------------------------------------------------------------------

async def test_get_run_returns_status_and_nodes(client, seeded_node_run):
    run, node_run = seeded_node_run

    resp = await client.get(f"/runs/{run.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == str(run.id)
    assert body["status"] == "running"
    assert len(body["nodes"]) == 1
    assert body["nodes"][0]["node_type"] == "vllm-serve"
    assert body["nodes"][0]["status"] == "running"


async def test_get_run_includes_outputs(client, db, seeded_node_run):
    run, node_run = seeded_node_run

    node_run.outputs = {"endpoint_url": "https://pod-abc-8000.proxy.runpod.net/v1"}
    await db.commit()

    resp = await client.get(f"/runs/{run.id}")

    outputs = resp.json()["nodes"][0]["outputs"]
    assert outputs["endpoint_url"] == "https://pod-abc-8000.proxy.runpod.net/v1"


async def test_get_run_not_found_returns_404(client):
    resp = await client.get(f"/runs/{uuid.uuid4()}")

    assert resp.status_code == 404
