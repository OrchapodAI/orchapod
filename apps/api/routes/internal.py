"""
apps/api/routes/internal.py

Webhook routes called by GPU pod containers during execution.

POST /internal/artifact  — register a completed output artifact
POST /internal/ttl       — register endpoint + schedule pod termination
POST /internal/log       — receive a log line (fire-and-forget)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.database import get_db
from api.models.db import Artifact, ArtifactKind, Model, ModelFormat, NodeRun, NodeStatus, Run, RunStatus

router = APIRouter(prefix="/internal", tags=["internal"])


# ---------------------------------------------------------------------------
# POST /internal/artifact
# ---------------------------------------------------------------------------

class ArtifactPayload(BaseModel):
    name:     str
    uri:      str
    kind:     str
    metadata: dict[str, Any] = {}


class RegisterArtifactRequest(BaseModel):
    run_id:   str
    node_id:  str
    artifact: ArtifactPayload


@router.post("/artifact", status_code=201)
async def register_artifact(body: RegisterArtifactRequest, db: AsyncSession = Depends(get_db)):
    try:
        kind = ArtifactKind(body.artifact.kind)
    except ValueError:
        raise HTTPException(422, f"Unknown artifact kind '{body.artifact.kind}'. "
                            f"Valid: {[k.value for k in ArtifactKind]}")

    result = await db.exec(
        select(NodeRun).where(
            NodeRun.run_id  == uuid.UUID(body.run_id),
            NodeRun.node_id == body.node_id,
        )
    )
    node_run = result.first()
    if node_run is None:
        raise HTTPException(404, f"NodeRun not found: run_id={body.run_id}, node_id={body.node_id}")

    artifact = Artifact(
        node_run_id=node_run.id,
        name=body.artifact.name,
        kind=kind,
        uri=body.artifact.uri,
        meta=body.artifact.metadata,
    )
    db.add(artifact)

    # update node outputs so downstream nodes can reference this artifact by name
    outputs = dict(node_run.outputs or {})
    outputs[body.artifact.name] = body.artifact.uri
    node_run.outputs = outputs

    await db.flush()  # get artifact.id before auto-registering model

    # Auto-register model record for any model artifact
    if kind == ArtifactKind.MODEL:
        _auto_register_model(db, artifact, node_run, body.artifact.metadata)

    await db.commit()
    return {"artifact_id": str(artifact.id)}


def _auto_register_model(
    db:       AsyncSession,
    artifact: Artifact,
    node_run: NodeRun,
    metadata: dict,
) -> None:
    """
    Create a Model registry entry from a model artifact.
    format + base_model are inferred from the artifact metadata written by containers.
    """
    fmt_str    = metadata.get("format", "hf").lower()
    base_model = metadata.get("base_model") or node_run.inputs.get("model", "unknown")

    try:
        fmt = ModelFormat(fmt_str)
    except ValueError:
        fmt = ModelFormat.HF

    # Derive a default name: base_model slug + format + precision/bits if present
    slug = base_model.split("/")[-1].lower().replace(".", "-")
    suffix = metadata.get("precision") or (f"awq{metadata.get('bits','4')}" if fmt == ModelFormat.AWQ else "")
    name = f"{slug}-{fmt.value}" + (f"-{suffix}" if suffix else "")

    model = Model(
        user_id=node_run.run_id,   # placeholder — replaced with real auth in V1
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


# ---------------------------------------------------------------------------
# POST /internal/ttl
# ---------------------------------------------------------------------------

class RegisterTTLRequest(BaseModel):
    run_id:         str
    node_id:        str
    action:         str          # "register_ttl"
    keep_alive_min: int
    endpoint_url:   str


@router.post("/ttl", status_code=202)
async def register_ttl(body: RegisterTTLRequest, db: AsyncSession = Depends(get_db)):
    result = await db.exec(
        select(NodeRun).where(
            NodeRun.run_id  == uuid.UUID(body.run_id),
            NodeRun.node_id == body.node_id,
        )
    )
    node_run = result.first()
    if node_run is None:
        raise HTTPException(404, f"NodeRun not found: run_id={body.run_id}, node_id={body.node_id}")

    # Store endpoint URL in outputs
    outputs = dict(node_run.outputs or {})
    outputs["endpoint_url"] = body.endpoint_url
    node_run.outputs = outputs

    # Create an ENDPOINT artifact
    artifact = Artifact(
        node_run_id=node_run.id,
        name="endpoint_url",
        kind=ArtifactKind.ENDPOINT,
        uri=body.endpoint_url,
        meta={"keep_alive_min": body.keep_alive_min},
    )
    db.add(artifact)
    await db.commit()

    # Schedule termination in background
    asyncio.create_task(
        _terminate_after_ttl(
            run_id=body.run_id,
            node_run_id=str(node_run.id),
            gpu_provider=node_run.gpu_provider,
            gpu_pod_id=node_run.gpu_pod_id,
            keep_alive_min=body.keep_alive_min,
        )
    )

    return {"status": "ttl_registered", "keep_alive_min": body.keep_alive_min}


async def _terminate_after_ttl(
    run_id:       str,
    node_run_id:  str,
    gpu_provider: str | None,
    gpu_pod_id:   str | None,
    keep_alive_min: int,
) -> None:
    """Sleep, then terminate pod and mark run SUCCEEDED."""
    from api.database import SessionLocal
    from packages.providers.vastai import PROVIDERS
    from packages.providers.base import Pod

    await asyncio.sleep(keep_alive_min * 60)

    if gpu_provider and gpu_pod_id:
        provider = PROVIDERS.get(gpu_provider)
        if provider:
            try:
                await provider.terminate(Pod(provider=gpu_provider, pod_id=gpu_pod_id))
            except Exception:
                pass

    async with SessionLocal() as db:
        node_run = await db.get(NodeRun, uuid.UUID(node_run_id))
        run      = await db.get(Run, uuid.UUID(run_id))
        if node_run:
            node_run.status      = NodeStatus.SUCCEEDED
            node_run.finished_at = datetime.utcnow()
        if run:
            run.status      = RunStatus.SUCCEEDED
            run.finished_at = datetime.utcnow()
        await db.commit()


# ---------------------------------------------------------------------------
# POST /internal/log
# ---------------------------------------------------------------------------

class LogLineRequest(BaseModel):
    run_id:  str
    node_id: str
    ts:      str
    level:   str
    message: str


@router.post("/log", status_code=204)
async def receive_log(body: LogLineRequest):
    # Fire-and-forget: just print for now; V1 will fan out to SSE / persist to R2
    print(f"[{body.level}] {body.ts} run={body.run_id} node={body.node_id}: {body.message}")
    return Response(status_code=204)
