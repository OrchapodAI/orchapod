"""
apps/api/routes/inference.py

One-click inference deployment — no workflow YAML knowledge required.

Routes:
  POST /inference/deploy     — deploy a model (serve / quantize-serve / quantize-gguf)
  GET  /inference/endpoints  — list active vLLM endpoints
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.database import get_session
from api.models.db import Workflow, Run, NodeRun, NodeStatus, RunStatus, Artifact, ArtifactKind

router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class DeployRequest(BaseModel):
    model: str = Field(description="HuggingFace model ID (e.g. Qwen/Qwen3-4B-Instruct) or R2 URI")
    mode: Literal["serve", "quantize-serve", "quantize-gguf"] = Field(
        default="serve",
        description=(
            "serve: deploy directly with vLLM. "
            "quantize-serve: AWQ-quantize then deploy with vLLM. "
            "quantize-gguf: GGUF-quantize only (for Ollama/llama.cpp)."
        ),
    )
    gpu: str = Field(default="1xH100", description="GPU spec: 1xH100, 1xA100, etc.")
    max_model_len: int = Field(default=8192, ge=512, le=131072)
    keep_alive_min: int = Field(default=60, ge=5, le=1440, description="Minutes before vLLM pod auto-terminates")
    precision: Literal["q4_k_m", "q5_k_m", "q8_0"] = Field(default="q4_k_m", description="GGUF precision (quantize-gguf mode)")
    served_model_name: str | None = Field(default=None, description="Override the model name in /v1/models")
    hf_token: str | None = Field(default=None, description="HuggingFace token for gated models")


class DeployResponse(BaseModel):
    run_id: uuid.UUID
    workflow_id: uuid.UUID
    status: str
    mode: str
    model: str


class EndpointOut(BaseModel):
    run_id: uuid.UUID
    workflow_name: str
    model: str
    endpoint_url: str | None
    status: str
    started_at: datetime | None
    keep_alive_min: int | None
    gpu_provider: str | None


# ---------------------------------------------------------------------------
# POST /inference/deploy
# ---------------------------------------------------------------------------

@router.post("/deploy", response_model=DeployResponse, status_code=http_status.HTTP_202_ACCEPTED)
async def deploy_model(body: DeployRequest, db: Session):
    """
    One-click model deployment. Creates a minimal workflow and starts a run immediately.

    Modes:
    - serve          → single vllm-serve node
    - quantize-serve → quantize (AWQ) node → vllm-serve node
    - quantize-gguf  → quantize (GGUF) node only
    """
    yaml_str, wf_name = _build_workflow_yaml(body)

    # Create the workflow
    from api.executor.dag import workflow_to_graph_json
    try:
        graph_json = workflow_to_graph_json(yaml_str)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to compile workflow: {e}")

    workflow = Workflow(
        user_id=uuid.uuid4(),
        name=wf_name,
        yaml=yaml_str,
        graph_json=graph_json,
    )
    db.add(workflow)
    await db.flush()
    await db.refresh(workflow)

    # Create and immediately start the run
    run = Run(
        workflow_id=workflow.id,
        user_id=workflow.user_id,
        inputs={},
        status=RunStatus.PROVISIONING_GPU,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)

    # Kick off execution in the background
    import asyncio
    from api.executor.run_workflow import run_workflow
    from api.services.events import event_bus
    from api.database import AsyncSessionLocal

    async def _run():
        async with AsyncSessionLocal() as bg_db:
            try:
                await run_workflow(run.id, bg_db, event_bus.publish)
            except Exception:
                pass

    asyncio.create_task(_run())

    return DeployResponse(
        run_id=run.id,
        workflow_id=workflow.id,
        status="provisioning_gpu",
        mode=body.mode,
        model=body.model,
    )


# ---------------------------------------------------------------------------
# GET /inference/endpoints
# ---------------------------------------------------------------------------

@router.get("/endpoints", response_model=list[EndpointOut])
async def list_endpoints(db: Session):
    """
    Return all vllm-serve node runs that have an endpoint_url, sorted newest first.
    Includes both running (live) and recently succeeded (expired) endpoints.
    """
    result = await db.execute(
        select(NodeRun, Run, Workflow)
        .join(Run, Run.id == NodeRun.run_id)
        .join(Workflow, Workflow.id == Run.workflow_id)
        .where(NodeRun.node_type == "vllm-serve")
        .order_by(Run.created_at.desc())
        .limit(50)
    )
    rows = result.all()

    out = []
    for node_run, run, workflow in rows:
        outputs = node_run.outputs or {}
        endpoint_url = outputs.get("endpoint_url")

        # Parse keep_alive_min from artifacts meta if available
        keep_alive_min: int | None = None
        model_input = (node_run.inputs or {}).get("model", "")

        out.append(EndpointOut(
            run_id=run.id,
            workflow_name=workflow.name,
            model=model_input,
            endpoint_url=endpoint_url,
            status=node_run.status.value,
            started_at=node_run.started_at,
            keep_alive_min=keep_alive_min,
            gpu_provider=run.gpu_provider,
        ))

    return out


# ---------------------------------------------------------------------------
# POST /inference/extend/{run_id}
# ---------------------------------------------------------------------------

# GPU hourly cost estimates (USD) — used for extension cost preview.
# Keyed by provider; refined by GPU model when available.
_HOURLY_COST_USD: dict[str, float] = {
    "vastai":  3.50,   # rough H100 SXM5 rate on Vast.ai
    "runpod":  3.99,
    "default": 3.50,
}


class ExtendRequest(BaseModel):
    extend_min: int = 60


class ExtendResponse(BaseModel):
    run_id:           uuid.UUID
    expires_at:       datetime
    extend_min:       int
    cost_estimate_usd: float


@router.post("/extend/{run_id}", response_model=ExtendResponse)
async def extend_endpoint(run_id: uuid.UUID, body: ExtendRequest, db: Session, preview: bool = False):
    """
    Extend a live vllm-serve endpoint by extend_min minutes.
    If preview=True (query param), returns cost estimate only — no changes made.
    Otherwise cancels the existing termination task and schedules a new one,
    and updates expires_at in the endpoint artifact meta and NodeRun outputs.
    """
    from api.routes.internal import _ttl_tasks, _terminate_after_ttl
    from api.services.events import event_bus

    # Find the vllm-serve NodeRun for this run
    result = await db.execute(
        select(NodeRun).where(
            NodeRun.run_id   == run_id,
            NodeRun.node_type == "vllm-serve",
        )
    )
    node_run = result.scalars().first()
    if not node_run:
        raise HTTPException(404, "No vllm-serve node found for this run")

    if node_run.status != NodeStatus.RUNNING:
        raise HTTPException(409, f"Endpoint is not running (status: {node_run.status.value})")

    # Find the endpoint artifact to update expires_at
    art_result = await db.execute(
        select(Artifact).where(
            Artifact.node_run_id == node_run.id,
            Artifact.kind        == ArtifactKind.ENDPOINT,
        )
    )
    artifact = art_result.scalars().first()

    # Compute new expiry and cost estimate
    now        = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=body.extend_min)
    hourly     = _HOURLY_COST_USD.get(node_run.gpu_provider or "default", _HOURLY_COST_USD["default"])
    cost       = round(hourly * body.extend_min / 60, 4)

    # Dry-run: return estimate without mutating anything
    if preview:
        return ExtendResponse(
            run_id=run_id,
            expires_at=expires_at,
            extend_min=body.extend_min,
            cost_estimate_usd=cost,
        )

    # Persist new expiry on artifact meta
    if artifact:
        meta = dict(artifact.meta or {})
        meta["expires_at"]     = expires_at.isoformat()
        meta["keep_alive_min"] = body.extend_min
        artifact.meta = meta
        db.add(artifact)

    # Persist on NodeRun outputs
    outputs = dict(node_run.outputs or {})
    outputs["expires_at"] = expires_at.isoformat()
    node_run.outputs = outputs
    db.add(node_run)

    await db.flush()

    # Cancel existing TTL task and reschedule
    node_run_id_str = str(node_run.id)
    old_task = _ttl_tasks.pop(node_run_id_str, None)
    if old_task and not old_task.done():
        old_task.cancel()

    new_task = asyncio.create_task(
        _terminate_after_ttl(
            run_id=str(run_id),
            node_run_id=node_run_id_str,
            gpu_provider=node_run.gpu_provider,
            gpu_pod_id=node_run.gpu_pod_id,
            keep_alive_min=body.extend_min,
        )
    )
    _ttl_tasks[node_run_id_str] = new_task

    # Notify WebSocket subscribers
    await event_bus.publish(run_id, {
        "type":              "endpoint_expiry",
        "node_run_id":       node_run_id_str,
        "expires_at":        expires_at.isoformat(),
        "minutes_remaining": body.extend_min,
    })

    return ExtendResponse(
        run_id=run_id,
        expires_at=expires_at,
        extend_min=body.extend_min,
        cost_estimate_usd=cost,
    )


# ---------------------------------------------------------------------------
# YAML builder
# ---------------------------------------------------------------------------

def _build_workflow_yaml(req: DeployRequest) -> tuple[str, str]:
    """Returns (yaml_str, workflow_name)."""
    slug = req.model.split("/")[-1].lower().replace(".", "-").replace("_", "-")

    if req.mode == "serve":
        name = f"serve-{slug}"
        extra = ""
        if req.served_model_name:
            extra += f"\n      served_model_name: \"{req.served_model_name}\""
        if req.hf_token:
            extra += f"\n      hf_token: \"{req.hf_token}\""
        yaml = f"""name: {name}
