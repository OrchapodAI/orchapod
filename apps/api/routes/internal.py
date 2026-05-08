"""
apps/api/routes/internal.py

Internal webhook endpoints called by node containers via the orchapod SDK.
These are NOT exposed to the public internet — protected by a shared secret
or network policy in production.

Routes:
  POST /internal/log       — receive a structured log line from a container
  POST /internal/artifact  — receive artifact registration after R2 upload
  POST /internal/progress  — receive training progress (step, loss) for charts
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from typing import Annotated

from api.database import get_session
from api.models.db import NodeRun, NodeStatus, Artifact, ArtifactKind
from api.services.events import event_bus

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

_INTERNAL_SECRET = os.environ.get("ORCHAPOD_INTERNAL_SECRET", "")


def _verify_secret(x_orchapod_secret: str | None = Header(default=None)) -> None:
    if _INTERNAL_SECRET and x_orchapod_secret != _INTERNAL_SECRET:
        raise HTTPException(status_code=403, detail="Invalid internal secret")


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class LogEvent(BaseModel):
    run_id: uuid.UUID
    node_id: str
    ts: str
    level: str         # INFO | WARN | ERROR | PROGRESS
    message: str


class ArtifactEvent(BaseModel):
    run_id: uuid.UUID
    node_id: str
    artifact: dict     # {name, uri, kind, metadata}


class ProgressEvent(BaseModel):
    run_id: uuid.UUID
    node_id: str
    step: int
    total: int | None = None
    loss: float | None = None
    extra: dict = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/log", dependencies=[Depends(_verify_secret)])
async def receive_log(event: LogEvent):
    """
    Receive a log line from a container and forward it to the WebSocket subscribers.
    Does NOT write to DB — logs are streamed live and persisted by the provider
    (full log is uploaded to R2 at the end of the node run).
    """
    await event_bus.publish(event.run_id, {
        "type": "log",
        "node_id": event.node_id,
        "ts": event.ts,
        "level": event.level,
        "message": event.message,
    })
    return {"ok": True}


@router.post("/artifact", dependencies=[Depends(_verify_secret)])
async def receive_artifact(event: ArtifactEvent, db: Session):
    """
    Called by io.write_output() in the container SDK after uploading to R2.
    Registers the artifact in the DB and notifies WebSocket subscribers.
    """
    result = await db.execute(
        select(NodeRun).where(
            NodeRun.run_id == event.run_id,
            NodeRun.node_id == event.node_id,
        )
    )
    node_run = result.scalar_one_or_none()
    if not node_run:
        raise HTTPException(status_code=404, detail="NodeRun not found")

    art_data = event.artifact
    artifact = Artifact(
        node_run_id=node_run.id,
        name=art_data["name"],
        kind=ArtifactKind(art_data["kind"]),
        uri=art_data["uri"],
        size_bytes=art_data.get("size_bytes"),
        metadata=art_data.get("metadata", {}),
    )
    db.add(artifact)

    # Merge URI into NodeRun.outputs so downstream nodes can reference it
    outputs = dict(node_run.outputs or {})
    outputs[art_data["name"]] = art_data["uri"]
    node_run.outputs = outputs
    db.add(node_run)

    await db.flush()

    await event_bus.publish(event.run_id, {
        "type": "artifact",
        "node_id": event.node_id,
        "name": art_data["name"],
        "uri": art_data["uri"],
        "kind": art_data["kind"],
    })
    return {"ok": True}


@router.post("/progress", dependencies=[Depends(_verify_secret)])
async def receive_progress(event: ProgressEvent):
    """
    Receive training progress (step/loss) and broadcast to WebSocket subscribers.
    Used by the run viewer to render live loss charts.
    """
    await event_bus.publish(event.run_id, {
        "type": "progress",
        "node_id": event.node_id,
        "step": event.step,
        "total": event.total,
        "loss": event.loss,
        **event.extra,
    })
    return {"ok": True}


@router.post("/node-complete", dependencies=[Depends(_verify_secret)])
async def node_complete(
    run_id: uuid.UUID,
    node_id: str,
    exit_code: int,
    db: Session,
):
    """
    Called when a container exits. Marks the NodeRun succeeded or failed.
    In practice the executor's provider.wait() drives this, but containers
    can also push directly for faster feedback.
    """
    result = await db.execute(
        select(NodeRun).where(
            NodeRun.run_id == run_id,
            NodeRun.node_id == node_id,
        )
    )
    node_run = result.scalar_one_or_none()
    if not node_run:
        raise HTTPException(status_code=404, detail="NodeRun not found")

    node_run.status = NodeStatus.SUCCEEDED if exit_code == 0 else NodeStatus.FAILED
    node_run.finished_at = datetime.utcnow()
    if exit_code != 0:
        node_run.error = f"Container exited with code {exit_code}"
    db.add(node_run)
    await db.flush()

    await event_bus.publish(run_id, {
        "type": "node_status",
        "node_id": node_id,
        "status": node_run.status.value,
    })
    return {"ok": True}
