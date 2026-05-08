"""
apps/api/database.py

Async database engine and session management (PostgreSQL 16 via asyncpg).
All tables defined in models/db.py — SQLModel handles both Pydantic + SQLAlchemy.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlmodel import SQLModel


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://orchapod:orchapod_dev@localhost:5432/orchapod",
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def create_tables() -> None:
    """Create all tables defined via SQLModel metadata. Called at startup."""
    # Import models so SQLModel registers them before create_all
    import api.models.db  # noqa: F401
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
