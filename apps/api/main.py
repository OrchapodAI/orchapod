"""
apps/api/main.py

FastAPI application entry point for the Orchapod control plane.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlmodel import SQLModel

from api.database import engine
from api.routes.internal import router as internal_router
from api.routes.runs import router as runs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

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
app.include_router(runs_router)
