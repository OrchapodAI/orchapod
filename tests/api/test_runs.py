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

@pytest.fixture
def admin(monkeypatch):
    """vllm-serve rents a GPU, which only the admin starts (anonymous callers get 403: tests/api/test_budget.py)."""
    monkeypatch.setenv("ORCHAPOD_ADMIN_TOKEN", "s3cret")
    return {"X-Orchapod-Admin": "s3cret"}


async def test_deploy_valid_model_returns_202(client, no_bg_tasks, admin):
    resp = await client.post("/inference/deploy", headers=admin, json={
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


async def test_deploy_creates_workflow_and_run_in_db(client, db, no_bg_tasks, admin):
    from api.models.db import Run, Workflow

    resp = await client.post("/inference/deploy", headers=admin, json={
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


async def test_deploy_never_stores_an_hf_token(client, db, no_bg_tasks, admin):
    """The executor forwards HF_TOKEN from the API's env to every node, so a deploy needs no token; one sent anyway must
    not reach the stored workflow, its graph or the run (node schemas still declare hf_token inputs: report)."""
    import json
    from sqlmodel import select
    from api.models.db import Run, Workflow

    for mode in ("serve", "quantize-serve", "quantize-gguf"):
        r = await client.post("/inference/deploy", headers=admin, json={
            "model": "meta-llama/Llama-3.2-3B-Instruct", "mode": mode, "hf_token": "hf_secret123"})
        assert r.status_code == 202
    stored = json.dumps([[w.yaml, w.graph_json] for w in await db.scalars(select(Workflow))]
                        + [r.inputs for r in await db.scalars(select(Run))])
    assert stored.count("Llama-3.2-3B") == 6  # three workflows, each in its YAML and its graph
    assert "hf_token" not in stored and "hf_secret123" not in stored


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

    assert len((await client.get("/runs")).json()) == 50
    assert len((await client.get("/workflows", params={"limit": 50})).json()) == 50
    for path in ("/runs", "/workflows"):  # the runs page reads 500 runs and names them from the default workflow list
        assert len((await client.get(path, params={"limit": 500})).json()) == 51
        for bad in (0, 501):  # a public caller cannot ask for every row
            assert (await client.get(path, params={"limit": bad})).status_code == 422
    assert len((await client.get("/workflows")).json()) == 51
    assert (await client.get("/artifacts", params={"limit": -1})).status_code == 422  # SQLite reads -1 as no limit


async def test_runs_carry_their_workflows_name(client, db, no_bg_tasks):
    """The golden-run link finds its run by workflow name, without reading the newest 500 workflows."""
    from api.models.db import Run, Workflow
    golden = Workflow(user_id=uuid.uuid4(), name="nebius-docs-specialist-llama-8b", yaml="name: x\nnodes: []\n",
                      graph_json={})
    db.add(golden)
    await db.flush()
    run, standalone = Run(workflow_id=golden.id, user_id=golden.user_id), Run(user_id=uuid.uuid4())
    db.add_all([run, standalone])
    await db.commit()

    listed = {r["id"]: r["workflow_name"] for r in (await client.get("/runs")).json()}
    assert listed == {str(run.id): "nebius-docs-specialist-llama-8b", str(standalone.id): None}
    assert (await client.get(f"/runs/{run.id}")).json()["workflow_name"] == "nebius-docs-specialist-llama-8b"
    made = await client.post("/runs", json={"workflow_id": str(golden.id)})
    assert made.json()["workflow_name"] == "nebius-docs-specialist-llama-8b"


async def test_cost_estimate_quotes_only_the_nodes_that_rent_a_gpu(client, db, monkeypatch):
    """The canvas asks for a confirmation only when a node has a quote. A cpu or api node rents no GPU, so it has none
    (each used to get the default 1xH100's), and vllm-serve is priced on its platform input, as its endpoint is."""
    from orchapod.prices import PRICES
    from api.models.db import Run, Workflow
    from api.services import provider_selector
    asked = []

    async def quote(res):
        asked.append(res.gpu)
        return [{"provider": "nebius", "price_per_hour": 4.5, "available": True, "gpu_type": "gpu-h100-sxm"}]
    monkeypatch.setattr(provider_selector, "get_cost_estimate", quote)
    wf = Workflow(user_id=uuid.uuid4(), name="w", graph_json={}, yaml="name: w\nnodes:\n"
                  "  - {id: research, type: web-research}\n  - {id: tune, type: tf-finetune}\n"
                  "  - {id: train, type: unsloth-train}\n  - {id: serve, type: vllm-serve}\n"
                  "  - {id: serve_h100, type: vllm-serve, inputs: {platform: gpu-h100-sxm}}\n")
    db.add(wf)
    await db.flush()
    run = Run(workflow_id=wf.id, user_id=wf.user_id)
    db.add(run)
    await db.commit()

    quoted = {n["node_id"]: n["quotes"] for n in (await client.get(f"/runs/{run.id}/cost-estimate")).json()["nodes"]}
    assert set(quoted) == {"train", "serve", "serve_h100"} and asked == ["1xH100"]
    gpu = PRICES["nebius_serverless"]
    assert [(q["gpu_type"], q["price_per_hour"]) for q in quoted["serve"] + quoted["serve_h100"]] == [
        ("gpu-l40s-a", gpu["gpu-l40s-a"]), ("gpu-h100-sxm", gpu["gpu-h100-sxm"])]


# ---------------------------------------------------------------------------
# Cancel token: visitors cannot cancel each other's runs
# ---------------------------------------------------------------------------

GOOD_PLAN = {"name": "qa-data", "nodes": [
    {"id": "synth", "type": "synth-distilabel", "needs": [], "inputs": {"pipeline_template": "self-instruct", "n_samples": 100}},
    {"id": "prep", "type": "data-prep", "needs": ["synth"], "inputs": {"dataset": "${{ nodes.synth.outputs.dataset }}"}},
]}


async def test_only_the_caller_who_started_a_run_or_the_admin_cancels_it(client, db, monkeypatch):
    import hashlib
    from sqlmodel import select
    from api.executor import run_workflow as ex
    from api.models.db import CancelToken, Run, RunStatus, Workflow
    monkeypatch.setattr(ex, "launch", lambda run_id, scale: None)
    monkeypatch.setenv("ORCHAPOD_ADMIN_TOKEN", "s3cret")
    wf = Workflow(user_id=uuid.uuid4(), name="w", yaml="name: w\nnodes:\n  - {id: d, type: data-prep, inputs: {dataset: hf://x}}\n",
                  graph_json={})
    db.add(wf)
    await db.flush()
    started, by_agent, pending = (Run(workflow_id=wf.id, user_id=wf.user_id) for _ in range(3))
    db.add_all([started, by_agent, pending])
    await db.commit()

    token = (await client.post(f"/runs/{started.id}/start")).json()["cancel_token"]
    agent = (await client.post("/agent/run", json={"intent": "Q&A data", "plan": GOOD_PLAN})).json()
    kept = {r.run_id: r.sha256 for r in await db.scalars(select(CancelToken))}
    assert kept[started.id] == hashlib.sha256(token.encode()).hexdigest() and token not in str(kept)  # only its hash

    def cancel(run_id, **headers):
        return client.post(f"/runs/{run_id}/cancel", headers=headers)
    for refused in (await cancel(started.id), await cancel(started.id, **{"X-Orchapod-Cancel-Token": "guess"}),
                    await cancel(started.id, **{"X-Orchapod-Cancel-Token": agent["cancel_token"]}),  # another run's
                    await cancel(pending.id)):  # never started: no token exists
        assert refused.status_code == 403 and "cancel token" in refused.json()["detail"]
    r = await cancel(started.id, **{"X-Orchapod-Cancel-Token": token})
    assert (r.status_code, r.json()["status"]) == (200, "cancelled")
    r = await cancel(agent["run_id"], **{"X-Orchapod-Cancel-Token": agent["cancel_token"]})
    assert (r.status_code, r.json()["status"]) == (200, "cancelled")
    assert (await cancel(pending.id, **{"X-Orchapod-Admin": "s3cret"})).json()["status"] == "cancelled"  # the admin: any
    assert (await cancel(uuid.uuid4())).status_code == 404

    from api.models.db import NodeRun, NodeStatus
    db.add(NodeRun(run_id=started.id, node_id="d", node_type="data-prep", status=NodeStatus.FAILED, error="cancelled"))
    await db.commit()
    assert (await client.post(f"/runs/{started.id}/nodes/d/retry")).status_code == 202  # anyone may retry ...
    r = await cancel(started.id, **{"X-Orchapod-Cancel-Token": token})  # ... and the starter's token still cancels it
    assert (r.status_code, r.json()["status"]) == (200, "cancelled")
    run = await db.get(Run, started.id)
    await db.refresh(run)
    assert run.status == RunStatus.CANCELLED
