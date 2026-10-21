"""
apps/api/executor/run_workflow.py

Asyncio workflow executor — the heart of the control plane (docs/contracts.md "Run state machine").
Executes workflow DAGs topologically, node by node.

Key invariants:
  - The control plane NEVER trains. All ML work runs in node containers.
  - Every artifact lives in object storage, addressed by runs/{run_id}/{node_id}/{name}.
  - Nodes never read from each other directly — only via r2:// URIs.
  - Every NodeRun row exists (pending) from the start; a stopped run has exactly one failed node.
  - State is persisted at every node boundary, so retry resumes from the failed node.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.executor.dag import DAGNode, compile_dag
from api.models.db import NodeRun, NodeStatus, Run, RunStatus, Workflow, utcnow
from api.services import budget

Broadcast = Callable[[uuid.UUID, dict], Awaitable[None]]

log = logging.getLogger("api.executor")

# run_id → the task executing it. One API worker (see ORCHAPOD_INTERNAL_SECRET).
running_tasks: dict[uuid.UUID, asyncio.Task] = {}
# run_id → its provisions and pod teardowns still in flight after a cancel, referenced until done.
_inflight: dict[uuid.UUID, set[asyncio.Future]] = {}

# SDK-formatted stdout lines already reached the UI through /internal/log or /internal/progress.
_SDK_LINE = re.compile(r"\[[^\]]+\] \[(INFO|WARN|ERROR|PROGRESS)\] ")
_REF = re.compile(r"\$\{\{\s*(?:inputs\.(\w+)|nodes\.([^.\s}]+)\.outputs\.(\w+))\s*\}\}")

# contracts "Config": exactly these reach containers, with their defaults (blank = default).
_FORWARD = {
    "NEBIUS_API_KEY": "", "NEBIUS_BASE_URL": "https://api.tokenfactory.nebius.com/v1",
    "TAVILY_API_KEY": "", "HF_TOKEN": "",
    "NEBIUS_PROJECT_ID": "", "NEBIUS_IAM_TOKEN": "", "ORCHAPOD_ENDPOINT_TOKEN": "",
    "ORCHAPOD_R2_ENDPOINT": "http://localhost:9000", "ORCHAPOD_R2_REGION": "auto",
    "ORCHAPOD_R2_ACCESS_KEY": "orchapod", "ORCHAPOD_R2_SECRET_KEY": "orchapod_dev",
    "ORCHAPOD_R2_BUCKET": "orchapod-artifacts",
    "ORCHAPOD_CONTROL_URL": "http://localhost:8001", "STUB": "",
}


class NodeFailed(Exception):
    pass


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def launch(run_id: uuid.UUID, scale: float) -> asyncio.Task:
    """The one way to start a run (start, retry, /agent/run, /inference/deploy): cancel finds its task, and a
    concurrent start or retry joins the running executor instead of starting a second one. `scale` is the
    caller's budget scale (R7), required so a forgotten caller fails loudly; the executor lives only in this process,
    so it is never persisted."""
    if (task := running_tasks.get(run_id)) and not task.done():
        return task
    task = asyncio.create_task(_run_in_own_session(run_id, scale))
    running_tasks[run_id] = task
    task.add_done_callback(lambda t: running_tasks.pop(run_id) if running_tasks.get(run_id) is t else None)
    return task


def busy(run_id: uuid.UUID) -> bool:
    """The run's executor, or a provision or pod teardown it left behind, is still in flight."""
    return bool((task := running_tasks.get(run_id)) and not task.done() or _inflight.get(run_id))


def _track(run_id: uuid.UUID, future: asyncio.Future) -> asyncio.Future:
    _inflight.setdefault(run_id, set()).add(future)

    def done(f):
        pending = _inflight.get(run_id, set())
        pending.discard(f)
        if not pending:
            _inflight.pop(run_id, None)

    future.add_done_callback(done)
    return future


