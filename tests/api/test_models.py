"""
Tests for the model registry — GET /models, GET /models/{id}, POST /models
and auto-registration via POST /internal/artifact.
"""

import uuid

import pytest


# ---------------------------------------------------------------------------
# POST /models  (manual registration)
# ---------------------------------------------------------------------------

async def test_register_model_returns_201(client):
    resp = await client.post("/models", json={
        "name":       "qwen3-4b-dolly-gguf-q4",
        "base_model": "Qwen/Qwen3-4B-Instruct",
        "format":     "gguf",
        "uri":        "r2://orchapod-artifacts/runs/abc/node/model_q4_k_m.gguf",
        "tags":       ["gguf", "qwen3"],
    })

    assert resp.status_code == 201
    body = resp.json()
    assert body["format"]     == "gguf"
    assert body["base_model"] == "Qwen/Qwen3-4B-Instruct"
    assert "gguf" in body["tags"]
    assert "id" in body


async def test_register_model_unknown_format_returns_422(client):
    resp = await client.post("/models", json={
        "name":       "test",
        "base_model": "Qwen/Qwen3-4B-Instruct",
        "format":     "tpu-magic",
        "uri":        "r2://x",
        "tags":       [],
    })

    assert resp.status_code == 422
    assert "tpu-magic" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# GET /models
# ---------------------------------------------------------------------------

async def test_list_models_returns_all(client):
    from unittest.mock import patch
    # seed two models
    await client.post("/models", json={"name": "m1", "base_model": "Qwen/Qwen3-4B-Instruct", "format": "gguf", "uri": "r2://a", "tags": ["gguf"]})
    await client.post("/models", json={"name": "m2", "base_model": "Qwen/Qwen3-4B-Instruct", "format": "awq",  "uri": "r2://b", "tags": ["awq"]})

    resp = await client.get("/models")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


async def test_list_models_filter_by_format(client):
    await client.post("/models", json={"name": "g1", "base_model": "Meta/Llama-3-8B", "format": "gguf", "uri": "r2://g1", "tags": []})
    await client.post("/models", json={"name": "a1", "base_model": "Meta/Llama-3-8B", "format": "awq",  "uri": "r2://a1", "tags": []})

    resp = await client.get("/models?format=gguf")
    assert resp.status_code == 200
    assert all(m["format"] == "gguf" for m in resp.json())


async def test_list_models_filter_by_base_model(client):
    await client.post("/models", json={"name": "q", "base_model": "Qwen/Qwen3-4B-Instruct", "format": "hf", "uri": "r2://q", "tags": []})
    await client.post("/models", json={"name": "l", "base_model": "Meta/Llama-3-8B",          "format": "hf", "uri": "r2://l", "tags": []})

    resp = await client.get("/models?base_model=Qwen/Qwen3-4B-Instruct")
    assert resp.status_code == 200
    assert all(m["base_model"] == "Qwen/Qwen3-4B-Instruct" for m in resp.json())


async def test_list_models_filter_by_tag(client):
    await client.post("/models", json={"name": "t1", "base_model": "x", "format": "hf", "uri": "r2://t1", "tags": ["production"]})
    await client.post("/models", json={"name": "t2", "base_model": "x", "format": "hf", "uri": "r2://t2", "tags": ["dev"]})

    resp = await client.get("/models?tag=production")
    assert resp.status_code == 200
    bodies = resp.json()
    assert all("production" in m["tags"] for m in bodies)
    assert not any(m["name"] == "t2" for m in bodies)


# ---------------------------------------------------------------------------
# GET /models/{id}
# ---------------------------------------------------------------------------

async def test_get_model_by_id(client):
    created = (await client.post("/models", json={
        "name": "lookup-test", "base_model": "x", "format": "hf", "uri": "r2://x", "tags": [],
    })).json()

    resp = await client.get(f"/models/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "lookup-test"


async def test_get_model_not_found_returns_404(client):
    resp = await client.get(f"/models/{uuid.uuid4()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auto-registration via /internal/artifact
# ---------------------------------------------------------------------------

async def test_model_auto_registered_on_artifact_upload(client, db, seeded_node_run):
    from sqlmodel import select
    from api.models.db import Model

    run, node_run = seeded_node_run

    resp = await client.post("/internal/artifact", json={
        "run_id":  str(run.id),
        "node_id": "node",
        "artifact": {
            "name": "gguf_file",
            "uri":  "r2://orchapod-artifacts/runs/abc/node/model_q4_k_m.gguf",
            "kind": "model",
            "metadata": {
                "format":    "gguf",
                "precision": "q4_k_m",
                "base_model": "Qwen/Qwen3-4B-Instruct",
            },
        },
    })

    assert resp.status_code == 201

    result = await db.exec(select(Model).where(Model.run_id == run.id))
    model = result.first()
    assert model is not None
    assert model.format.value == "gguf"
    assert model.base_model   == "Qwen/Qwen3-4B-Instruct"
    assert model.run_id       == run.id
    assert model.node_run_id  == node_run.id


async def test_non_model_artifact_does_not_create_model_record(client, db, seeded_node_run):
    from sqlmodel import select
    from api.models.db import Model

    run, _ = seeded_node_run

    await client.post("/internal/artifact", json={
        "run_id":  str(run.id),
        "node_id": "node",
        "artifact": {"name": "stats", "uri": "r2://x/stats.json", "kind": "metrics"},
    })

    result = await db.exec(select(Model).where(Model.run_id == run.id))
    assert result.first() is None
