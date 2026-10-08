"""
apps/api/routes/runs.py

Run lifecycle management.

Routes:
  POST   /runs                          — create a run (workflow_id + inputs)
  POST   /runs/{id}/start               — start execution (launches asyncio task)
  POST   /runs/{id}/cancel              — request cancellation
  GET    /runs/{id}                     — get run + status
  GET    /runs/{id}/nodes               — list node runs for a run
  GET    /runs/{id}/nodes/{node_id}     — get a single node run
  GET    /runs/{id}/artifacts           — list all artifacts for a run
  GET    /runs/{id}/cost-estimate       — show GPU cost before starting
  GET    /runs                          — list runs (optionally filter by workflow)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.database import get_session
from api.models.db import Run, NodeRun, RunStatus, NodeStatus, Workflow, Artifact, ArtifactKind
from api.services.events import event_bus

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

# Track in-flight asyncio tasks so we can cancel them
_running_tasks: dict[uuid.UUID, asyncio.Task] = {}


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
    user_id: uuid.UUID
    status: RunStatus
    inputs: dict
    cost_usd: float | None
    started_at: datetime | None
    finished_at: datetime | None
    gpu_provider: str | None
    created_at: datetime


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

@router.post("", response_model=RunOut, status_code=status.HTTP_201_CREATED)
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
    return _run_out(run)


@router.post("/{run_id}/start", response_model=RunOut)
async def start_run(run_id: uuid.UUID, background_tasks: BackgroundTasks, db: Session):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status not in (RunStatus.PENDING,):
        raise HTTPException(
            status_code=409,
            detail=f"Run is already {run.status} — only pending runs can be started",
        )

    workflow = await db.get(Workflow, run.workflow_id)

    run.status = RunStatus.PROVISIONING_GPU
    db.add(run)
    await db.flush()
    await db.commit()  # commit before background task runs to release row lock
    await db.refresh(run)

    background_tasks.add_task(_launch_run, run_id, workflow.yaml, run.inputs)
    return _run_out(run)


@router.post("/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: uuid.UUID, db: Session):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED):
        raise HTTPException(status_code=409, detail=f"Run already in terminal state: {run.status}")

    task = _running_tasks.get(run_id)
    if task and not task.done():
        task.cancel()

    run.status = RunStatus.CANCELLED
    run.finished_at = datetime.utcnow()
    db.add(run)
    await db.flush()

    await event_bus.publish(run_id, {"type": "run_status", "status": "cancelled"})
    await db.refresh(run)
    return _run_out(run)


@router.get("", response_model=list[RunOut])
async def list_runs(
    db: Session,
    workflow_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    limit: int = 50,
):
    stmt = select(Run).order_by(Run.created_at.desc()).limit(limit)
    if workflow_id:
        stmt = stmt.where(Run.workflow_id == workflow_id)
    if user_id:
        stmt = stmt.where(Run.user_id == user_id)
    result = await db.execute(stmt)
    return [_run_out(r) for r in result.scalars().all()]


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, db: Session):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_out(run)


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

    from api.executor.dag import compile_dag
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
# Background task: execute the run
# ---------------------------------------------------------------------------

async def _launch_run(run_id: uuid.UUID, workflow_yaml: str, run_inputs: dict) -> None:
    """
    Launched as a BackgroundTask from start_run.
    Opens its own DB session (can't share the request session across task boundaries).
    """
    import logging
    log = logging.getLogger("api.runs")
    log.warning("_launch_run STARTING for run_id=%s", run_id)
    from api.database import AsyncSessionLocal
    log.warning("_launch_run: db imported")
    from api.executor.run_workflow import run_workflow
    log.warning("_launch_run: run_workflow imported")

    async with AsyncSessionLocal() as db:
        log.warning("_launch_run: db session opened")
        await asyncio.sleep(0)  # yield so request session can commit first
        task = asyncio.current_task()
        if task:
            _running_tasks[run_id] = task

        try:
            await run_workflow(run_id, db, event_bus.publish)
        except asyncio.CancelledError:
            pass  # cancellation is handled in cancel_run
        except Exception as exc:
            import traceback, logging
            logging.getLogger("api.runs").error("_launch_run crashed: %s\n%s", exc, traceback.format_exc())
        finally:
            _running_tasks.pop(run_id, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_out(r: Run) -> RunOut:
    return RunOut(
        id=r.id,
        workflow_id=r.workflow_id,
        user_id=r.user_id,
        status=r.status,
        inputs=r.inputs or {},
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
        inputs=n.inputs or {},
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
        meta=a.meta or {},
        created_at=a.created_at,
    )
