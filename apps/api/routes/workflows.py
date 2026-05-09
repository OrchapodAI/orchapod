"""
apps/api/routes/workflows.py

Workflow CRUD + agent-based workflow builder.

Routes:
  POST   /workflows              — create from YAML
  GET    /workflows              — list (for current user)
  GET    /workflows/{id}         — get workflow + graph JSON
  PUT    /workflows/{id}         — update YAML (recompiles graph_json)
  DELETE /workflows/{id}         — delete
  POST   /workflows/from-prompt  — generate YAML via Claude agent
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.database import get_session
from api.models.db import Workflow
from api.executor.dag import compile_dag, workflow_to_graph_json

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class WorkflowCreate(BaseModel):
    name: str
    yaml: str
    user_id: uuid.UUID | None = None  # MVP: optional, auth via Clerk in prod


class WorkflowUpdate(BaseModel):
    name: str | None = None
    yaml: str | None = None


class WorkflowOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    yaml: str
    graph_json: dict
    version: int
    created_at: datetime
    updated_at: datetime


class PromptRequest(BaseModel):
    prompt: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
async def create_workflow(body: WorkflowCreate, db: Session):
    try:
        graph_json = workflow_to_graph_json(body.yaml)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid workflow YAML: {e}")

    workflow = Workflow(
        user_id=body.user_id or uuid.uuid4(),
        name=body.name,
        yaml=body.yaml,
        graph_json=graph_json,
    )
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return _to_out(workflow)


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(db: Session, user_id: uuid.UUID | None = None):
    stmt = select(Workflow).order_by(Workflow.created_at.desc())
    if user_id:
        stmt = stmt.where(Workflow.user_id == user_id)
    result = await db.execute(stmt)
    return [_to_out(w) for w in result.scalars().all()]


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(workflow_id: uuid.UUID, db: Session):
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _to_out(workflow)


@router.put("/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(workflow_id: uuid.UUID, body: WorkflowUpdate, db: Session):
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if body.name is not None:
        workflow.name = body.name

    if body.yaml is not None:
        try:
            graph_json = workflow_to_graph_json(body.yaml)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid workflow YAML: {e}")
        workflow.yaml = body.yaml
        workflow.graph_json = graph_json
        workflow.version += 1

    workflow.updated_at = datetime.utcnow()
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return _to_out(workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: uuid.UUID, db: Session):
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.delete(workflow)


@router.post("/from-prompt", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
async def create_workflow_from_prompt(body: PromptRequest, db: Session):
    """Use the Claude agent to generate a workflow YAML from a natural-language prompt."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    from api.agent.workflow_builder import build_workflow_from_prompt
    try:
        yaml_str = await build_workflow_from_prompt(body.prompt, api_key)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        graph_json = workflow_to_graph_json(yaml_str)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Agent produced invalid YAML: {e}")

    import yaml as _yaml
    spec = _yaml.safe_load(yaml_str)

    workflow = Workflow(
        user_id=uuid.uuid4(),
        name=spec.get("name", "Agent-generated workflow"),
        yaml=yaml_str,
        graph_json=graph_json,
    )
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return _to_out(workflow)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _to_out(w: Workflow) -> WorkflowOut:
    return WorkflowOut(
        id=w.id,
        user_id=w.user_id,
        name=w.name,
        yaml=w.yaml,
        graph_json=w.graph_json,
        version=w.version,
        created_at=w.created_at,
        updated_at=w.updated_at,
    )
