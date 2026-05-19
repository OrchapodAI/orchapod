"""
apps/api/routes/internal.py

Internal webhook endpoints called by node containers via the orchapod SDK.
These are NOT exposed to the public internet — protected by a shared secret
or network policy in production.

Routes:
  POST /internal/log           — receive a structured log line from a container
  POST /internal/artifact      — receive artifact registration after R2 upload
  POST /internal/progress      — receive training progress (step, loss) for charts
  POST /internal/ttl           — register endpoint + schedule pod termination
  POST /internal/node-complete — mark a node run succeeded/failed
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

# node_run_id (str) → running asyncio.Task for TTL termination.
# Stored so the extend endpoint can cancel + reschedule it.
_ttl_tasks: dict[str, asyncio.Task] = {}

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.database import get_session, AsyncSessionLocal
from api.models.db import (
    Artifact, ArtifactKind,
    Model, ModelFormat,
    NodeRun, NodeStatus,
    Run, RunStatus,
)
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


class RegisterTTLRequest(BaseModel):
    run_id:         str
    node_id:        str
    action:         str          # "register_ttl"
    keep_alive_min: int
    endpoint_url:   str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/log", status_code=204, dependencies=[Depends(_verify_secret)])
async def receive_log(event: LogEvent):
    """
    Receive a log line from a container and forward it to the WebSocket subscribers.
    Does NOT write to DB — logs are streamed live and persisted by the provider
    (full log is uploaded to R2 at the end of the node run).
    """
    from fastapi import Response
    await event_bus.publish(event.run_id, {
        "type": "log",
        "node_id": event.node_id,
        "ts": event.ts,
        "level": event.level,
        "message": event.message,
    })
    return Response(status_code=204)


@router.post("/artifact", status_code=201, dependencies=[Depends(_verify_secret)])
async def receive_artifact(event: ArtifactEvent, db: Session):
    """
    Called by io.write_output() in the container SDK after uploading to R2.
    Registers the artifact in the DB, auto-registers Model if kind=model,
    and notifies WebSocket subscribers.
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
    try:
        kind = ArtifactKind(art_data["kind"])
    except ValueError:
        raise HTTPException(422, f"Unknown artifact kind '{art_data['kind']}'. "
                            f"Valid: {[k.value for k in ArtifactKind]}")

    artifact = Artifact(
        node_run_id=node_run.id,
        name=art_data["name"],
        kind=kind,
        uri=art_data["uri"],
        size_bytes=art_data.get("size_bytes"),
        meta=art_data.get("metadata", {}),
    )
    db.add(artifact)

    # Merge URI into NodeRun.outputs so downstream nodes can reference it
    outputs = dict(node_run.outputs or {})
    outputs[art_data["name"]] = art_data["uri"]
    node_run.outputs = outputs
    db.add(node_run)

    await db.flush()

    # Auto-register a Model record for any model artifact
    if kind == ArtifactKind.MODEL:
        _auto_register_model(db, artifact, node_run, art_data.get("metadata", {}))

    await event_bus.publish(event.run_id, {
        "type": "artifact",
        "node_id": event.node_id,
        "name": art_data["name"],
        "uri": art_data["uri"],
        "kind": art_data["kind"],
    })
    return {"ok": True, "artifact_id": str(artifact.id)}


def _auto_register_model(
    db:       AsyncSession,
    artifact: Artifact,
    node_run: NodeRun,
    metadata: dict[str, Any],
) -> None:
    """Create a Model registry entry from a model artifact."""
    fmt_str    = metadata.get("format", "hf").lower()
    base_model = metadata.get("base_model") or (node_run.inputs or {}).get("model", "unknown")

    try:
        fmt = ModelFormat(fmt_str)
    except ValueError:
        fmt = ModelFormat.HF

    slug   = base_model.split("/")[-1].lower().replace(".", "-")
    suffix = metadata.get("precision") or (f"awq{metadata.get('bits','4')}" if fmt == ModelFormat.AWQ else "")
    name   = f"{slug}-{fmt.value}" + (f"-{suffix}" if suffix else "")

    model = Model(
        user_id=node_run.run_id,
        name=name,
        base_model=base_model,
        format=fmt,
        uri=artifact.uri,
        size_bytes=artifact.size_bytes,
        tags=[fmt.value, base_model],
        artifact_id=artifact.id,
        node_run_id=node_run.id,
        run_id=node_run.run_id,
    )
    db.add(model)


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


