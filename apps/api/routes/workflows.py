"""
apps/api/routes/workflows.py

Workflow CRUD + agent-based workflow builder.

Routes:
  POST   /workflows              — create from YAML
  GET    /workflows              — list (for current user)
  GET    /workflows/{id}         — get workflow + graph JSON
  PUT    /workflows/{id}         — update YAML (recompiles graph_json)
  DELETE /workflows/{id}         — delete
  POST   /workflows/from-prompt  — the Orchapod Agent's planner drafts it (Nemotron on Token Factory)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.agent.planner import Intent, make_plan
from api.database import get_session
from api.models.db import Run, Workflow, utcnow
from api.executor.dag import load_yaml, workflow_to_graph_json
from api.services import budget, ratelimit
from api.services.redact import without_secrets

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]
Admin = Annotated[bool, Depends(budget.admin)]
WRITE = [Depends(ratelimit.limit("write"))]


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
    prompt: Intent


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED, dependencies=WRITE)
async def create_workflow(body: WorkflowCreate, db: Session):
    try:
        text = _stored(body.yaml)
        graph_json = workflow_to_graph_json(text)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid workflow YAML: {e}")

    workflow = Workflow(
        user_id=body.user_id or uuid.uuid4(),
        name=body.name,
        yaml=text,
        graph_json=graph_json,
    )
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return _to_out(workflow)


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(db: Session, user_id: uuid.UUID | None = None, limit: int = Query(500, ge=1, le=500)):
    """Newest first, at most 500: the runs page names up to 500 runs from this list (its golden-run filter)."""
    stmt = select(Workflow).order_by(Workflow.created_at.desc()).limit(limit)
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


@router.put("/{workflow_id}", response_model=WorkflowOut, dependencies=WRITE)
async def update_workflow(workflow_id: uuid.UUID, body: WorkflowUpdate, db: Session, is_admin: Admin):
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await _read_only_if_run(db, workflow_id, is_admin)

    if body.name is not None:
        workflow.name = body.name

    if body.yaml is not None:
        try:
            text = _stored(body.yaml)
            graph_json = workflow_to_graph_json(text)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Invalid workflow YAML: {e}")
        workflow.yaml = text
        workflow.graph_json = graph_json
        workflow.version += 1

    workflow.updated_at = utcnow()
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)
    return _to_out(workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=WRITE)
async def delete_workflow(workflow_id: uuid.UUID, db: Session, is_admin: Admin):
    workflow = await db.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await _read_only_if_run(db, workflow_id, is_admin)
    await db.delete(workflow)


@router.post("/from-prompt", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(ratelimit.limit("plan"))])
async def create_workflow_from_prompt(body: PromptRequest, db: Session,
                                      scale: float = Depends(budget.scale)):
    """The Orchapod Agent's planner drafts the workflow (same rules as POST /agent/plan); the canvas opens it,
    errors and all, as long as it compiles."""
    out = await make_plan(body.prompt, db, scale)
    out["plan"] = without_secrets(out["plan"])
    yaml_str = yaml.safe_dump(out["plan"], sort_keys=False)
    try:
        graph_json = workflow_to_graph_json(yaml_str) if out["plan"].get("nodes") else None
    except Exception:
        graph_json = None
    if graph_json is None:
        raise HTTPException(status_code=422, detail="; ".join(out["errors"]) or "the planner returned no nodes")

    workflow = Workflow(
        user_id=uuid.uuid4(),
        name=out["plan"].get("name") or "Agent-generated workflow",
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

def _stored(text: str) -> str:
    """The YAML to store: aliases refused (load_yaml), secret-looking node inputs dropped; re-dumped only if one was."""
    spec = load_yaml(text)
    clean = without_secrets(spec)
    return text if clean == spec else yaml.safe_dump(clean, sort_keys=False)


async def _read_only_if_run(db: AsyncSession, workflow_id: uuid.UUID, is_admin: bool) -> None:
    """409 for an anonymous caller once the workflow has runs: there is no user auth (D6), so anyone could otherwise
    rewrite the golden run's canvas, or the YAML a retry of someone's run executes."""
    if not is_admin and await db.scalar(select(Run.id).where(Run.workflow_id == workflow_id).limit(1)):
        raise HTTPException(status_code=409, detail="this workflow has runs, so it is read-only on the public app; "
                                                    "save a copy as a new workflow")


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
