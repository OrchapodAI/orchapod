"""Spend safety: a gpu node with default resources never provisions on vast.ai (contracts "provider selection")."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from sqlmodel import select

from api.executor import run_workflow as ex
from api.models.db import NodeRun, Run, RunStatus, Workflow
from api.services import provider_selector
from packages.providers.base import Quote
from packages.providers.vastai import VastAIProvider


async def test_default_resources_never_provision_on_vastai_without_nebius(db, monkeypatch):
    monkeypatch.setenv("VASTAI_API_KEY", "vast-key")
    monkeypatch.delenv("NEBIUS_PROJECT_ID", raising=False)
    monkeypatch.delenv("NEBIUS_IAM_TOKEN", raising=False)
    monkeypatch.setattr(provider_selector, "_providers", {})  # rebuilt from this env
    vast = []

    async def quote(self, gpu_spec):  # vast.ai has capacity
        vast.append("quote")
        return Quote(provider="vastai", price_per_hour=1.0, available=True, gpu_type=gpu_spec.gpu_type)

    async def provision(self, gpu_spec, image, env, ports=()):
        vast.append("provision")
        raise RuntimeError("provisioned on vast.ai")

    monkeypatch.setattr(VastAIProvider, "quote", quote)
    monkeypatch.setattr(VastAIProvider, "provision", provision)
    wf = Workflow(user_id=uuid.uuid4(), name="g", graph_json={},  # no resources: ResourceSpec() defaults
                  yaml="name: g\nnodes:\n  - id: t\n    type: unsloth-train\n    inputs: {model: m}\n")
    db.add(wf)
    await db.flush()
    run = Run(workflow_id=wf.id, user_id=wf.user_id, inputs={}, status=RunStatus.PROVISIONING_GPU)
    db.add(run)
    await db.commit()

    await ex.run_workflow(run.id, db, AsyncMock())

    node = (await db.exec(select(NodeRun).where(NodeRun.run_id == run.id))).one()
    await db.refresh(node)
    assert vast == []
    assert node.error == "no gpu provider: none of ['nebius'] is configured with 1xH100 capacity (nebius needs NEBIUS_PROJECT_ID)"
