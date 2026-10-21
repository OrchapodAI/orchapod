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

The node's exit code decides its status (executor); every call carries X-Orchapod-Secret.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.database import get_session, AsyncSessionLocal
from api.models.db import (
    utcnow,
    Artifact, ArtifactKind,
    Model, ModelFormat,
    NodeRun, NodeStatus,
    Run, RunStatus,
)
from api.services.events import event_bus

# node_run_id (str) → running asyncio.Task for TTL termination.
# Stored so the extend endpoint can cancel + reschedule it.
_ttl_tasks: dict[str, asyncio.Task] = {}

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]

# R2: /internal/* is never open. Unset (or blank) → a random secret for this process, which the
# executor passes to containers; set it explicitly when running more than one API worker.
INTERNAL_SECRET = os.environ.get("ORCHAPOD_INTERNAL_SECRET") or secrets.token_urlsafe(32)


def _verify_secret(x_orchapod_secret: str = Header(default="")) -> None:
    if not secrets.compare_digest(x_orchapod_secret.encode(), INTERNAL_SECRET.encode()):
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
async def receive_log(event: LogEvent, db: Session):
    """
    Receive a log line from a container and forward it to the WebSocket subscribers.
    Only the last ERROR line is stored (NodeRun.error): a failed node's error is "exit <code>: <that line>".
    """
    from fastapi import Response
    if event.level == "ERROR":
        node_run = await db.scalar(select(NodeRun).where(NodeRun.run_id == event.run_id, NodeRun.node_id == event.node_id))
        if node_run and node_run.status == NodeStatus.RUNNING:  # a late line must not replace "cancelled"
            node_run.error = event.message
            await db.commit()  # before the event, like every other announced change
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

    # The SDK's cost_json carries the node's spend as metadata {"usd"}; it rolls up into Run.cost_usd.
    cost_usd = None
    if art_data["name"] == "cost_json":
        cost_usd = await db.scalar(
            update(Run).where(Run.id == event.run_id)
            .values(cost_usd=func.coalesce(Run.cost_usd, 0) + Decimal(str(artifact.meta.get("usd", 0))))
            .returning(Run.cost_usd).execution_options(synchronize_session=False))
    await db.commit()  # before the events: subscribers re-read /runs/{id}/summary on them
    if cost_usd is not None:
        await event_bus.publish(event.run_id, {"type": "run_cost", "cost_usd": float(cost_usd)})

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
    await db.commit()  # before the event: subscribers re-read the run on it

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

    # Sleep until T-10min, then broadcast in-app warning + send email
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

        # Fetch model + endpoint URL from DB for the email
        try:
            from api.services.email import send_endpoint_expiry_warning
            async with AsyncSessionLocal() as _db:
                _node_run = await _db.get(NodeRun, uuid.UUID(node_run_id))
                if _node_run:
                    _model        = str((_node_run.inputs or {}).get("model", "unknown"))
                    _endpoint_url = str((_node_run.outputs or {}).get("endpoint_url", ""))
                    await send_endpoint_expiry_warning(
                        run_id=run_id,
                        model=_model,
                        endpoint_url=_endpoint_url,
                        minutes_remaining=10,
                    )
        except Exception as _exc:
            import logging
            logging.getLogger(__name__).warning("Expiry email failed: %s", _exc)

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
            node_run.finished_at = utcnow()
        if run:
            run.status      = RunStatus.SUCCEEDED
            run.finished_at = utcnow()
        await db.commit()
