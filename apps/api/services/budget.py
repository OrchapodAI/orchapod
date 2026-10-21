"""
apps/api/services/budget.py

Budget guard (docs/contracts.md "Budget guard", R6, R7): per-run and per-UTC-day caps, the kill switch,
the anonymous scale, and the day ledger of control-plane spend (planner, reporter, /compare).
"""

from __future__ import annotations

import asyncio
import os
import secrets
import uuid
from decimal import Decimal
from typing import Callable

from fastapi import Header, HTTPException
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api.models.db import Run, Spend, utcnow
from packages.providers.tokenfactory import TokenFactory

# run_id → what its running node may spend, granted at the node boundary and released when the node ends, so
# concurrent runs never hand out the same dollars twice. ponytail: in-process, which the one API worker allows.
_granted: dict[uuid.UUID, float] = {}


def scale(x_orchapod_admin: str = Header(default="")) -> float:
    """FastAPI dependency: 1 for a caller sending X-Orchapod-Admin: $ORCHAPOD_ADMIN_TOKEN, else
    ORCHAPOD_ANON_SCALE (R7). A blank token is unset, so then everyone is anonymous."""
    token = (os.environ.get("ORCHAPOD_ADMIN_TOKEN") or "").strip()
    if token and secrets.compare_digest(x_orchapod_admin.strip().encode(), token.encode()):
        return 1.0
    return float(os.environ.get("ORCHAPOD_ANON_SCALE") or 0.1)


def kill_switch() -> bool:
    """ORCHAPOD_KILL_SWITCH: anything but blank or 0 is on, so a typo fails safe."""
    return (os.environ.get("ORCHAPOD_KILL_SWITCH") or "0").strip() != "0"


async def spent_today(db: AsyncSession) -> float:
    """UTC-day spend: Run.cost_usd of the runs created today plus today's control-plane ledger."""
    day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    runs = await db.scalar(select(func.sum(Run.cost_usd)).where(Run.created_at >= day))
    ledger = await db.scalar(select(func.sum(Spend.usd)).where(Spend.created_at >= day))
    return float(runs or 0) + float(ledger or 0)


async def left(db: AsyncSession, run: Run | None, scale: float) -> tuple[float, str, float]:
    """(budget left, the cap that binds: "run" | "day", that cap in $); both caps × scale. The day's budget left
    also excludes what other runs' running nodes were granted."""
    run_cap = float(os.environ.get("ORCHAPOD_MAX_RUN_USD") or 3) * scale
    day_cap = float(os.environ.get("ORCHAPOD_MAX_DAY_USD") or 15) * scale
    granted = dict(_granted)  # a node that ends while spend is read stays counted: its cost commits before release
    if run is not None:
        await db.refresh(run)  # Run.cost_usd grows as nodes register cost_json
    spent = await spent_today(db)
    granted.update(_granted)  # no await from here to reserve()'s write, so two boundaries never share a grant
    granted.pop(run.id if run is not None else None, None)
    run_left = run_cap - (float(run.cost_usd or 0) if run is not None else 0.0)
    day_left = day_cap - spent - sum(granted.values())
    return (run_left, "run", run_cap) if run_left <= day_left else (day_left, "day", day_cap)


async def reserve(db: AsyncSession, run: Run, scale: float) -> tuple[float, str, float]:
    """left() for the run's next node, granted to it until release(run.id)."""
    amount, which, cap = await left(db, run, scale)
    if amount > 0:
        _granted[run.id] = amount
    return amount, which, cap


def release(run_id: uuid.UUID) -> None:
    _granted.pop(run_id, None)


async def guard(db: AsyncSession, scale: float, run: Run | None = None, need: float = 0.0) -> None:
    """503 while the kill switch is on; 402 when nothing is left, or less than `need` (a plan's estimate)."""
    if kill_switch():
        raise HTTPException(status_code=503, detail="the kill switch is on (ORCHAPOD_KILL_SWITCH)")
    amount, which, cap = await left(db, run, scale)
    if amount <= 0 or need > amount:
        raise HTTPException(status_code=402, detail=f"{which} cap ${cap:g}: ${max(amount, 0):.2f} left"
                                                     + (f", the plan needs ${need:.2f}" if need else ""))


async def control_plane(db: AsyncSession, source: str, call: Callable[[TokenFactory], dict]) -> dict:
    """Run one sync Token Factory call in a worker thread; whatever it bills goes into today's ledger,
    also when the call then fails (TF bills before the reply is parsed)."""
    usage: list[float] = []  # on_usage runs on the worker thread; list.append is atomic
    tf = TokenFactory(on_usage=lambda *_, usd=None, **__: usage.append(usd or 0.0))
    try:
        return await asyncio.to_thread(call, tf)
    finally:
        if usage:
            db.add(Spend(source=source, usd=Decimal(str(round(sum(usage), 6)))))
            await db.commit()
