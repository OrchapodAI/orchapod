"""
apps/api/routes/internal.py

Internal webhook routes — called by containers running inside GPU pods, not by users.

POST /internal/ttl       — vllm-serve registers its keep-alive + endpoint URL
POST /internal/artifact  — any node registers an output artifact after uploading to R2
POST /internal/log       — any node streams a log line to the run viewer

All three are called by packages/sdk-py/orchapod/{io,log}.py and
containers/vllm-serve/run.py.  They have no auth in MVP (control-plane network
is internal-only; add mTLS or a shared secret in V1).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.database import SessionLocal, get_db
from api.models.db import Artifact, ArtifactKind, NodeRun, NodeStatus

router = APIRouter(prefix="/internal", tags=["internal"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class TTLRequest(BaseModel):
    run_id:         str
    node_id:        str
    action:         str            # always "register_ttl" for now
    keep_alive_min: int
    endpoint_url:   str


class ArtifactPayload(BaseModel):
    name:     str
    uri:      str
    kind:     str
    metadata: dict[str, Any] = {}


class ArtifactRequest(BaseModel):
    run_id:   str
    node_id:  str
    artifact: ArtifactPayload


class LogRequest(BaseModel):
    run_id:  str
    node_id: str
    ts:      str
    level:   str
    message: str


# ---------------------------------------------------------------------------
# POST /internal/ttl
# ---------------------------------------------------------------------------

@router.post("/ttl", status_code=202)
async def register_ttl(body: TTLRequest, db: AsyncSession = Depends(get_db)):
    """
    Called by vllm-serve the moment its vLLM server is healthy.

    1. Stores the endpoint URL in NodeRun.outputs so the run viewer can surface it.
    2. Creates an Artifact record of kind=endpoint.
    3. Fires a background task that terminates the GPU pod after keep_alive_min minutes
       and marks the NodeRun as SUCCEEDED.
    """
    node_run = await _get_node_run(db, body.run_id, body.node_id)
    if not node_run:
        raise HTTPException(404, f"NodeRun not found: run={body.run_id} node={body.node_id}")

    # Persist endpoint URL into NodeRun outputs
    outputs = dict(node_run.outputs or {})
    outputs["endpoint_url"] = body.endpoint_url
    node_run.outputs = outputs
    await db.commit()

    # Create Artifact record
    db.add(Artifact(
        node_run_id=node_run.id,
        name="endpoint_url",
        kind=ArtifactKind.ENDPOINT,
        uri=body.endpoint_url,
        metadata={"keep_alive_min": body.keep_alive_min},
    ))
    await db.commit()

    # Background: terminate pod after TTL expires
    asyncio.create_task(
        _terminate_after_ttl(
            run_id=body.run_id,
            node_id=body.node_id,
            keep_alive_min=body.keep_alive_min,
        )
    )

    return {"status": "ttl_registered", "keep_alive_min": body.keep_alive_min}


async def _terminate_after_ttl(run_id: str, node_id: str, keep_alive_min: int) -> None:
    """
    Waits keep_alive_min minutes then:
    - terminates the GPU pod via the provider that owns it
    - marks the NodeRun as SUCCEEDED (it served successfully for its TTL)
    """
    await asyncio.sleep(keep_alive_min * 60)

    async with SessionLocal() as db:
        node_run = await _get_node_run(db, run_id, node_id)
        if not node_run:
            return

        if node_run.gpu_pod_id and node_run.gpu_provider:
            try:
                from packages.providers.vastai import PROVIDERS
                from packages.providers.base import Pod
                provider = PROVIDERS.get(node_run.gpu_provider)
                if provider:
                    pod = Pod(provider=node_run.gpu_provider, pod_id=node_run.gpu_pod_id)
                    await provider.terminate(pod)
            except Exception as exc:
                # Log but don't raise — we still want to mark the node done
                print(f"[TTL] terminate failed for pod {node_run.gpu_pod_id}: {exc}")

        node_run.status      = NodeStatus.SUCCEEDED
        node_run.finished_at = datetime.utcnow()
        await db.commit()


# ---------------------------------------------------------------------------
# POST /internal/artifact
# ---------------------------------------------------------------------------

@router.post("/artifact", status_code=201)
async def register_artifact(body: ArtifactRequest, db: AsyncSession = Depends(get_db)):
    """
    Called by packages/sdk-py/orchapod/io.py after every write_output() call.

    1. Creates an Artifact row with the R2 URI.
    2. Adds name → URI to NodeRun.outputs so downstream nodes can reference it
       via ${{ nodes.<id>.outputs.<name> }}.
    """
    node_run = await _get_node_run(db, body.run_id, body.node_id)
    if not node_run:
        raise HTTPException(404, f"NodeRun not found: run={body.run_id} node={body.node_id}")

    try:
        kind = ArtifactKind(body.artifact.kind)
    except ValueError:
        raise HTTPException(422, f"Unknown artifact kind: {body.artifact.kind}")

    db.add(Artifact(
        node_run_id=node_run.id,
        name=body.artifact.name,
        kind=kind,
        uri=body.artifact.uri,
        metadata=body.artifact.metadata,
    ))

    outputs = dict(node_run.outputs or {})
    outputs[body.artifact.name] = body.artifact.uri
    node_run.outputs = outputs

    await db.commit()
    return {"status": "artifact_registered", "uri": body.artifact.uri}


# ---------------------------------------------------------------------------
# POST /internal/log
# ---------------------------------------------------------------------------

@router.post("/log", status_code=204)
async def receive_log(body: LogRequest):
    """
    Called by packages/sdk-py/orchapod/log.py for every log line.

    MVP: prints to stdout so docker-compose logs pick it up.
    V1: publish to Redis pub/sub → SSE stream → run viewer.
    """
    print(f"[{body.run_id}/{body.node_id}] {body.ts} {body.level} {body.message}", flush=True)


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

async def _get_node_run(db: AsyncSession, run_id: str, node_id: str) -> NodeRun | None:
    result = await db.exec(
        select(NodeRun).where(
            NodeRun.run_id  == uuid.UUID(run_id),
            NodeRun.node_id == node_id,
        )
    )
    return result.first()
