"""
apps/api/routes/model_registry.py

DB-backed model registry endpoints.
Models are auto-registered when a node uploads a model artifact via
POST /internal/artifact, or can be registered manually via POST /models.

Routes:
  POST /models            — manually register a trained/quantized model
  GET  /models            — list models (optionally filter by format, base_model, tag)
  GET  /models/{model_id} — get a single model by UUID
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.database import get_db
from api.models.db import Model, ModelFormat
from api.services import ratelimit

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_db)]


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class ModelCreate(BaseModel):
    name: str
    base_model: str
    format: str          # "hf" | "awq" | "gguf"
    uri: str
    tags: list[str] = []
    description: str | None = None


class ModelOut(BaseModel):
    id: uuid.UUID
    name: str
    base_model: str
    format: str
    uri: str
    tags: list[str]
    description: str | None
    created_at: datetime


def _model_out(m: Model) -> ModelOut:
    return ModelOut(
        id=m.id,
        name=m.name,
        base_model=m.base_model,
        format=m.format.value,
        uri=m.uri,
        tags=m.tags or [],
        description=m.description,
        created_at=m.created_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=ModelOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(ratelimit.limit("write"))])
async def register_model(body: ModelCreate, db: Session):
    """Manually register a model in the registry."""
    try:
        fmt = ModelFormat(body.format.lower())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown format '{body.format}'. Valid: {[f.value for f in ModelFormat]}",
        )

    model = Model(
        user_id=uuid.uuid4(),
        name=body.name,
        base_model=body.base_model,
        format=fmt,
        uri=body.uri,
        tags=body.tags,
        description=body.description,
    )
    db.add(model)
    await db.flush()
    await db.refresh(model)
    return _model_out(model)


@router.get("", response_model=list[ModelOut])
async def list_models(
    db: Session,
    format: str | None = None,
    base_model: str | None = None,
    tag: str | None = None,
):
    """List registered models with optional filters."""
    stmt = select(Model).order_by(Model.created_at.desc())

    if format:
        try:
            fmt = ModelFormat(format.lower())
        except ValueError:
            return []
        stmt = stmt.where(Model.format == fmt)

    if base_model:
        stmt = stmt.where(Model.base_model == base_model)

    result = await db.execute(stmt)
    models = result.scalars().all()

    if tag:
        models = [m for m in models if tag in (m.tags or [])]

    return [_model_out(m) for m in models]


@router.get("/{model_id}", response_model=ModelOut)
async def get_model(model_id: uuid.UUID, db: Session):
    """Get a single model by UUID."""
    model = await db.get(Model, model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model '{model_id}' not found")
    return _model_out(model)
