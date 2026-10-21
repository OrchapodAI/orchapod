"""
apps/api/routes/inference.py

One-click inference deployment — no workflow YAML knowledge required.

Routes:
  POST /inference/deploy     — deploy a model (serve / quantize-serve / quantize-gguf)
  GET  /inference/endpoints  — list active vLLM endpoints
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.database import get_session
from api.services import budget, ratelimit
from api.models.db import Workflow, Run, NodeRun, RunStatus

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
    # no hf_token: nodes get HF_TOKEN from the executor's env, and a token here would be stored in the workflow


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

@router.post("/deploy", response_model=DeployResponse, status_code=http_status.HTTP_202_ACCEPTED,
             dependencies=[Depends(ratelimit.limit("run"))])
async def deploy_model(body: DeployRequest, db: Session, scale: float = Depends(budget.scale)):
    """
    One-click model deployment. Creates a minimal workflow and starts a run immediately.

    Modes:
    - serve          → single vllm-serve node
    - quantize-serve → quantize (AWQ) node → vllm-serve node
    - quantize-gguf  → quantize (GGUF) node only
    """
    await budget.guard(db, scale)  # 503 kill switch, 402 no budget left; the run gets the caller's caps (R7)
    yaml_str, wf_name = _build_workflow_yaml(body)

    # Create the workflow
    from api.executor.dag import workflow_to_graph_json
    try:
        graph_json = workflow_to_graph_json(yaml_str)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to compile workflow: {e}")

    budget.gpu_guard((n["data"]["node_type"] for n in graph_json["nodes"]), scale)  # vllm-serve rents a GPU

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

    # Kick off execution through the one launcher, so POST /runs/{id}/cancel can stop it
    from api.executor.run_workflow import launch
    await db.commit()
    launch(run.id, scale)

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
        serve_name_line = f'\n      served_model_name: "{req.served_model_name}"' if req.served_model_name else ""
        yaml = f"""name: {name}
version: 1
nodes:
  - id: quantize
    type: quantize
    inputs:
      model: "{req.model}"
      method: awq
      bits: 4
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
        yaml = f"""name: {name}
version: 1
nodes:
  - id: quantize
    type: quantize
    inputs:
      model: "{req.model}"
      method: gguf
      precision: {req.precision}
    resources:
      gpu: {req.gpu}
      provider_pref:
        - vastai
"""

    return yaml, name