async def _run_in_own_session(run_id: uuid.UUID, scale: float) -> None:
    from api import database
    from api.services.events import event_bus

    async with database.AsyncSessionLocal() as db:
        try:
            await run_workflow(run_id, db, event_bus.publish, scale)
        except Exception:
            log.exception("run %s crashed", run_id)


async def run_workflow(run_id: uuid.UUID, db: AsyncSession, broadcast: Broadcast, scale: float) -> None:
    """Execute (or, after a retry, resume) a run: succeeded nodes are skipped. Every node boundary checks
    the kill switch and the budget (caps × scale)."""
    run = await db.get(Run, run_id)
    order, rows = [], {}
    try:
        workflow = await db.get(Workflow, run.workflow_id)
        order = compile_dag(workflow.yaml, run.inputs).topological_order()
        rows = {n.node_id: n for n in await db.scalars(select(NodeRun).where(NodeRun.run_id == run_id))}
        for node in order:
            if node.id not in rows:
                rows[node.id] = NodeRun(run_id=run_id, node_id=node.id, node_type=node.type, inputs=node.inputs)
                db.add(rows[node.id])
        run.status, run.finished_at = RunStatus.RUNNING, None
        run.started_at = run.started_at or utcnow()
        await db.commit()
        await broadcast(run_id, {"type": "run_status", "status": "running"})

        for node in order:
            node_run = rows[node.id]
            if node_run.status == NodeStatus.SUCCEEDED:
                continue
            if budget.kill_switch():
                raise NodeFailed("kill switch")
            max_cost, which, cap = await budget.reserve(db, run, scale)  # granted to this node until it ends
            if max_cost <= 0:
                raise NodeFailed(f"budget: {which} cap ${cap:g} reached")
            try:
                node_run.status, node_run.error = NodeStatus.RUNNING, None
                node_run.started_at, node_run.finished_at = utcnow(), None
                await db.commit()
                await broadcast(run_id, {"type": "node_status", "node_id": node.id, "status": "running"})
                outputs = await _execute_node(node_run, node, run, rows, db, broadcast, max_cost)
            finally:
                budget.release(run_id)
            node_run.status, node_run.finished_at, node_run.error = NodeStatus.SUCCEEDED, utcnow(), None
            await db.commit()
            await broadcast(run_id, {"type": "node_status", "node_id": node.id, "status": "succeeded", "outputs": outputs})
    except (Exception, asyncio.CancelledError) as e:
        cancelled = isinstance(e, asyncio.CancelledError)
        first = next((rows[n.id] for n in order if n.id in rows and rows[n.id].status != NodeStatus.SUCCEEDED), None)
        await _stop(db, run, first, RunStatus.CANCELLED if cancelled else RunStatus.FAILED,
                    "cancelled" if cancelled else str(e) if isinstance(e, NodeFailed) else f"internal: {e}", broadcast)
        if cancelled:
            raise
        return

    run.status, run.finished_at = RunStatus.SUCCEEDED, utcnow()
    await db.commit()
    await broadcast(run_id, {"type": "run_status", "status": "succeeded"})


async def _stop(db: AsyncSession, run: Run, node_run: NodeRun | None, status: RunStatus, error: str,
                broadcast: Broadcast) -> None:
    """The first unfinished node is the run's one failed node; its error is the run's error."""
    run.status, run.finished_at = status, utcnow()
    events = [{"type": "run_status", "status": status.value, "error": error}]
    if node_run:
        node_run.status, node_run.error, node_run.finished_at = NodeStatus.FAILED, error, run.finished_at
        events.insert(0, {"type": "node_status", "node_id": node_run.node_id, "status": "failed", "error": error})
    await db.commit()
    for event in events:
        await broadcast(run.id, event)


# ---------------------------------------------------------------------------
# Single node execution
# ---------------------------------------------------------------------------

