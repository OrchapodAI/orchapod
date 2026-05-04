"""
apps/api/executor/run_workflow.py

Asyncio workflow executor — the heart of the control plane.
Runs workflow DAGs topologically, node by node.
MVP: sequential execution (no same-level parallelism — keeps GPU costs predictable).
V1: parallelize nodes that have no interdependency.

Key invariants (from architecture doc):
  - The control plane NEVER trains. All ML work runs in GPU pods.
  - Every artifact lives in R2, addressed by runs/{run_id}/{node_id}/{name}.
  - Nodes never read from each other directly — only via R2 URIs.
  - State is persisted at every node boundary so crashes are resumable.
"""

from __future__ import annotations
import asyncio
import json
import re
import uuid
from datetime import datetime
from typing import Any

from ..models.db import Run, NodeRun, RunStatus, NodeStatus
from .dag import compile_dag, DAGNode


class NodeFailed(Exception):
    pass


# ---------------------------------------------------------------------------
# Top-level entry point (called from FastAPI route POST /runs/{id}/start)
# ---------------------------------------------------------------------------

async def run_workflow(run_id: uuid.UUID, db, broadcast) -> None:
    """
    Execute a workflow run.
    db       — async database session
    broadcast — async fn(run_id, event) for WebSocket state pushes
    """
    run = await db.get(Run, run_id)
    workflow = await db.get_workflow(run.workflow_id)

    dag = compile_dag(workflow.yaml, run.inputs)

    await _update_run_status(db, run, RunStatus.RUNNING)
    await broadcast(run_id, {"type": "run_status", "status": "running"})

    for dag_node in dag.topological_order():
        node_run = await _create_node_run(db, run, dag_node)
        await broadcast(run_id, {"type": "node_status", "node_id": dag_node.id, "status": "running"})

        try:
            await execute_node(node_run, db, broadcast)
        except NodeFailed as e:
            await _mark_node_failed(db, node_run, str(e))
            await _mark_run_failed(db, run, str(e))
            await broadcast(run_id, {"type": "run_status", "status": "failed", "error": str(e)})
            return

        await broadcast(run_id, {"type": "node_status", "node_id": dag_node.id, "status": "succeeded"})

    await _mark_run_succeeded(db, run)
    await broadcast(run_id, {"type": "run_status", "status": "succeeded"})


# ---------------------------------------------------------------------------
# Single node execution
# ---------------------------------------------------------------------------

async def execute_node(node_run: NodeRun, db, broadcast) -> None:
    from packages.providers.vastai import pick_provider, PROVIDERS
    from packages.providers.base import GPUSpec

    node_def = node_run._node_def  # attached by _create_node_run

    # 1. Resolve inputs — replace ${{ nodes.X.outputs.Y }} with real R2 URIs
    resolved = _resolve_inputs(node_def.inputs, node_run.run_id, db)

    # 2. Pick cheapest available provider
    provider = await pick_provider(node_def.resources)
    gpu_spec = GPUSpec(gpu_type="H100")

    # 3. Build container env
    env = _build_env(resolved, node_run)

    # 4. Provision pod + start container
    image = f"ghcr.io/orchapod/{node_def.type}:latest"
    pod = await provider.provision(gpu_spec=gpu_spec, image=image, env=env)
    await db.update_node_run(node_run.id, {"gpu_pod_id": pod.pod_id, "started_at": datetime.utcnow()})

    # 5. Stream logs → control plane webhook → SSE → frontend
    async def stream():
        async for line in provider.stream_logs(pod):
            await broadcast(node_run.run_id, {
                "type": "log",
                "node_id": node_run.node_id,
                "line": line,
            })
    stream_task = asyncio.create_task(stream())

    # 6. Wait for container exit
    exit_code = await provider.wait(pod)
    stream_task.cancel()

    if exit_code != 0:
        raise NodeFailed(f"Container exited with code {exit_code}")

    # 7. Terminate pod (except vllm-serve which stays alive)
    if node_def.type != "vllm-serve":
        await provider.terminate(pod)

    await db.update_node_run(node_run.id, {"status": NodeStatus.SUCCEEDED, "finished_at": datetime.utcnow()})


