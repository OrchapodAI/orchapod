"""
apps/api/routes/runs.py

Run lifecycle management.

Routes:
  POST   /runs                          — create a run (workflow_id + inputs)
  POST   /runs/{id}/start               — start execution (launches asyncio task)
  POST   /runs/{id}/cancel              — cancel (terminates the pod, SIGTERM with 30 s grace)
  POST   /runs/{id}/nodes/{node_id}/retry — re-run a failed node, then continue downstream
  GET    /runs/{id}                     — get run + status
  GET    /runs/{id}/summary             — status, cost, per-node usd and errors, artifacts
  GET    /runs/{id}/nodes               — list node runs for a run
  GET    /runs/{id}/nodes/{node_id}     — get a single node run
  GET    /runs/{id}/artifacts           — list all artifacts for a run
  GET    /runs/{id}/cost-estimate       — show GPU cost before starting
  GET    /runs                          — list runs (optionally filter by workflow)
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid
from collections import defaultdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.database import get_session
from api.executor import run_workflow as executor
from api.executor.dag import compile_dag
from api.models.db import (AgentRun, Artifact, ArtifactKind, CancelToken, NodeRun, NodeStatus, Run, RunStatus, Workflow,
                           utcnow)
from api.services import budget, ratelimit
from api.services.events import event_bus
from api.services.redact import redact

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]
Scale = Annotated[float, Depends(budget.scale)]  # 1 for X-Orchapod-Admin, else ORCHAPOD_ANON_SCALE (R7)
Admin = Annotated[bool, Depends(budget.admin)]

TERMINAL = (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class RunCreate(BaseModel):
    workflow_id: uuid.UUID
    inputs: dict = {}
    user_id: uuid.UUID | None = None


class RunOut(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID | None
    workflow_name: str | None  # null once the workflow is gone; the golden-run link finds its run by it
    user_id: uuid.UUID
    status: RunStatus
    inputs: dict
    cost_usd: float | None
    started_at: datetime | None
    finished_at: datetime | None
    gpu_provider: str | None
    created_at: datetime


class StartOut(RunOut):
    cancel_token: str  # returned once: an anonymous cancel of this run needs it (X-Orchapod-Cancel-Token)


class NodeRunOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    node_id: str
    node_type: str
    status: NodeStatus
    started_at: datetime | None
    finished_at: datetime | None
    inputs: dict
    outputs: dict
    logs_uri: str | None
    error: str | None


class ArtifactOut(BaseModel):
    id: uuid.UUID
    node_run_id: uuid.UUID
    name: str
    kind: ArtifactKind
    uri: str
    size_bytes: int | None
    meta: dict
    created_at: datetime


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(ratelimit.limit("write"))])
async def create_run(body: RunCreate, db: Session):
    workflow = await db.get(Workflow, body.workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run = Run(
        workflow_id=body.workflow_id,
        user_id=body.user_id or uuid.uuid4(),
        inputs=body.inputs,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return _run_out(run, workflow.name)


@router.post("/{run_id}/start", response_model=StartOut, dependencies=[Depends(ratelimit.limit("run"))])
async def start_run(run_id: uuid.UUID, db: Session, scale: Scale):
    """409 unless pending; 503 kill switch; 402 when no budget is left (caps × the caller's scale). The reply carries
    the run's cancel token, once."""
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status == RunStatus.PENDING:
        await budget.guard(db, scale, run)
        budget.gpu_guard(await _to_run(db, run), scale)
    token, kept = cancel_token(run_id)
    if run.status != RunStatus.PENDING or not await _move(db, run, [RunStatus.PENDING], kept):
        await db.refresh(run)
        raise HTTPException(status_code=409, detail=f"Run is {run.status.value}; only pending runs can be started")
    executor.launch(run_id, scale)
    return StartOut(**_run_out(run, await _workflow_name(db, run)).model_dump(), cancel_token=token)


@router.post("/{run_id}/cancel", response_model=RunOut, dependencies=[Depends(ratelimit.limit("write"))])
async def cancel_run(run_id: uuid.UUID, db: Session, is_admin: Admin, x_orchapod_cancel_token: str = Header(default="")):
    """The admin cancels any run; anyone else needs the run's cancel token, which start or /agent/run returned."""
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    kept = None if is_admin else await db.get(CancelToken, run_id)
    if not is_admin and not (kept and secrets.compare_digest(kept.sha256, _sha256(x_orchapod_cancel_token))):
        raise HTTPException(status_code=403, detail="cancelling this run needs its cancel token (X-Orchapod-Cancel-Token, "
                                                    "returned when it started) or the admin")
    if run.status in TERMINAL:
        raise HTTPException(status_code=409, detail=f"Run already in terminal state: {run.status}")

    task = executor.running_tasks.get(run_id)
    if task:
        # The executor terminates the pod (SIGTERM, 30 s grace) and marks the node failed "cancelled".
        task.cancel()
        await asyncio.wait({task}, timeout=60)
    await db.refresh(run)
    if run.status not in TERMINAL:  # never started (or still stopping after 60 s)
        run.status = RunStatus.CANCELLED
        run.finished_at = utcnow()
        await db.commit()  # before the event: subscribers re-read the run on it
        await event_bus.publish(run_id, {"type": "run_status", "status": "cancelled"})
    return _run_out(run, await _workflow_name(db, run))


@router.post("/{run_id}/nodes/{node_id}/retry", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED,
             dependencies=[Depends(ratelimit.limit("run"))])
async def retry_node(run_id: uuid.UUID, node_id: str, db: Session, scale: Scale):
    """Re-run the run's failed node (same row, outputs kept), then continue downstream."""
    run = await db.get(Run, run_id)
    node_run = await db.scalar(select(NodeRun).where(NodeRun.run_id == run_id, NodeRun.node_id == node_id))
    if not run or not node_run:
        raise HTTPException(status_code=404, detail="Run or node not found")
    if run.status not in (RunStatus.FAILED, RunStatus.CANCELLED) or node_run.status != NodeStatus.FAILED:
        raise HTTPException(status_code=409, detail=f"Only the failed node of a failed or cancelled run "
                                                    f"can be retried (run {run.status.value}, node {node_run.status.value})")
    await budget.guard(db, scale, run)
    budget.gpu_guard(await _to_run(db, run), scale)
    if executor.busy(run_id):  # its executor, or a container it started, is still stopping
        raise HTTPException(status_code=409, detail="Run is still stopping; retry in a moment")

    reset = await db.execute(update(NodeRun).where(NodeRun.id == node_run.id, NodeRun.status == NodeStatus.FAILED)
                             .values(status=NodeStatus.PENDING, error=None).execution_options(synchronize_session=False))
    await db.execute(update(AgentRun).where(AgentRun.run_id == run_id).values(report_md=None)  # a new report at the end
                     .execution_options(synchronize_session=False))
    if reset.rowcount != 1 or not await _move(db, run, [RunStatus.FAILED, RunStatus.CANCELLED]):
        await db.rollback()
        raise HTTPException(status_code=409, detail="Run changed meanwhile; reload it")
    executor.launch(run_id, scale)
    return _run_out(run, await _workflow_name(db, run))


async def _to_run(db: AsyncSession, run: Run) -> list[str]:
    """The types of the run's nodes that have not succeeded: what a start or retry would run."""
    workflow = await db.get(Workflow, run.workflow_id) if run.workflow_id else None
    try:
        nodes = compile_dag(workflow.yaml, run.inputs).nodes.values()
    except Exception:
        return []  # a workflow that no longer compiles fails in the executor, with its error
    done = set(await db.scalars(select(NodeRun.node_id).where(NodeRun.run_id == run.id,
                                                              NodeRun.status == NodeStatus.SUCCEEDED)))
    return [n.type for n in nodes if n.id not in done]


async def _move(db: AsyncSession, run: Run, sources: list[RunStatus], *rows) -> bool:
    """Atomically move the run from one of `sources` to provisioning_gpu and commit (the executor reads it in its
    own session), together with the caller's earlier statements and `rows`; False when another request or worker
    changed it first."""
    moved = await db.execute(update(Run).where(Run.id == run.id, Run.status.in_(sources))
                             .values(status=RunStatus.PROVISIONING_GPU, finished_at=None)
                             .execution_options(synchronize_session=False))
    if moved.rowcount != 1:
        return False
    db.add_all(rows)
    await db.commit()
    await db.refresh(run)
    return True


@router.get("", response_model=list[RunOut])
async def list_runs(
    db: Session,
    workflow_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=500),  # a public caller never asks for every row
):
    stmt = (select(Run, Workflow.name).outerjoin(Workflow, Workflow.id == Run.workflow_id)
            .order_by(Run.created_at.desc()).limit(limit))
    if workflow_id:
        stmt = stmt.where(Run.workflow_id == workflow_id)
    if user_id:
        stmt = stmt.where(Run.user_id == user_id)
    return [_run_out(r, name) for r, name in (await db.execute(stmt)).all()]


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, db: Session):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_out(run, await _workflow_name(db, run))


