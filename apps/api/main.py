"""
apps/api/main.py

Orchapod control-plane API.
Entry point: uvicorn api.main:app --host 0.0.0.0 --port 8000

Startup sequence:
  1. Create DB tables (dev only — production uses Alembic migrations)
  2. Register GPU providers from environment keys
  3. Mount routers
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import SQLModel

from api.database import engine
from api.routes.internal import router as internal_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on first boot (idempotent — safe to run repeatedly in dev)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    # Initialise GPU provider registry
    from packages.providers.vastai import register_providers
    register_providers(
        runpod_key=os.environ.get("RUNPOD_API_KEY", ""),
        vastai_key=os.environ.get("VASTAI_API_KEY", ""),
    )

    yield
    await engine.dispose()


app = FastAPI(
    title="Orchapod Control Plane",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(internal_router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
