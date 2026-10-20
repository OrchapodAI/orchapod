"""
tests/api/conftest.py

Shared fixtures for API route tests.
Uses an in-memory SQLite database to avoid requiring PostgreSQL in CI.
Never patch asyncio.create_task by hand: the `no_bg_tasks` fixture closes the coroutine it is handed,
so pytest stays free of "coroutine ... was never awaited".
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Set required env vars before importing the app
os.environ.setdefault("DATABASE_URL",           "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ORCHAPOD_R2_ENDPOINT",   "https://r2.example.com")
os.environ.setdefault("ORCHAPOD_R2_ACCESS_KEY", "test-key")
os.environ.setdefault("ORCHAPOD_R2_SECRET_KEY", "test-secret")
os.environ.setdefault("ORCHAPOD_CONTROL_URL",   "http://localhost:8000")

# Import all DB models so SQLModel.metadata is populated BEFORE create_all runs.
# Without this import, SQLModel.metadata has no tables registered at the time
# the db fixture calls create_all, so no tables are created.
from api.models.db import (  # noqa: F401
    Run, NodeRun, Artifact, Model, Workflow,
    RunStatus, NodeStatus, ArtifactKind, ModelFormat,
)


@pytest_asyncio.fixture
async def db():
    """In-memory SQLite session, tables created fresh per test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _clear_ttl_tasks():
    """Cancel and drop TTL tasks at teardown: api.routes.internal._ttl_tasks is module-global."""
    yield
    from api.routes import internal

    tasks = [t for t in internal._ttl_tasks.values() if isinstance(t, asyncio.Task)]
    internal._ttl_tasks.clear()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.fixture
def no_bg_tasks():
    """Use instead of patch("asyncio.create_task"): the coroutine is closed, so it can't warn 'never awaited'."""

    def drop(coro, **_):
        coro.close()
        return MagicMock()

    with patch("asyncio.create_task", drop):
        yield


@pytest_asyncio.fixture
async def client(db):
    """AsyncClient wired to the FastAPI app with get_db and get_session overridden."""
    from unittest.mock import AsyncMock
    from api.main import app
    from api.database import get_db, get_session
    from api.routes.internal import INTERNAL_SECRET

    async def override_db():
        yield db
        # Mimic get_session's auto-commit so route changes are visible to the test
        await db.flush()

    # Override both dependency names — some routes use get_db, others get_session
    app.dependency_overrides[get_db]      = override_db
    app.dependency_overrides[get_session] = override_db

    with patch("api.main.register_providers"), \
         patch("api.services.events.event_bus.publish", new=AsyncMock(return_value=None)):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test",
            headers={"X-Orchapod-Secret": INTERNAL_SECRET},  # /internal/* is never open (R2)
        ) as ac:
            yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_node_run(db):
    """A Run + NodeRun in RUNNING state, ready for internal webhook tests."""
    run = Run(
        user_id=uuid.uuid4(),
        status=RunStatus.RUNNING,
        gpu_provider="vastai",
        gpu_pod_id="12345678",
    )
    db.add(run)
    await db.flush()

    node_run = NodeRun(
        run_id=run.id,
        node_id="node",
        node_type="vllm-serve",
        status=NodeStatus.RUNNING,
        started_at=datetime.utcnow(),
        inputs={"model": "Qwen/Qwen3-4B-Instruct"},
        gpu_provider="vastai",
        gpu_pod_id="12345678",
    )
    db.add(node_run)
    await db.commit()
    await db.refresh(run)
    await db.refresh(node_run)

    return run, node_run
