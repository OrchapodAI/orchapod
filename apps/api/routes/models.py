"""
apps/api/routes/models.py

Model registry — search, inspect, and manually register models.

GET  /models                — list models, filterable by base_model / format / tag
GET  /models/{model_id}     — get a single model record
POST /models                — manually register a model (auto-registration is the
                              normal path via /internal/artifact)
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel as PydanticModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.database import get_db
from api.models.db import Model, ModelFormat

router = APIRouter(prefix="/models", tags=["models"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ModelResponse(PydanticModel):
    id:          str
    name:        str
    description: str | None
    base_model:  str
    format:      str
    uri:         str
    size_bytes:  int | None
    tags:        list[str]
    artifact_id: str | None
    node_run_id: str | None
    run_id:      str | None
    created_at:  str


class RegisterModelRequest(PydanticModel):
    name:        str
    base_model:  str
    format:      str
    uri:         str
    description: str | None = None
    size_bytes:  int | None = None
    tags:        list[str]  = []
    # optional lineage — supplied automatically by /internal/artifact
    artifact_id: str | None = None
    node_run_id: str | None = None
    run_id:      str | None = None


def _to_response(m: Model) -> ModelResponse:
    return ModelResponse(
        id=str(m.id),
        name=m.name,
        description=m.description,
        base_model=m.base_model,
        format=m.format.value,
        uri=m.uri,
        size_bytes=m.size_bytes,
        tags=m.tags or [],
        artifact_id=str(m.artifact_id) if m.artifact_id else None,
        node_run_id=str(m.node_run_id) if m.node_run_id else None,
        run_id=str(m.run_id)      if m.run_id      else None,
        created_at=m.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# GET /models
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ModelResponse])
async def list_models(
    base_model: str | None = Query(default=None, description="Filter by base model HF ID"),
    format:     str | None = Query(default=None, description="Filter by format: hf | awq | gguf"),
    tag:        str | None = Query(default=None, description="Filter by tag (single)"),
    limit:      int        = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Model).order_by(Model.created_at.desc()).limit(limit)

    if base_model:
        stmt = stmt.where(Model.base_model == base_model)
    if format:
        try:
            fmt = ModelFormat(format)
        except ValueError:
            raise HTTPException(422, f"Unknown format '{format}'. Valid: {[f.value for f in ModelFormat]}")
        stmt = stmt.where(Model.format == fmt)

    result = await db.exec(stmt)
    models = result.all()

    if tag:
        # JSON array containment — filter in Python (works for SQLite + PG)
        models = [m for m in models if tag in (m.tags or [])]

    return [_to_response(m) for m in models]


# ---------------------------------------------------------------------------
# GET /models/{model_id}
# ---------------------------------------------------------------------------

@router.get("/{model_id}", response_model=ModelResponse)
async def get_model(model_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    model = await db.get(Model, model_id)
    if not model:
        raise HTTPException(404, f"Model {model_id} not found")
    return _to_response(model)


# ---------------------------------------------------------------------------
# POST /models  (manual registration)
# ---------------------------------------------------------------------------

@router.post("", response_model=ModelResponse, status_code=201)
async def register_model(
    body: RegisterModelRequest,
    db:   AsyncSession = Depends(get_db),
):
    try:
        fmt = ModelFormat(body.format)
    except ValueError:
        raise HTTPException(422, f"Unknown format '{body.format}'. Valid: {[f.value for f in ModelFormat]}")

    model = Model(
        user_id=uuid.uuid4(),   # TODO: replace with real auth user_id
        name=body.name,
        description=body.description,
        base_model=body.base_model,
        format=fmt,
        uri=body.uri,
        size_bytes=body.size_bytes,
        tags=body.tags,
        artifact_id=uuid.UUID(body.artifact_id) if body.artifact_id else None,
        node_run_id=uuid.UUID(body.node_run_id) if body.node_run_id else None,
        run_id=uuid.UUID(body.run_id)      if body.run_id      else None,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return _to_response(model)
