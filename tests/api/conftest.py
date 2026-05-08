"""
tests/api/conftest.py

Shared fixtures for API route tests.
Uses an in-memory SQLite database to avoid requiring PostgreSQL in CI.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Set required env vars before importing the app
os.environ.setdefault("DATABASE_URL",          "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ORCHAPOD_R2_ENDPOINT",  "https://r2.example.com")
os.environ.setdefault("ORCHAPOD_R2_ACCESS_KEY", "test-key")
os.environ.setdefault("ORCHAPOD_R2_SECRET_KEY", "test-secret")
os.environ.setdefault("ORCHAPOD_CONTROL_URL",  "http://localhost:8000")


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


@pytest_asyncio.fixture
async def client(db):
    """AsyncClient wired to the FastAPI app with get_db overridden."""
    from api.main import app
    from api.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db

    with patch("api.main.register_providers"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_node_run(db):
    """A Run + NodeRun in RUNNING state, ready for internal webhook tests."""
    from api.models.db import NodeRun, NodeStatus, Run, RunStatus

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
