"""
apps/api/database.py

Async SQLAlchemy engine + session factory.
All DB access in the API goes through get_db().
"""

import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

_db_url = os.environ["DATABASE_URL"]
_pool_kwargs = {} if _db_url.startswith("sqlite") else {"pool_size": 10, "max_overflow": 20}

engine = create_async_engine(_db_url, echo=False, **_pool_kwargs)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields a DB session per request."""
    async with SessionLocal() as session:
        yield session
