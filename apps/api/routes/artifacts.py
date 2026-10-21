"""
apps/api/routes/artifacts.py

Global artifact browser.

Routes:
  GET /artifacts                — list all artifacts across runs, with optional filters
  GET /artifacts/{id}/download  — 307 to a presigned GET URL valid for 1 h
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.database import get_session
from api.models.db import Artifact, ArtifactKind, NodeRun, Run, Workflow
from api.services.redact import redact
from api.services.storage import presigned_download_url, r2_uri_to_key

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


class ArtifactListItem(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    node_run_id: uuid.UUID
    workflow_id: uuid.UUID | None
    workflow_name: str | None
    node_id: str
    name: str
    kind: ArtifactKind
    uri: str
    size_bytes: int | None
    meta: dict
    created_at: datetime


@router.get("", response_model=list[ArtifactListItem])
async def list_artifacts(
    db: Session,
    kind: str | None = Query(None, description="Filter by artifact kind"),
    limit: int = Query(100, ge=1, le=500),
):
    """Return artifacts across all runs, newest first."""
    stmt = (
        select(Artifact, NodeRun, Run, Workflow)
        .join(NodeRun, NodeRun.id == Artifact.node_run_id)
        .join(Run, Run.id == NodeRun.run_id)
        .outerjoin(Workflow, Workflow.id == Run.workflow_id)
        .order_by(Artifact.created_at.desc())
        .limit(limit)
    )
    if kind:
        stmt = stmt.where(Artifact.kind == kind)

    result = await db.execute(stmt)
    rows = result.all()

    items = []
    for artifact, node_run, run, workflow in rows:
        items.append(ArtifactListItem(
            id=artifact.id,
            run_id=run.id,
            node_run_id=artifact.node_run_id,
            workflow_id=run.workflow_id,
            workflow_name=workflow.name if workflow else None,
            node_id=node_run.node_id,
            name=artifact.name,
            kind=artifact.kind,
            uri=artifact.uri,
            size_bytes=artifact.size_bytes,
            meta=redact(artifact.meta or {}),
            created_at=artifact.created_at,
        ))
    return items


@router.get("/{artifact_id}/download", status_code=307)
async def download_artifact(artifact_id: uuid.UUID, db: Session):
    """A stable download link (the summary and the cached report use it); the presigned URL lasts 1 h."""
    artifact = await db.get(Artifact, artifact_id)
    if not artifact or not artifact.uri.startswith("r2://"):
        raise HTTPException(status_code=404, detail="No downloadable artifact")
    return RedirectResponse(presigned_download_url(r2_uri_to_key(artifact.uri)), status_code=307)
