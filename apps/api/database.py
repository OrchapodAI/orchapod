"""
apps/api/database.py

Async SQLAlchemy engine + session factory.
All DB access in the API goes through get_db().
"""

import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

engine = create_async_engine(
    os.environ["DATABASE_URL"],
    echo=False,
    pool_size=10,
    max_overflow=20,
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields a DB session per request."""
    async with SessionLocal() as session:
        yield session