# ---------------------------------------------------------------------------
# Input resolution — replace ${{ ... }} template refs with actual R2 URIs
# ---------------------------------------------------------------------------

def _resolve_inputs(inputs: dict, run_id: uuid.UUID, db) -> dict:
    """
    Walk the inputs dict and replace ${{ nodes.X.outputs.Y }} and ${{ inputs.Z }}
    with real values from the database.
    """
    resolved = {}
    for key, value in inputs.items():
        if isinstance(value, str) and "${{" in value:
            resolved[key] = _resolve_ref(value, run_id, db)
        else:
            resolved[key] = value
    return resolved


def _resolve_ref(template: str, run_id: uuid.UUID, db) -> Any:
    match = re.search(r"\$\{\{\s*(.+?)\s*\}\}", template)
    if not match:
        return template
    ref = match.group(1).strip()
    # e.g. "nodes.prep.outputs.train_jsonl" or "inputs.dataset_uri"
    parts = ref.split(".")
    if parts[0] == "inputs":
        # TODO: look up from Run.inputs
        return f"__unresolved_input_{parts[1]}__"
    elif parts[0] == "nodes" and parts[2] == "outputs":
        # TODO: look up NodeRun outputs from db
        node_id, artifact = parts[1], parts[3]
        return f"__unresolved_{node_id}_{artifact}__"
    return template


def _build_env(resolved_inputs: dict, node_run: NodeRun) -> dict[str, str]:
    import os
    return {
        "ORCHAPOD_NODE_INPUTS":      json.dumps(resolved_inputs),
        "ORCHAPOD_NODE_OUTPUTS_DIR": "/tmp/orchapod_outputs",
        "ORCHAPOD_RUN_ID":           str(node_run.run_id),
        "ORCHAPOD_NODE_ID":          node_run.node_id,
        "ORCHAPOD_R2_ENDPOINT":      os.environ["ORCHAPOD_R2_ENDPOINT"],
        "ORCHAPOD_R2_ACCESS_KEY":    os.environ["ORCHAPOD_R2_ACCESS_KEY"],
        "ORCHAPOD_R2_SECRET_KEY":    os.environ["ORCHAPOD_R2_SECRET_KEY"],
        "ORCHAPOD_R2_BUCKET":        os.environ.get("ORCHAPOD_R2_BUCKET", "orchapod-artifacts"),
        "ORCHAPOD_CONTROL_URL":      os.environ["ORCHAPOD_CONTROL_URL"],
        # Pass through any API keys the node needs
        "ANTHROPIC_API_KEY":         os.environ.get("ANTHROPIC_API_KEY", ""),
        "HF_TOKEN":                  os.environ.get("HF_TOKEN", ""),
    }


# ---------------------------------------------------------------------------
# DB helpers (stubs — implement against real SQLModel session)
# ---------------------------------------------------------------------------

async def _create_node_run(db, run: Run, dag_node: DAGNode) -> NodeRun:
    node_run = NodeRun(
        run_id=run.id,
        node_id=dag_node.id,
        node_type=dag_node.type,
        inputs=dag_node.inputs,
    )
    node_run._node_def = dag_node   # attach for execute_node
    await db.add(node_run)
    return node_run


async def _update_run_status(db, run: Run, status: RunStatus) -> None:
    run.status = status
    if status == RunStatus.RUNNING:
        run.started_at = datetime.utcnow()
    await db.commit()


async def _mark_run_failed(db, run: Run, error: str) -> None:
    run.status = RunStatus.FAILED
    run.finished_at = datetime.utcnow()
    await db.commit()


async def _mark_run_succeeded(db, run: Run) -> None:
    run.status = RunStatus.SUCCEEDED
    run.finished_at = datetime.utcnow()
    await db.commit()


async def _mark_node_failed(db, node_run: NodeRun, error: str) -> None:
    node_run.status = NodeStatus.FAILED
    node_run.error = error
    node_run.finished_at = datetime.utcnow()
    await db.commit()
