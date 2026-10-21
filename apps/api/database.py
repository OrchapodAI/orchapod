"""
apps/api/database.py

Async database engine and session management.
Supports PostgreSQL (production) and SQLite (tests/dev).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlmodel import SQLModel

from api import config

DATABASE_URL = config.env("DATABASE_URL")

# pool_size / max_overflow are not valid kwargs for SQLite
_pool_kwargs = (
    {}
    if DATABASE_URL.startswith("sqlite")
    else {"pool_size": 10, "max_overflow": 20, "pool_pre_ping": True}
)

engine = create_async_engine(DATABASE_URL, echo=False, **_pool_kwargs)


def sqlite_wal(dbapi_connection, _record) -> None:
    """SQLite (dev, tests, the stub e2e) in WAL mode, where readers never block a writer. A cancel that cuts off a read while
    its rows are fetched leaves it open (sqlite3 closes the connection only once the cursor is gone), and in the default
    journal mode its lock failed every commit for 5 s with "database is locked", the executor's record of the cancel
    included (qa-w6)."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


if DATABASE_URL.startswith("sqlite"):
    event.listen(engine.sync_engine, "connect", sqlite_wal)

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
