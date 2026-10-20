"""
apps/api/executor/run_workflow.py

Asyncio workflow executor — the heart of the control plane.
Executes workflow DAGs topologically, node by node.

Key invariants:
  - The control plane NEVER trains. All ML work runs in GPU pods.
  - Every artifact lives in R2, addressed by runs/{run_id}/{node_id}/{name}.
  - Nodes never read from each other directly — only via R2 URIs.
  - State is persisted at every node boundary so crashes are resumable.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.models.db import Run, NodeRun, RunStatus, NodeStatus
from api.executor.dag import compile_dag, DAGNode

Broadcast = Callable[[uuid.UUID, dict], Awaitable[None]]


class NodeFailed(Exception):
    pass


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

async def run_workflow(run_id: uuid.UUID, db: AsyncSession, broadcast: Broadcast) -> None:
    """
    Execute a workflow run end-to-end.
    Called as a background task from POST /runs/{id}/start.
    """
    import logging
    _log = logging.getLogger("api.executor")
    _log.warning("run_workflow: fetching run %s", run_id)
    from api.models.db import Workflow
    run = await db.get(Run, run_id)
    _log.warning("run_workflow: fetching workflow %s", run.workflow_id)
    workflow = await db.get(Workflow, run.workflow_id)
    _log.warning("run_workflow: compiling dag")
    dag = compile_dag(workflow.yaml, run.inputs)
    _log.warning("run_workflow: dag compiled, setting status RUNNING")
    await _set_run_status(db, run, RunStatus.RUNNING)
    _log.warning("run_workflow: status set to RUNNING, starting dag loop")
    await broadcast(run_id, {"type": "run_status", "status": "running"})

    for dag_node in dag.topological_order():
        node_run = await _create_node_run(db, run, dag_node)
        await broadcast(run_id, {
            "type": "node_status",
            "node_id": dag_node.id,
            "status": "running",
        })

        try:
            outputs = await _execute_node(node_run, dag_node, run, db, broadcast)
            await _mark_node_succeeded(db, node_run, outputs)
        except NodeFailed as e:
            await _mark_node_failed(db, node_run, str(e))
            await _set_run_failed(db, run, str(e))
            await broadcast(run_id, {
                "type": "run_status",
                "status": "failed",
                "error": str(e),
            })
            return
        except asyncio.CancelledError:
            await _mark_node_failed(db, node_run, "Run was cancelled")
            await _set_run_failed(db, run, "Cancelled")
            raise

        await broadcast(run_id, {
            "type": "node_status",
            "node_id": dag_node.id,
            "status": "succeeded",
            "outputs": node_run.outputs,
        })

    await _set_run_succeeded(db, run)
    await broadcast(run_id, {"type": "run_status", "status": "succeeded"})


# ---------------------------------------------------------------------------
# Single node execution
# ---------------------------------------------------------------------------

async def _execute_node(
    node_run: NodeRun,
    dag_node: DAGNode,
    run: Run,
    db: AsyncSession,
    broadcast: Broadcast,
) -> dict:
    """
    Provision a GPU pod, run the container, stream logs, wait for exit.
    Returns the outputs dict collected from /internal/artifact webhooks.
    """
    from api.services.provider_selector import pick_provider, pick_local_docker
    from packages.workflow_schema.models import ResourceSpec, NodeType, NODE_REGISTRY

    res_dict = dag_node.resources if isinstance(dag_node.resources, dict) else {}
    resources = ResourceSpec(**res_dict) if res_dict else ResourceSpec()

    # Resolve ${{ ... }} template refs using outputs from already-completed nodes
    resolved = await _resolve_inputs(dag_node.inputs, run, db)

    # Determine runtime: CPU nodes run via LocalDockerProvider, GPU nodes via cloud
    try:
        node_runtime = NODE_REGISTRY[NodeType(dag_node.type)].get("runtime", "gpu")
    except (ValueError, KeyError):
        node_runtime = "gpu"

    try:
        if node_runtime == "cpu":
            provider, gpu_spec = await pick_local_docker(resources)
        else:
            provider, gpu_spec = await pick_provider(resources)
    except Exception as e:
        raise NodeFailed(f"No {node_runtime} provider available: {e}")

    env = _build_env(resolved, node_run)
    image = f"ghcr.io/orchapod/{dag_node.type}:latest"

    # Provision pod
    try:
        pod = await provider.provision(gpu_spec=gpu_spec, image=image, env=env)
    except Exception as e:
        raise NodeFailed(f"Provision failed: {e}")

    # Record which provider/pod we used
    node_run.started_at = datetime.utcnow()
    db.add(node_run)
    run.gpu_provider = provider.name
    run.gpu_pod_id = pod.pod_id
    db.add(run)
    await db.flush()
    await db.commit()

    # Stream logs until container exits
    async def _stream():
        async for line in provider.stream_logs(pod):
            await broadcast(node_run.run_id, {
                "type": "log",
                "node_id": node_run.node_id,
                "line": line,
            })

    stream_task = asyncio.create_task(_stream())

    try:
        exit_code = await provider.wait(pod)
    finally:
        stream_task.cancel()
        try:
            await stream_task
        except asyncio.CancelledError:
            pass

    if exit_code != 0:
        raise NodeFailed(f"Container exited with code {exit_code}")

    # Terminate pod (vllm-serve stays alive)
    if dag_node.type != "vllm-serve":
        try:
            await provider.terminate(pod)
        except Exception:
            pass  # best-effort cleanup

    # Re-read node_run to get outputs populated by /internal/artifact webhooks
    await db.refresh(node_run)
    return node_run.outputs


# ---------------------------------------------------------------------------
# Input resolution
# ---------------------------------------------------------------------------

async def _resolve_inputs(inputs: dict, run: Run, db: AsyncSession) -> dict:
    """
    Replace ${{ nodes.X.outputs.Y }} and ${{ inputs.Z }} with real values.
    """
    resolved = {}
    for key, value in inputs.items():
        if isinstance(value, str) and "${{" in value:
            resolved[key] = await _resolve_ref(value, run, db)
        else:
            resolved[key] = value
    return resolved


async def _resolve_ref(template: str, run: Run, db: AsyncSession) -> Any:
    match = re.search(r"\$\{\{\s*(.+?)\s*\}\}", template)
    if not match:
        return template
    ref = match.group(1).strip()
    parts = ref.split(".")

    if parts[0] == "inputs" and len(parts) >= 2:
        return run.inputs.get(parts[1], template)

    if parts[0] == "nodes" and len(parts) >= 4 and parts[2] == "outputs":
        node_id, artifact_name = parts[1], parts[3]
        result = await db.execute(
            select(NodeRun).where(
                NodeRun.run_id == run.id,
                NodeRun.node_id == node_id,
            )
        )
        node_run = result.scalar_one_or_none()
        if node_run and artifact_name in (node_run.outputs or {}):
            return node_run.outputs[artifact_name]

    return template  # unresolved ref — pass through as-is


def _build_env(resolved_inputs: dict, node_run: NodeRun) -> dict[str, str]:
    env = {
        "ORCHAPOD_NODE_INPUTS":      json.dumps(resolved_inputs),
        "ORCHAPOD_NODE_OUTPUTS_DIR": "/tmp/orchapod_outputs",
        "ORCHAPOD_RUN_ID":           str(node_run.run_id),
        "ORCHAPOD_NODE_ID":          node_run.node_id,
        "ORCHAPOD_R2_ENDPOINT":      os.environ.get("ORCHAPOD_R2_ENDPOINT", ""),
        "ORCHAPOD_R2_ACCESS_KEY":    os.environ.get("ORCHAPOD_R2_ACCESS_KEY", ""),
        "ORCHAPOD_R2_SECRET_KEY":    os.environ.get("ORCHAPOD_R2_SECRET_KEY", ""),
        "ORCHAPOD_R2_BUCKET":        os.environ.get("ORCHAPOD_R2_BUCKET", "orchapod-artifacts"),
        "ORCHAPOD_CONTROL_URL":      os.environ.get("ORCHAPOD_CONTROL_URL", ""),
        "NEBIUS_API_KEY":             os.environ.get("NEBIUS_API_KEY", ""),
        "OPENAI_API_KEY":            os.environ.get("OPENAI_API_KEY", ""),
        "ANTHROPIC_API_KEY":         os.environ.get("ANTHROPIC_API_KEY", ""),
        "HF_TOKEN":                  os.environ.get("HF_TOKEN", ""),
        # Cloudflare Tunnel — forwarded to vllm-serve pods (KAN-28)
        "CLOUDFLARE_TUNNEL_TOKEN":   os.environ.get("CLOUDFLARE_TUNNEL_TOKEN", ""),
    }
    # Inject resume checkpoint URI if one exists for this run+node
    resume_uri = _find_resume_checkpoint(node_run)
    if resume_uri:
        env["ORCHAPOD_RESUME_CHECKPOINT_URI"] = resume_uri
    return env


def _find_resume_checkpoint(node_run: NodeRun) -> str | None:
    """
    Check if there's a checkpoint artifact from a previous attempt of this node.
    Returns the URI of the latest checkpoint, or None.
    The node's run.py uses this via checkpoint.latest_checkpoint_uri().
    """
    # Checkpoints are stored in node_run.outputs keyed by 'checkpoint_step_NNNNNN'
    outputs = node_run.outputs or {}
    checkpoints = {k: v for k, v in outputs.items() if k.startswith("checkpoint_step_")}
    if not checkpoints:
        return None
    latest_key = sorted(checkpoints.keys())[-1]
    return checkpoints[latest_key]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def _create_node_run(db: AsyncSession, run: Run, dag_node: DAGNode) -> NodeRun:
    node_run = NodeRun(
        run_id=run.id,
        node_id=dag_node.id,
        node_type=dag_node.type,
        inputs=dag_node.inputs,
    )
    db.add(node_run)
    await db.flush()
    await db.commit()
    await db.refresh(node_run)
    return node_run


async def _set_run_status(db: AsyncSession, run: Run, status: RunStatus) -> None:
    import logging
    _log = logging.getLogger("api.executor")
    _log.warning("_set_run_status: %s -> %s", run.id, status)
    run.status = status
    if status == RunStatus.RUNNING:
        run.started_at = datetime.utcnow()
    db.add(run)
    _log.warning("_set_run_status: flushing")
    await db.flush()
    _log.warning("_set_run_status: committing")
    await db.commit()
    _log.warning("_set_run_status: done")


async def _set_run_succeeded(db: AsyncSession, run: Run) -> None:
    run.status = RunStatus.SUCCEEDED
    run.finished_at = datetime.utcnow()
    db.add(run)
    await db.flush()
    await db.commit()


async def _set_run_failed(db: AsyncSession, run: Run, error: str) -> None:
    run.status = RunStatus.FAILED
    run.finished_at = datetime.utcnow()
    db.add(run)
    await db.flush()
    await db.commit()


async def _mark_node_succeeded(db: AsyncSession, node_run: NodeRun, outputs: dict) -> None:
    node_run.status = NodeStatus.SUCCEEDED
    node_run.finished_at = datetime.utcnow()
    node_run.outputs = outputs
    db.add(node_run)
    await db.flush()
    await db.commit()


async def _mark_node_failed(db: AsyncSession, node_run: NodeRun, error: str) -> None:
    node_run.status = NodeStatus.FAILED
    node_run.finished_at = datetime.utcnow()
    node_run.error = error
    db.add(node_run)
    await db.flush()
    await db.commit()