async def _execute_node(
    node_run: NodeRun,
    dag_node: DAGNode,
    run: Run,
    rows: dict[str, NodeRun],
    db: AsyncSession,
    broadcast: Broadcast,
    max_cost: float,
) -> dict:
    """
    Provision the node's container, stream its stdout, wait for exit (or the timeout), terminate.
    Returns the outputs collected from /internal/artifact webhooks. max_cost = the budget left, which
    the node gets as ORCHAPOD_MAX_COST_USD.
    """
    from api.services.provider_selector import pick_local_docker, pick_provider
    from packages.workflow_schema.models import NODE_REGISTRY, NodeType, ResourceSpec

    timeout = float(os.environ.get("ORCHAPOD_NODE_TIMEOUT_S") or 5400)  # backstop above node-level timeouts
    node_run.inputs = _resolve_inputs(dag_node.inputs, run, rows)  # resolved inputs = lineage

    # cpu and api nodes run on LocalDocker; gpu nodes on a GPU provider
    runtime = NODE_REGISTRY.get(NodeType(dag_node.type), {}).get("runtime", "gpu")
    resources = ResourceSpec(**dag_node.resources) if isinstance(dag_node.resources, dict) and dag_node.resources else ResourceSpec()
    try:
        provider, gpu_spec = await (pick_local_docker if runtime in ("cpu", "api") else pick_provider)(resources)
    except Exception as e:
        raise NodeFailed(f"no {runtime} provider: {e}")

    env = _build_env(node_run, max_cost)
    image = f"{os.environ.get('ORCHAPOD_IMAGE_PREFIX') or 'ghcr.io/bangadpurva'}/{dag_node.type}:latest"
    prov = asyncio.ensure_future(provider.provision(gpu_spec=gpu_spec, image=image, env=env))
    try:
        pod = await asyncio.shield(prov)  # a cancel mid-provision (image pull, jobs.create) leaves it running
    except asyncio.CancelledError:
        # terminate the pod once it exists, even if this task is cancelled again; retry waits for both
        _track(run.id, asyncio.ensure_future(_terminate_when_up(provider, prov)))
        raise
    except Exception as e:
        raise NodeFailed(f"provision failed: {e}")

    stream = asyncio.create_task(_stream_stdout(provider, pod, node_run, broadcast))
    try:
        node_run.gpu_provider = run.gpu_provider = provider.name
        node_run.gpu_pod_id = run.gpu_pod_id = pod.pod_id
        await db.commit()
        exit_code = await asyncio.wait_for(provider.wait(pod), timeout)
    except TimeoutError:
        raise NodeFailed(f"timeout after {timeout:g} s")
    finally:
        await _terminate(provider, pod, run.id)  # cancel/timeout: SIGTERM, 30 s grace, kill; after exit: cleanup
        await asyncio.wait({stream}, timeout=5)  # drain the tail of stdout
        stream.cancel()

    await db.refresh(node_run)  # outputs and the last ERROR line arrive through /internal webhooks
    if exit_code != 0:
        raise NodeFailed(f"exit {exit_code}: {node_run.error}" if node_run.error else f"exit {exit_code}")
    return node_run.outputs or {}


def _terminate(provider, pod, run_id: uuid.UUID) -> asyncio.Future:
    """Teardown runs as its own task, tracked under its run, and is awaited through shield, so a second
    cancel cannot interrupt the SIGTERM grace; it never raises."""
    return asyncio.shield(_track(run_id, asyncio.ensure_future(_terminate_now(provider, pod))))


async def _terminate_when_up(provider, provision: asyncio.Future) -> None:
    try:
        pod = await provision
    except Exception:
        return  # it never came up
    await _terminate_now(provider, pod)


async def _terminate_now(provider, pod) -> None:
    try:
        await provider.terminate(pod)
    except Exception as e:
        log.warning("terminate %s failed: %s", pod.pod_id, e)


async def _stream_stdout(provider, pod, node_run: NodeRun, broadcast: Broadcast) -> None:
    async for line in provider.stream_logs(pod):
        if not _SDK_LINE.match(line):
            await broadcast(node_run.run_id, {"type": "log", "node_id": node_run.node_id, "level": "STDOUT",
                                              "ts": datetime.now(timezone.utc).isoformat(), "message": line})


