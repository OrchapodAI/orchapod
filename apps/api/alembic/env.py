"""
apps/api/alembic/env.py

Alembic migration environment — async SQLAlchemy + SQLModel autogenerate.
Reads DATABASE_URL from the environment (same var the API uses).
"""

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

# Make api.* and packages.* importable when running alembic from any directory
sys.path.insert(0, str(Path(__file__).parents[3]))  # repo root
sys.path.insert(0, str(Path(__file__).parents[2]))  # apps/

# Import every model module so SQLModel.metadata has all table definitions
import api.models.db  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata


def get_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set.")
    return url


# ---------------------------------------------------------------------------
# Offline — emit raw SQL without a live connection (useful for review/CI)
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online — connect and apply migrations
# ---------------------------------------------------------------------------

def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_url(), echo=False)
    async with engine.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
