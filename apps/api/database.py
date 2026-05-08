"""
apps/api/database.py

Async SQLAlchemy engine + session factory used by all API routes.
"""
from __future__ import annotations

import os

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

_db_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./orchapod_dev.db")

# pool_size / max_overflow are not valid for SQLite
_pool_kwargs = (
    {}
    if _db_url.startswith("sqlite")
    else {"pool_size": 10, "max_overflow": 20}
)

engine = create_async_engine(_db_url, echo=False, **_pool_kwargs)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
