"""
apps/api/main.py

FastAPI control-plane entry point for Orchapod.ai.
Handles: workflow CRUD, run lifecycle, live log streaming, internal container webhooks.

Start: uvicorn api.main:app --reload
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.database import AsyncSessionLocal, create_tables
from api.executor.run_workflow import sweep
from api.services.events import event_bus
from api.services.storage import ensure_bucket_exists
from api.routes import agent, workflows, runs, models, internal, ws, inference, model_registry, artifacts
from packages.providers.vastai import register_providers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await create_tables()
    await event_bus.connect()
    async with AsyncSessionLocal() as db:
        await sweep(db)  # runs a restart left mid-flight fail; their pods are terminated
    # MinIO in dev starts without the bucket; off the event loop, so a slow or absent store never delays startup
    asyncio.get_running_loop().run_in_executor(None, ensure_bucket_exists)

    register_providers(vastai_key=os.environ.get("VASTAI_API_KEY", ""))

    yield
    # Shutdown
    await event_bus.disconnect()


app = FastAPI(
    title="Orchapod API",
    description="Control plane for the Orchapod.ai LLM fine-tuning platform.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routes
app.include_router(workflows.router,       prefix="/workflows", tags=["workflows"])
app.include_router(runs.router,            prefix="/runs",      tags=["runs"])
app.include_router(models.router,          prefix="/registry",  tags=["registry"])
app.include_router(model_registry.router,  prefix="/models",    tags=["models"])
app.include_router(internal.router,        prefix="/internal",  tags=["internal"])
app.include_router(inference.router,       prefix="/inference", tags=["inference"])
app.include_router(artifacts.router,       prefix="/artifacts", tags=["artifacts"])
app.include_router(agent.router,           prefix="/agent",     tags=["agent"])

# WebSocket
app.include_router(ws.router, tags=["websocket"])


@app.get("/health")
async def health():
    return {"status": "ok"}