@router.get("/{run_id}/summary")
async def run_summary(run_id: uuid.UUID, db: Session):
    """One read for the run page and the agent report: per-node usd comes from each cost_json."""
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    nodes = list(await db.scalars(select(NodeRun).where(NodeRun.run_id == run_id)))
    order = executor.node_order(await db.get(Workflow, run.workflow_id) if run.workflow_id else None, run)
    # a workflow that no longer compiles (a retired or not yet merged node type) lists its nodes as they ran
    nodes.sort(key=lambda n: (order.index(n.node_id) if n.node_id in order else len(order), n.started_at or datetime.max))
    node_ids = {n.id: n.node_id for n in nodes}
    artifacts = (await db.scalars(select(Artifact).where(
        Artifact.node_run_id.in_(node_ids)).order_by(Artifact.created_at))).all()
    usd: dict[str, float] = defaultdict(float)
    for a in artifacts:
        if a.name == "cost_json":
            usd[node_ids[a.node_run_id]] += float((a.meta or {}).get("usd", 0))
    failed = next((n for n in nodes if n.status == NodeStatus.FAILED), None)
    return {
        "run_id": run.id,
        "status": run.status,
        "cost_usd": float(run.cost_usd or 0),
        "error": failed.error if failed else None,
        "nodes": [{"node_id": n.node_id, "type": n.node_type, "status": n.status, "usd": usd[n.node_id],
                   "error": n.error, "started_at": n.started_at, "finished_at": n.finished_at} for n in nodes],
        "artifacts": [{"id": a.id, "node_id": node_ids[a.node_run_id], "name": a.name, "kind": a.kind, "uri": a.uri,
                       "download_url": f"/artifacts/{a.id}/download" if a.uri.startswith("r2://") else None,
                       "meta": redact(a.meta or {})} for a in artifacts],
    }


