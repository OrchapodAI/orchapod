"""
apps/api/database.py

Async database engine and session management.
Supports PostgreSQL (production) and SQLite (tests/dev).
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlmodel import SQLModel


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./orchapod_dev.db",
)

# pool_size / max_overflow are not valid kwargs for SQLite
_pool_kwargs = (
    {}
    if DATABASE_URL.startswith("sqlite")
    else {"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True}
)

engine = create_async_engine(DATABASE_URL, echo=False, **_pool_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Alias used by older routes
SessionLocal = AsyncSessionLocal


async def create_tables() -> None:
    """Create all tables defined via SQLModel metadata. Called at startup."""
    import api.models.db  # noqa: F401 — registers models before create_all
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields an async DB session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Alias used by older routes
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
