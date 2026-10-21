"""
apps/api/routes/agent.py

The Orchapod Agent (docs/contracts.md "Agent API"): intent → plan → validate → run → monitor → report.

Routes:
  POST /agent/plan              — Nemotron 3 Super drafts a plan; validation errors go back for up to 2 repairs
  POST /agent/run               — validates again, then Workflow (opens on the canvas) + Run, launched at once
  GET  /agent/runs/{id}/report  — the run summary, plus a report cached on the first GET after a terminal status
  GET  /agent/templates         — the three canonical intents; they double as the STUB plans
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.agent import planner
from api.database import get_session
from api.executor import run_workflow as executor
from api.executor.dag import workflow_to_graph_json
from api.models.db import AgentRun, Run, RunStatus, Workflow
from api.routes.runs import TERMINAL, run_summary
from api.services import budget

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]
Scale = Annotated[float, Depends(budget.scale)]  # 1 for X-Orchapod-Admin, else ORCHAPOD_ANON_SCALE (R7)


class PlanRequest(BaseModel):
    intent: planner.Intent


class RunRequest(BaseModel):
    intent: planner.Intent
    plan: dict[str, Any]  # review() reports its shape errors in the contract's {"detail", "errors"}


@router.post("/plan")
async def plan(body: PlanRequest, db: Session, scale: Scale):
    """→ {plan, rationale, estimate, warnings, errors}; the UI disables Run while errors is non-empty."""
    return await planner.make_plan(body.intent, db, scale)


@router.post("/run", status_code=201)
async def run(body: RunRequest, db: Session, scale: Scale):
    """503 kill switch; 422 {detail, errors} when the plan fails validation; 402 when its estimate is over budget."""
    if budget.kill_switch():
        raise HTTPException(status_code=503, detail="the kill switch is on (ORCHAPOD_KILL_SWITCH)")
    errors, _, estimate = planner.review(body.plan)
    if errors:
        return JSONResponse(status_code=422, content={"detail": "the plan has errors", "errors": errors})
    plan = planner.Plan.model_validate(body.plan).model_dump()  # extra keys (resources, ...) are dropped
    await budget.guard(db, scale, need=estimate["usd"])

    text = yaml.safe_dump(plan, sort_keys=False)
    workflow = Workflow(user_id=uuid.uuid4(), name=plan["name"], yaml=text, graph_json=workflow_to_graph_json(text))
    db.add(workflow)
    await db.flush()
    run = Run(workflow_id=workflow.id, user_id=workflow.user_id, status=RunStatus.PROVISIONING_GPU)
    db.add(run)
    await db.flush()
    db.add(AgentRun(run_id=run.id, intent=body.intent, plan=plan, estimate=estimate))
    await db.commit()  # the executor reads the run in its own session
    executor.launch(run.id, scale)
    return {"run_id": run.id, "workflow_id": workflow.id, "estimate": estimate}


@router.get("/runs/{run_id}/report")
async def report(run_id: uuid.UUID, db: Session, scale: Scale):
    """→ {<GET /runs/{id}/summary fields>, intent, estimate, ready, markdown}; ready = terminal and written."""
    agent_run = await db.get(AgentRun, run_id)
    if not agent_run:
        raise HTTPException(status_code=404, detail="Not a run the agent started")
    finished_at = (await db.get(Run, run_id)).finished_at  # the attempt this report would describe
    summary = jsonable_encoder(await run_summary(run_id, db))
    terminal = summary["status"] in {s.value for s in TERMINAL}
    markdown = agent_run.report_md
    if terminal and markdown is None:
        written = await planner.write_report(agent_run, summary, db, scale)
        # kept only if no retry restarted the run meanwhile (retry clears report_md and finished_at), and only once
        # if two first GETs race; ponytail: both of those GETs still call Lightning (< $0.001, in the ledger)
        await db.execute(update(AgentRun).where(
            AgentRun.run_id == run_id, AgentRun.report_md.is_(None),
            select(Run.id).where(Run.id == run_id, Run.finished_at == finished_at).exists(),
        ).values(report_md=written).execution_options(synchronize_session=False))
        await db.commit()
        markdown = await db.scalar(select(AgentRun.report_md).where(AgentRun.run_id == run_id))
    ready = terminal and markdown is not None
    return {**summary, "intent": agent_run.intent, "estimate": agent_run.estimate, "ready": ready,
            "markdown": markdown if ready else None}


@router.get("/templates")
async def list_templates():
    """→ [{slug, title, intent, rationale, plan, estimate, reduced_inputs, reduced: {plan, estimate}}]; one-click Run posts
    a template's plan to /agent/run, and "Run it yourself" (the hosted demo's anonymous callers) posts `reduced.plan`."""
    return [{**t, "estimate": planner.estimate(t["plan"])[0], "reduced": planner.reduced(t)} for t in planner.templates()]