version: 1
nodes:
  - id: serve
    type: vllm-serve
    inputs:
      model: "{req.model}"
      max_model_len: {req.max_model_len}
      keep_alive_min: {req.keep_alive_min}{extra}
    resources:
      gpu: {req.gpu}
      provider_pref:
        - vastai
"""

    elif req.mode == "quantize-serve":
        name = f"quantize-serve-{slug}"
        hf_tok_line = f'\n      hf_token: "{req.hf_token}"' if req.hf_token else ""
        serve_name_line = f'\n      served_model_name: "{req.served_model_name}"' if req.served_model_name else ""
        yaml = f"""name: {name}
version: 1
nodes:
  - id: quantize
    type: quantize
    inputs:
      model: "{req.model}"
      method: awq
      bits: 4{hf_tok_line}
    resources:
      gpu: {req.gpu}
      provider_pref:
        - vastai

  - id: serve
    type: vllm-serve
    needs:
      - quantize
    inputs:
      model: "${{{{ nodes.quantize.outputs.awq_model }}}}"
      max_model_len: {req.max_model_len}
      keep_alive_min: {req.keep_alive_min}{serve_name_line}
    resources:
      gpu: {req.gpu}
      provider_pref:
        - vastai
"""

    else:  # quantize-gguf
        name = f"quantize-gguf-{slug}"
        hf_tok_line = f'\n      hf_token: "{req.hf_token}"' if req.hf_token else ""
        yaml = f"""name: {name}
version: 1
nodes:
  - id: quantize
    type: quantize
    inputs:
      model: "{req.model}"
      method: gguf
      precision: {req.precision}{hf_tok_line}
    resources:
      gpu: {req.gpu}
      provider_pref:
        - vastai
"""

    return yaml, name