@router.post("/ttl", status_code=202, dependencies=[Depends(_verify_secret)])
async def register_ttl(body: RegisterTTLRequest, db: Session):
    """
    Called by vllm-serve containers once the endpoint is healthy.
    Stores the endpoint URL and schedules pod termination after keep_alive_min.
    """
    result = await db.execute(
        select(NodeRun).where(
            NodeRun.run_id  == uuid.UUID(body.run_id),
            NodeRun.node_id == body.node_id,
        )
    )
    node_run = result.scalar_one_or_none()
    if node_run is None:
        raise HTTPException(404, f"NodeRun not found: run_id={body.run_id}, node_id={body.node_id}")

    now        = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=body.keep_alive_min)

    outputs = dict(node_run.outputs or {})
    outputs["endpoint_url"] = body.endpoint_url
    outputs["expires_at"]   = expires_at.isoformat()
    node_run.outputs = outputs
    db.add(node_run)

    artifact = Artifact(
        node_run_id=node_run.id,
        name="endpoint_url",
        kind=ArtifactKind.ENDPOINT,
        uri=body.endpoint_url,
        meta={
            "keep_alive_min": body.keep_alive_min,
            "registered_at":  now.isoformat(),
            "expires_at":     expires_at.isoformat(),
        },
    )
    db.add(artifact)
    await db.flush()

    await event_bus.publish(uuid.UUID(body.run_id), {
        "type":       "artifact",
        "node_id":    body.node_id,
        "name":       "endpoint_url",
        "uri":        body.endpoint_url,
        "kind":       "endpoint",
        "expires_at": expires_at.isoformat(),
    })

    node_run_id_str = str(node_run.id)
    task = asyncio.create_task(
        _terminate_after_ttl(
            run_id=body.run_id,
            node_run_id=node_run_id_str,
            gpu_provider=getattr(node_run, "gpu_provider", None),
            gpu_pod_id=getattr(node_run, "gpu_pod_id", None),
            keep_alive_min=body.keep_alive_min,
        )
    )
    _ttl_tasks[node_run_id_str] = task

    return {"status": "ttl_registered", "keep_alive_min": body.keep_alive_min, "expires_at": expires_at.isoformat()}


async def _terminate_after_ttl(
    run_id:         str,
    node_run_id:    str,
    gpu_provider:   str | None,
    gpu_pod_id:     str | None,
    keep_alive_min: int,
) -> None:
    """Sleep, fire a T-10min warning, then terminate the pod."""
    from packages.providers.vastai import PROVIDERS
    from packages.providers.base import Pod

    warn_after  = max(0, (keep_alive_min - 10) * 60)
    final_after = 10 * 60

    # Sleep until T-10min, then broadcast warning
    if warn_after > 0:
        await asyncio.sleep(warn_after)
        try:
            await event_bus.publish(uuid.UUID(run_id), {
                "type":              "endpoint_expiry",
                "node_run_id":       node_run_id,
                "minutes_remaining": 10,
            })
        except Exception:
            pass
        await asyncio.sleep(final_after)
    else:
        await asyncio.sleep(keep_alive_min * 60)

    _ttl_tasks.pop(node_run_id, None)

    if gpu_provider and gpu_pod_id:
        provider = PROVIDERS.get(gpu_provider)
        if provider:
            try:
                await provider.terminate(Pod(provider=gpu_provider, pod_id=gpu_pod_id))
            except Exception:
                pass

    async with AsyncSessionLocal() as db:
        node_run = await db.get(NodeRun, uuid.UUID(node_run_id))
        run      = await db.get(Run, uuid.UUID(run_id))
        if node_run:
            node_run.status      = NodeStatus.SUCCEEDED
            node_run.finished_at = datetime.utcnow()
        if run:
            run.status      = RunStatus.SUCCEEDED
            run.finished_at = datetime.utcnow()
        await db.commit()


@router.post("/node-complete", dependencies=[Depends(_verify_secret)])
async def node_complete(
    run_id: uuid.UUID,
    node_id: str,
    exit_code: int,
    db: Session,
):
    """
    Called when a container exits. Marks the NodeRun succeeded or failed.
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
