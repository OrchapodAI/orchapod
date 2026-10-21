"""
apps/api/main.py

FastAPI control-plane entry point for Orchapod.ai.
Handles: workflow CRUD, run lifecycle, live log streaming, internal container webhooks.

Start: uvicorn api.main:app --reload
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from time import monotonic

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api import config, database
from api.database import AsyncSessionLocal, create_tables
from api.executor.run_workflow import sweep
from api.services import storage
from api.services.events import event_bus
from api.routes import agent, compare, workflows, runs, models, internal, ws, inference, model_registry, artifacts
from packages.providers.vastai import register_providers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await create_tables()
    await event_bus.connect()
    async with AsyncSessionLocal() as db:
        await sweep(db)  # runs a restart left mid-flight fail; their pods are terminated
    await internal.resume_ttls()  # endpoints past their expiry are deleted; the others get their timers back
    # MinIO in dev starts without the bucket; off the event loop, so a slow or absent store never delays startup
    asyncio.get_running_loop().run_in_executor(None, storage.ensure_bucket_exists)

    register_providers(vastai_key=config.env("VASTAI_API_KEY"))

    yield
    # Shutdown
    await event_bus.disconnect()


app = FastAPI(
    title="Orchapod API",
    description="Control plane for the Orchapod.ai LLM fine-tuning platform.",
    version="0.1.0",
    lifespan=lifespan,
)


def cors() -> dict:
    """CORSMiddleware options from ORCHAPOD_CORS_ORIGINS: exact origins, comma-separated; blank = this machine's pages on
    any port (`next dev` moves to 3001 when 3000 is taken). No credentials: the web app sends none, so a `*` never
    comes with them."""
    origins = [o.strip() for o in config.env("ORCHAPOD_CORS_ORIGINS").split(",") if o.strip()]
    return {"allow_origins": origins, "allow_methods": ["*"], "allow_headers": ["*"], "expose_headers": ["Retry-After"],
            "allow_origin_regex": None if origins else r"https?://(localhost|127\.0\.0\.1)(:\d+)?"}


app.add_middleware(CORSMiddleware, **cors())

# REST routes
app.include_router(workflows.router,       prefix="/workflows", tags=["workflows"])
app.include_router(runs.router,            prefix="/runs",      tags=["runs"])
app.include_router(models.router,          prefix="/registry",  tags=["registry"])
app.include_router(model_registry.router,  prefix="/models",    tags=["models"])
app.include_router(internal.router,        prefix="/internal",  tags=["internal"])
app.include_router(inference.router,       prefix="/inference", tags=["inference"])
app.include_router(artifacts.router,       prefix="/artifacts", tags=["artifacts"])
app.include_router(agent.router,           prefix="/agent",     tags=["agent"])
app.include_router(compare.router,         prefix="/compare",   tags=["compare"])

# WebSocket
app.include_router(ws.router, tags=["websocket"])


log = logging.getLogger("api.health")
HEALTH_TIMEOUT_S, HEALTH_TTL_S = 3, 10
_health: tuple[float, asyncio.Task] | None = None  # (when the last deep check started, that check)


async def _answers(name: str, check) -> bool:
    try:
        await asyncio.wait_for(check(), HEALTH_TIMEOUT_S)
        return True
    except Exception as e:  # down, refused, or slower than HEALTH_TIMEOUT_S; the cause goes to the log only
        log.warning("health: %s failed: %r", name, e)
        return False


async def _database() -> None:
    async with database.engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _failed() -> list[str]:
    checks = {"database": _database, "redis": lambda: event_bus.redis.ping(),
              "storage": lambda: asyncio.to_thread(storage.head_bucket)}
    up = await asyncio.gather(*(_answers(name, check) for name, check in checks.items()))
    return [name for name, ok in zip(checks, up) if not ok]


@app.get("/health")
async def health():
    """Deep: the database, Redis and object storage each answer within HEALTH_TIMEOUT_S, else 503 names the ones that
    did not. For uptime monitors and people; the watchdog restarts on /livez, since a restart fixes none of these.
    Concurrent callers share one check and its result is reused for HEALTH_TTL_S, so a flood of probes cannot pin the
    executor's threads while storage is slow."""
    global _health
    if _health is None or monotonic() - _health[0] >= HEALTH_TTL_S:
        _health = (monotonic(), asyncio.ensure_future(_failed()))
    failed = await asyncio.shield(_health[1])  # a caller that hangs up leaves the check to the others
    if failed:
        return JSONResponse(status_code=503, content={"status": "fail", "failed": failed})
    return {"status": "ok"}


@app.get("/livez")
async def livez():
    """Shallow: the process answers (the watchdog's and the container healthcheck's probe)."""
    return {"status": "ok"}
