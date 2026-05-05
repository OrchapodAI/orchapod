"""
API test fixtures.

Uses SQLite in-memory instead of PostgreSQL so tests run without
docker-compose. The get_db dependency is overridden per-test so routes
hit the test DB, not the module-level engine.
"""

import os
import uuid

# Must be set before any api.* imports so database.py creates a SQLite engine
os.environ.setdefault("DATABASE_URL",           "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ORCHAPOD_R2_ENDPOINT",   "http://localhost:9000")
os.environ.setdefault("ORCHAPOD_R2_ACCESS_KEY", "testkey")
os.environ.setdefault("ORCHAPOD_R2_SECRET_KEY", "testsecret")
os.environ.setdefault("ORCHAPOD_CONTROL_URL",   "http://localhost:8000")

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from unittest.mock import patch

from api.main import app
from api.database import get_db
from api.models.db import NodeRun, NodeStatus, Run, RunStatus


@pytest.fixture
async def db():
    """Fresh in-memory SQLite session per test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def client(db):
    """Test HTTP client with DB overridden and GPU providers mocked."""
    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override

    with patch("api.main.register_providers"):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def seeded_node_run(db):
    """A Run + NodeRun in RUNNING state for testing internal routes."""
    run = Run(user_id=uuid.uuid4(), status=RunStatus.RUNNING)
    db.add(run)
    await db.flush()

    node_run = NodeRun(
        run_id=run.id,
        node_id="node",
        node_type="vllm-serve",
        status=NodeStatus.RUNNING,
        inputs={"model": "Qwen/Qwen3-4B-Instruct"},
        gpu_pod_id="pod-abc",
        gpu_provider="runpod",
    )
    db.add(node_run)
    await db.commit()
    await db.refresh(run)
    await db.refresh(node_run)
    return run, node_run
