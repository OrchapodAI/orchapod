"""
Tests for the run lifecycle API:
  POST /inference/deploy   — one-click model deployment (creates workflow + run)
  POST /runs               — create a run from an existing workflow
  GET  /runs/{run_id}      — get run status
  GET  /runs/{run_id}/nodes — get node runs for a run
"""

import uuid

import pytest


# ---------------------------------------------------------------------------
# POST /inference/deploy  (one-click node execution)
# ---------------------------------------------------------------------------

async def test_deploy_valid_model_returns_202(client, no_bg_tasks):
    resp = await client.post("/inference/deploy", json={
        "model": "Qwen/Qwen3-4B-Instruct",
        "mode":  "serve",
    })

    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "provisioning_gpu"
    assert "run_id" in body
    assert "workflow_id" in body
    assert body["model"] == "Qwen/Qwen3-4B-Instruct"


async def test_deploy_invalid_mode_returns_422(client):
    resp = await client.post("/inference/deploy", json={
        "model": "Qwen/Qwen3-4B-Instruct",
        "mode":  "does-not-exist",
    })

    assert resp.status_code == 422


async def test_deploy_creates_workflow_and_run_in_db(client, db, no_bg_tasks):
    from sqlmodel import select
    from api.models.db import Run, Workflow

    resp = await client.post("/inference/deploy", json={
        "model": "Qwen/Qwen3-4B-Instruct",
        "mode":  "quantize-serve",
    })

    assert resp.status_code == 202
    body = resp.json()

    run = await db.get(Run, uuid.UUID(body["run_id"]))
    assert run is not None

    workflow = await db.get(Workflow, uuid.UUID(body["workflow_id"]))
    assert workflow is not None
    assert "vllm-serve" in workflow.yaml


# ---------------------------------------------------------------------------
# GET /runs/{run_id}
# ---------------------------------------------------------------------------

async def test_get_run_returns_status(client, seeded_node_run):
    run, node_run = seeded_node_run

    resp = await client.get(f"/runs/{run.id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(run.id)
    assert body["status"] == "running"


async def test_get_run_nodes_returns_node_list(client, seeded_node_run):
    run, node_run = seeded_node_run

    resp = await client.get(f"/runs/{run.id}/nodes")

    assert resp.status_code == 200
    nodes = resp.json()
    assert len(nodes) == 1
    assert nodes[0]["node_type"] == "vllm-serve"
    assert nodes[0]["status"] == "running"


async def test_get_run_nodes_includes_outputs(client, db, seeded_node_run):
    run, node_run = seeded_node_run

    node_run.outputs = {"endpoint_url": "https://pod-abc-8000.proxy.runpod.net/v1"}
    await db.commit()

    resp = await client.get(f"/runs/{run.id}/nodes")

    outputs = resp.json()[0]["outputs"]
    assert outputs["endpoint_url"] == "https://pod-abc-8000.proxy.runpod.net/v1"


async def test_get_run_not_found_returns_404(client):
    resp = await client.get(f"/runs/{uuid.uuid4()}")

    assert resp.status_code == 404


async def test_public_lists_cap_limit_at_500(client, db):
    from api.models.db import Run, Workflow
    db.add_all(Run(user_id=uuid.uuid4()) for _ in range(51))
    db.add_all(Workflow(user_id=uuid.uuid4(), name="w", yaml="", graph_json={}) for _ in range(51))
    await db.commit()

    for path in ("/runs", "/workflows"):
        assert len((await client.get(path)).json()) == 50
        assert len((await client.get(path, params={"limit": 500})).json()) == 51  # the golden-run filter asks for 500
        for bad in (0, 501):  # a public caller cannot ask for every row
            assert (await client.get(path, params={"limit": bad})).status_code == 422
    assert (await client.get("/artifacts", params={"limit": -1})).status_code == 422  # SQLite reads -1 as no limit
