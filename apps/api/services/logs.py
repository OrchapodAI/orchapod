"""
apps/api/services/logs.py

The log lines a run keeps (contracts "Run control API"): POST /internal/log stores each line it accepts, and seeding the
golden run stores the lines of its fixture's `logs` artifacts. Both go through clean() and keep(), so a seeded run is cut,
redacted and trimmed exactly like a live one.
"""

from __future__ import annotations

import uuid
from typing import Iterable

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.models.db import NodeLog
from api.services.redact import redact_text

LOG_MAX, LOG_KEEP = 2000, 5000  # chars of a stored line; lines kept per run


def clean(text: str) -> str:
    """A line as it is stored, broadcast and kept as a node's error: R22-redacted, at most LOG_MAX chars, and fit for the
    database (Postgres refuses NUL, and no database takes a lone surrogate, which a node that decodes bytes with
    surrogateescape sends: NUL is dropped, a lone surrogate becomes "?"). Cut first, so the regex never reads a huge line,
    and again: "[redacted]" can be longer than the value it replaces."""
    return redact_text(text[:LOG_MAX].replace("\x00", "").encode("utf-8", "replace").decode())[:LOG_MAX]


async def keep(db: AsyncSession, run_id: uuid.UUID, lines: Iterable[tuple[str, str, str, str]]) -> None:
    """Add (node_id, ts, level, message) lines, already clean(), to the run's log, oldest first, and delete all but its
    last LOG_KEEP. The caller commits."""
    db.add_all(NodeLog(run_id=run_id, node_id=node_id, ts=ts, level=level, message=message)
               for node_id, ts, level, message in lines)
    drop = await db.scalar(select(NodeLog.id).where(NodeLog.run_id == run_id)
                           .order_by(NodeLog.id.desc()).offset(LOG_KEEP).limit(1))  # the newest line beyond the last LOG_KEEP
    if drop is not None:
        await db.execute(delete(NodeLog).where(NodeLog.run_id == run_id, NodeLog.id <= drop)
                         .execution_options(synchronize_session=False))
