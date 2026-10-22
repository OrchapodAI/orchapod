"""
apps/api/routes/agent.py

The Orchapod Agent (docs/contracts.md "Agent API"): intent → plan → validate → run → monitor → report.

Routes:
  POST /agent/plan              — Nemotron 3 Super drafts a plan; validation errors go back for up to 2 repairs
  POST /agent/run               — validates again, then Workflow (opens on the canvas) + Run, launched at once
  GET  /agent/runs/{id}/report  — the run summary, plus the report written in the background once the run ends
  GET  /agent/templates         — the three canonical intents; they double as the STUB plans
"""

from __future__ import annotations

import asyncio
import logging
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
from api.routes.runs import TERMINAL, cancel_token, run_summary
from api.services import budget, ratelimit
from api.services.redact import without_secrets

router = APIRouter()
log = logging.getLogger("api.agent")

Session = Annotated[AsyncSession, Depends(get_session)]
Scale = Annotated[float, Depends(budget.scale)]  # 1 for X-Orchapod-Admin, else ORCHAPOD_ANON_SCALE (R7)


class PlanRequest(BaseModel):
    intent: planner.Intent


class RunRequest(BaseModel):
    intent: planner.Intent
    plan: dict[str, Any]  # review() reports its shape errors in the contract's {"detail", "errors"}


@router.post("/plan", dependencies=[Depends(ratelimit.limit("plan"))])
async def plan(body: PlanRequest, db: Session, scale: Scale):
    """→ {plan, rationale, estimate, warnings, errors}; the UI disables Run while errors is non-empty."""
    return await planner.make_plan(body.intent, db, scale)


@router.post("/run", status_code=201, dependencies=[Depends(ratelimit.limit("run"))])
async def run(body: RunRequest, db: Session, scale: Scale):
    """503 kill switch; 422 {detail, errors} when the plan fails validation; 402 when its estimate is over budget.
    → 201 {run_id, workflow_id, estimate, cancel_token}: the token is returned once; an anonymous cancel needs it."""
    if budget.kill_switch():
        raise HTTPException(status_code=503, detail="the kill switch is on (ORCHAPOD_KILL_SWITCH)")
    errors, _, estimate = planner.review(body.plan)
    if errors:
        return JSONResponse(status_code=422, content={"detail": "the plan has errors", "errors": errors})
    plan = without_secrets(planner.Plan.model_validate(body.plan).model_dump())  # extra keys (resources, ...) go too
    budget.gpu_guard((n["type"] for n in plan["nodes"]), scale)
    await budget.guard(db, scale, need=estimate["usd"])

    text = yaml.safe_dump(plan, sort_keys=False)
    workflow = Workflow(user_id=uuid.uuid4(), name=plan["name"], yaml=text, graph_json=workflow_to_graph_json(text))
    db.add(workflow)
    await db.flush()
    run = Run(workflow_id=workflow.id, user_id=workflow.user_id, status=RunStatus.PROVISIONING_GPU)
    db.add(run)
    await db.flush()
    token, kept = cancel_token(run.id)
    db.add_all([AgentRun(run_id=run.id, intent=body.intent, plan=plan, estimate=estimate), kept])
    await db.commit()  # the executor reads the run in its own session
    executor.launch(run.id, scale)
    return {"run_id": run.id, "workflow_id": workflow.id, "estimate": estimate, "cancel_token": token}  # once


@router.get("/runs/{run_id}/report")
async def report(run_id: uuid.UUID, db: Session, scale: Scale):
    """→ {<GET /runs/{id}/summary fields>, intent, estimate, ready, markdown}; ready = terminal and written. It never waits
    on Nemotron: the report is written in the background once the run ends, and a poll reads it."""
    agent_run = await db.get(AgentRun, run_id, populate_existing=True)  # the writer stores it from its own session
    if not agent_run:
        raise HTTPException(status_code=404, detail="Not a run the agent started")
    summary = jsonable_encoder(await run_summary(run_id, db))
    terminal = summary["status"] in {s.value for s in TERMINAL}
    if terminal and agent_run.report_md is None:
        # the executor asked for it as the run ended; this covers a run that ended elsewhere (a cancel before it started,
        # the startup sweep) or whose writer an API restart lost
        report_later(run_id, scale)
    ready = terminal and agent_run.report_md is not None
    return {**summary, "intent": agent_run.intent, "estimate": agent_run.estimate, "ready": ready,
            "markdown": agent_run.report_md if ready else None}


# run_id → the task writing its report; one per run. ponytail: in-process, which the one API worker allows.
_reporting: dict[uuid.UUID, asyncio.Task] = {}


def report_later(run_id: uuid.UUID, scale: float) -> None:
    """Write the report of an agent run that has ended, once, in the background, and cache it in agent_run.report_md
    (R8). The executor calls it as a run ends, and the GET for an ended run without one; anything else is left alone."""
    if (task := _reporting.get(run_id)) and not task.done():
        return
    task = asyncio.create_task(_write_report(run_id, scale))
    _reporting[run_id] = task
    task.add_done_callback(lambda t: _reporting.pop(run_id) if _reporting.get(run_id) is t else None)


async def _write_report(run_id: uuid.UUID, scale: float) -> None:
    from api import database
    try:
        async with database.AsyncSessionLocal() as db:
            agent_run, run = await db.get(AgentRun, run_id), await db.get(Run, run_id)
            if agent_run and run and agent_run.report_md is None and run.status in TERMINAL:
                finished_at = run.finished_at  # the attempt this report describes
                written = await planner.write_report(agent_run, jsonable_encoder(await run_summary(run_id, db)), db, scale)
                # kept only if no retry restarted the run meanwhile (retry clears report_md and finished_at)
                await db.execute(update(AgentRun).where(
                    AgentRun.run_id == run_id, AgentRun.report_md.is_(None),
                    select(Run.id).where(Run.id == run_id, Run.finished_at == finished_at).exists(),
                ).values(report_md=written).execution_options(synchronize_session=False))
            await db.commit()  # a read alone ends with it too: close() would roll back, and tests share one connection
    except Exception:
        log.exception("the report of run %s was not written", run_id)  # the next poll of an ended run tries again


@router.get("/templates")
async def list_templates(scale: Scale):
    """→ [{slug, title, intent, rationale, plan, estimate, reduced_inputs, reduced: {plan, estimate}, fits}]; one-click Run
    posts a template's plan to /agent/run, and "Run it yourself" posts `reduced.plan`. fits: the reduced estimate is
    within this caller's run cap (ORCHAPOD_MAX_RUN_USD × their scale), and an anonymous caller's plan has no gpu node."""
    out = []
    for t in planner.templates():
        small = planner.reduced(t)
        gpu = scale < 1 and budget.gpu_nodes(n["type"] for n in small["plan"]["nodes"])  # /agent/run would 403
        out.append({**t, "estimate": planner.estimate(t["plan"])[0], "reduced": small,
                    "fits": small["estimate"]["usd"] <= budget.run_cap(scale) and not gpu})
    return out