# ---------------------------------------------------------------------------
# Input resolution and container env
# ---------------------------------------------------------------------------

def _resolve_inputs(inputs: dict, run: Run, rows: dict[str, NodeRun]) -> dict:
    """A top-level input is a literal or exactly one ${{ inputs.X }} / ${{ nodes.<id>.outputs.<name> }} ref."""
    resolved = {}
    for key, value in inputs.items():
        if isinstance(value, str) and "${{" in value:
            m = _REF.fullmatch(value.strip())
            if m and m[1]:
                found = (run.inputs or {}).get(m[1])
            elif m and m[2] in rows:
                found = (rows[m[2]].outputs or {}).get(m[3])
            else:
                found = None
            if found is None:
                raise NodeFailed(f"unresolved ref {value}")
            value = found
        resolved[key] = value
    return resolved


def _build_env(node_run: NodeRun, max_cost_usd: float) -> dict[str, str]:
    from api.routes.internal import INTERNAL_SECRET

    env = {k: os.environ.get(k) or default for k, default in _FORWARD.items()}
    env.update({
        "ORCHAPOD_INTERNAL_SECRET":  INTERNAL_SECRET,
        "ORCHAPOD_MAX_COST_USD":     f"{max_cost_usd:.4f}",
        "ORCHAPOD_NODE_INPUTS":      json.dumps(node_run.inputs),
        "ORCHAPOD_NODE_OUTPUTS_DIR": "/tmp/orchapod_outputs",
        "ORCHAPOD_RUN_ID":           str(node_run.run_id),
        "ORCHAPOD_NODE_ID":          node_run.node_id,
    })
    # Retry reuses the row and keeps its outputs, so the newest checkpoint resumes training.
    checkpoints = sorted(k for k in (node_run.outputs or {}) if k.startswith("checkpoint_step_"))
    if checkpoints:
        env["ORCHAPOD_RESUME_CHECKPOINT_URI"] = node_run.outputs[checkpoints[-1]]
    return env


def node_order(workflow: Workflow | None, run: Run) -> list[str]:
    """Topological node ids, or [] when the workflow is gone or no longer compiles."""
    try:
        return [n.id for n in compile_dag(workflow.yaml, run.inputs).topological_order()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Startup sweep
# ---------------------------------------------------------------------------

async def sweep(db: AsyncSession) -> None:
    """At API start: runs left mid-flight fail; a running node's pod is terminated so the node
    cancels its remote job, and that node (or else the first unfinished one) fails "control plane restarted"."""
    from api.services.provider_selector import get_providers, pick_local_docker
    from packages.providers.base import Pod

    orphans = (await db.scalars(select(Run).where(Run.status.in_([RunStatus.PROVISIONING_GPU, RunStatus.RUNNING])))).all()
    pods = []
    now = utcnow()
    for run in orphans:
        rows = {n.node_id: n for n in await db.scalars(select(NodeRun).where(NodeRun.run_id == run.id))}
        order = node_order(await db.get(Workflow, run.workflow_id), run) or list(rows)
        node_run = next((rows[i] for i in order if i in rows and rows[i].status != NodeStatus.SUCCEEDED), None)
        if node_run:
            if node_run.status == NodeStatus.RUNNING and node_run.gpu_pod_id:
                provider = (await pick_local_docker(None))[0] if node_run.gpu_provider == "local-docker" \
                    else get_providers().get(node_run.gpu_provider)
                if provider:
                    pods.append((run.id, provider, Pod(provider=node_run.gpu_provider, pod_id=node_run.gpu_pod_id)))
            node_run.status, node_run.error, node_run.finished_at = NodeStatus.FAILED, "control plane restarted", now
        run.status, run.finished_at = RunStatus.FAILED, now
    await db.commit()
    for run_id, provider, pod in pods:  # in the background: the API must be serving when the nodes post their last cost_json
        _terminate(provider, pod, run_id)