@router.get("/{run_id}/nodes", response_model=list[NodeRunOut])
async def list_node_runs(run_id: uuid.UUID, db: Session):
    result = await db.execute(select(NodeRun).where(NodeRun.run_id == run_id))
    return [_node_run_out(n) for n in result.scalars().all()]


@router.get("/{run_id}/nodes/{node_id}", response_model=NodeRunOut)
async def get_node_run(run_id: uuid.UUID, node_id: str, db: Session):
    result = await db.execute(
        select(NodeRun).where(NodeRun.run_id == run_id, NodeRun.node_id == node_id)
    )
    node_run = result.scalar_one_or_none()
    if not node_run:
        raise HTTPException(status_code=404, detail="Node run not found")
    return _node_run_out(node_run)


@router.get("/{run_id}/artifacts", response_model=list[ArtifactOut])
async def list_artifacts(run_id: uuid.UUID, db: Session):
    stmt = (
        select(Artifact)
        .join(NodeRun, NodeRun.id == Artifact.node_run_id)
        .where(NodeRun.run_id == run_id)
    )
    result = await db.execute(stmt)
    return [_artifact_out(a) for a in result.scalars().all()]


@router.get("/{run_id}/cost-estimate")
async def cost_estimate(run_id: uuid.UUID, db: Session):
    """Return GPU cost quotes for all nodes in this run's workflow."""
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    workflow = await db.get(Workflow, run.workflow_id)

    from api.services.provider_selector import get_cost_estimate
    from packages.workflow_schema.models import ResourceSpec

    dag = compile_dag(workflow.yaml, run.inputs)
    estimates = []
    for node in dag.nodes.values():
        res = ResourceSpec(**node.resources) if isinstance(node.resources, dict) else node.resources
        quotes = await get_cost_estimate(res)
        estimates.append({"node_id": node.id, "node_type": node.type, "quotes": quotes})
    return {"nodes": estimates}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def cancel_token(run_id: uuid.UUID) -> tuple[str, CancelToken]:
    """A new cancel token for the run, and the row that keeps only its SHA-256 (the token has 256 random bits)."""
    token = secrets.token_urlsafe(32)
    return token, CancelToken(run_id=run_id, sha256=_sha256(token))


def _sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def _workflow_name(db: AsyncSession, run: Run) -> str | None:
    return await db.scalar(select(Workflow.name).where(Workflow.id == run.workflow_id)) if run.workflow_id else None


def _run_out(r: Run, workflow_name: str | None) -> RunOut:
    return RunOut(
        id=r.id,
        workflow_id=r.workflow_id,
        workflow_name=workflow_name,
        user_id=r.user_id,
        status=r.status,
        inputs=redact(r.inputs or {}),
        cost_usd=float(r.cost_usd) if r.cost_usd is not None else None,
        started_at=r.started_at,
        finished_at=r.finished_at,
        gpu_provider=getattr(r, "gpu_provider", None),
        created_at=r.created_at,
    )


def _node_run_out(n: NodeRun) -> NodeRunOut:
    return NodeRunOut(
        id=n.id,
        run_id=n.run_id,
        node_id=n.node_id,
        node_type=n.node_type,
        status=n.status,
        started_at=n.started_at,
        finished_at=n.finished_at,
        inputs=redact(n.inputs or {}),  # resolved inputs, stored before ingest dropped secret-looking ones
        outputs=n.outputs or {},
        logs_uri=getattr(n, "logs_uri", None),
        error=n.error,
    )


def _artifact_out(a: Artifact) -> ArtifactOut:
    return ArtifactOut(
        id=a.id,
        node_run_id=a.node_run_id,
        name=a.name,
        kind=a.kind,
        uri=a.uri,
        size_bytes=a.size_bytes,
        meta=redact(a.meta or {}),
        created_at=a.created_at,
    )
