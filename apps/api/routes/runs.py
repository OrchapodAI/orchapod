"""
apps/api/routes/runs.py

User-facing routes for submitting and monitoring node runs.

POST /nodes/run           — submit a single node (no workflow YAML required)
GET  /runs/{run_id}       — poll run status + node outputs
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from api.database import SessionLocal, get_db
from api.models.db import NodeRun, NodeStatus, Run, RunStatus

router = APIRouter(tags=["runs"])


# ---------------------------------------------------------------------------
# Request / response bodies
# ---------------------------------------------------------------------------

class ResourcesRequest(BaseModel):
    gpu:           str       = "1xH100"
    provider_pref: list[str] = ["vastai", "runpod"]


class NodeRunRequest(BaseModel):
    node_type: str
    inputs:    dict[str, Any]
    resources: ResourcesRequest = ResourcesRequest()


class NodeRunResponse(BaseModel):
    run_id:      str
    node_run_id: str
    status:      str
    status_url:  str


class NodeRunStatus(BaseModel):
    node_run_id: str
    node_type:   str
    status:      str
    outputs:     dict[str, Any]
    started_at:  str | None
    finished_at: str | None
    error:       str | None


class RunStatusResponse(BaseModel):
    run_id:  str
    status:  str
    nodes:   list[NodeRunStatus]


# ---------------------------------------------------------------------------
# POST /nodes/run
# ---------------------------------------------------------------------------

@router.post("/nodes/run", response_model=NodeRunResponse, status_code=202)
async def submit_node_run(body: NodeRunRequest, db: AsyncSession = Depends(get_db)):
    """
    Submit a single node for execution on a GPU pod.

    The run is created immediately and execution starts in the background.
    Poll GET /runs/{run_id} for status and outputs.
    """
    from packages.workflow_schema.models import NodeType

    try:
        NodeType(body.node_type)
    except ValueError:
        valid = [n.value for n in NodeType]
        raise HTTPException(422, f"Unknown node_type '{body.node_type}'. Valid: {valid}")

    run = Run(user_id=uuid.uuid4(), status=RunStatus.PROVISIONING_GPU)
    db.add(run)
    await db.flush()

    node_run = NodeRun(
        run_id=run.id,
        node_id="node",
        node_type=body.node_type,
        status=NodeStatus.PENDING,
        inputs=body.inputs,
    )
    db.add(node_run)
    await db.commit()
    await db.refresh(run)
    await db.refresh(node_run)

    asyncio.create_task(
        _execute_standalone_node(
            run_id=str(run.id),
            node_run_id=str(node_run.id),
            node_type=body.node_type,
            inputs=body.inputs,
            resources=body.resources,
        )
    )

    return NodeRunResponse(
        run_id=str(run.id),
        node_run_id=str(node_run.id),
        status="provisioning_gpu",
        status_url=f"/runs/{run.id}",
    )


# ---------------------------------------------------------------------------
# GET /runs/{run_id}
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}", response_model=RunStatusResponse)
async def get_run_status(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Poll run status and node outputs."""
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    result = await db.exec(select(NodeRun).where(NodeRun.run_id == run_id))
    node_runs = result.all()

    return RunStatusResponse(
        run_id=str(run.id),
        status=run.status.value,
        nodes=[
            NodeRunStatus(
                node_run_id=str(nr.id),
                node_type=nr.node_type,
                status=nr.status.value,
                outputs=nr.outputs or {},
                started_at=nr.started_at.isoformat() if nr.started_at else None,
                finished_at=nr.finished_at.isoformat() if nr.finished_at else None,
                error=nr.error,
            )
            for nr in node_runs
        ],
    )


# ---------------------------------------------------------------------------
# Background execution
# ---------------------------------------------------------------------------

async def _execute_standalone_node(
    run_id:      str,
    node_run_id: str,
    node_type:   str,
    inputs:      dict[str, Any],
    resources:   ResourcesRequest,
) -> None:
    """
    Provisions a GPU pod, starts the container, and waits for exit (except
    vllm-serve, which is long-running and managed by the TTL route).
    Runs entirely in the background after POST /nodes/run returns 202.
    """
    from packages.providers.base import GPUSpec, Pod
    from packages.providers.vastai import PROVIDERS, pick_provider
    from packages.workflow_schema.models import ResourceSpec

    resource_spec = ResourceSpec(
        gpu=resources.gpu,
        provider_pref=resources.provider_pref,
    )

    async with SessionLocal() as db:
        node_run = await db.get(NodeRun, uuid.UUID(node_run_id))
        run      = await db.get(Run, uuid.UUID(run_id))

        try:
            provider = await pick_provider(resource_spec)
            gpu_type = resource_spec.gpu.split("x")[-1]
            gpu_spec = GPUSpec(gpu_type=gpu_type, count=1)

            image = f"ghcr.io/orchapod/{node_type}:latest"
            env   = _build_env(inputs, node_run)

            pod = await provider.provision(gpu_spec=gpu_spec, image=image, env=env)

            node_run.gpu_pod_id   = pod.pod_id
            node_run.gpu_provider = provider.name
            node_run.status       = NodeStatus.RUNNING
            node_run.started_at   = datetime.utcnow()
            run.status            = RunStatus.RUNNING
            run.gpu_provider      = provider.name
            run.gpu_pod_id        = pod.pod_id
            await db.commit()

            if node_type == "vllm-serve":
                # Long-running: container calls /internal/ttl once healthy.
                # TTL background task handles termination + status update.
                return

            exit_code = await provider.wait(pod)

            if exit_code != 0:
                raise RuntimeError(f"Container exited with code {exit_code}")

            await provider.terminate(pod)
            node_run.status      = NodeStatus.SUCCEEDED
            node_run.finished_at = datetime.utcnow()
            run.status           = RunStatus.SUCCEEDED
            run.finished_at      = datetime.utcnow()
            await db.commit()

        except Exception as exc:
            node_run.status      = NodeStatus.FAILED
            node_run.error       = str(exc)
            node_run.finished_at = datetime.utcnow()
            run.status           = RunStatus.FAILED
            run.finished_at      = datetime.utcnow()
            await db.commit()
            # Do not re-raise: runs inside asyncio.create_task with no awaiter.
            # Error is already persisted — visible via GET /runs/{id}.


def _build_env(inputs: dict[str, Any], node_run: NodeRun) -> dict[str, str]:
    """Build the env dict injected into the GPU pod container."""
    return {
        "ORCHAPOD_NODE_INPUTS":      json.dumps(inputs, separators=(",", ":")),
        "ORCHAPOD_NODE_OUTPUTS_DIR": "/tmp/orchapod_outputs",
        "ORCHAPOD_RUN_ID":           str(node_run.run_id),
        "ORCHAPOD_NODE_ID":          node_run.node_id,
        "ORCHAPOD_R2_ENDPOINT":      os.environ["ORCHAPOD_R2_ENDPOINT"],
        "ORCHAPOD_R2_ACCESS_KEY":    os.environ["ORCHAPOD_R2_ACCESS_KEY"],
        "ORCHAPOD_R2_SECRET_KEY":    os.environ["ORCHAPOD_R2_SECRET_KEY"],
        "ORCHAPOD_R2_BUCKET":        os.environ.get("ORCHAPOD_R2_BUCKET", "orchapod-artifacts"),
        "ORCHAPOD_CONTROL_URL":      os.environ["ORCHAPOD_CONTROL_URL"],
        "ANTHROPIC_API_KEY":         os.environ.get("ANTHROPIC_API_KEY", ""),
        "HF_TOKEN":                  os.environ.get("HF_TOKEN", ""),
    }
