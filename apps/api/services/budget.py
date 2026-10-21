"""
apps/api/services/budget.py

Budget guard (docs/contracts.md "Budget guard", R6, R7): per-run and per-UTC-day caps, the kill switch,
the anonymous scale, and the day ledger of control-plane spend (planner, reporter, /compare).
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Callable

from fastapi import Header, HTTPException
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from api import config
from api.models.db import Artifact, Run, Spend, utcnow
from packages.providers.tokenfactory import TokenFactory

# run_id → (what its running node may spend, the scale it was granted at), granted at the node boundary and released
# when the node ends, so concurrent runs never hand out the same dollars twice. ponytail: in-process, which the one API
# worker allows.
_granted: dict[uuid.UUID, tuple[float, float]] = {}


# A node's cost_json and the executor's wall-time bill of the same attempt never interleave. ponytail: in-process, which
# the one API worker allows.
cost_lock = asyncio.Lock()


def attempt_cost(metas: list[dict]) -> float:
    """What one attempt of a node costs, from its cost_json metas (contracts "Run state machine"): what the node
    reported (a seq counts once, at its largest: a re-send after a broken POST), or the executor's wall-time bill of
    its gpu pod when that is more."""
    walls = [float(m.get("wall_usd", 0)) for m in metas if m.get("billed_by") == "executor"]
    seqs, reported = {}, 0.0
    for m in metas:
        if m.get("billed_by") != "executor":
            usd = float(m.get("reported_usd", m.get("usd", 0)))
            if isinstance(m.get("seq"), int):
                seqs[m["seq"]] = max(seqs.get(m["seq"], 0.0), usd)
            else:
                reported += usd
    return max([reported + sum(seqs.values()), *walls])


async def attempt_costs(db: AsyncSession, node_run) -> list[dict]:
    """The metas of the cost_json rows of the node's current attempt (a retry restarts started_at)."""
    return [m or {} for m in await db.scalars(select(Artifact.meta).where(
        Artifact.node_run_id == node_run.id, Artifact.name == "cost_json",
        Artifact.created_at >= (node_run.started_at or datetime.min)))]


def admin(x_orchapod_admin: str = Header(default="")) -> bool:
    """FastAPI dependency: the caller sent X-Orchapod-Admin: $ORCHAPOD_ADMIN_TOKEN (R7). A blank token is unset, so then
    nobody is the admin, whatever ORCHAPOD_ANON_SCALE gives the public."""
    token = config.env("ORCHAPOD_ADMIN_TOKEN").strip()
    return bool(token) and secrets.compare_digest(x_orchapod_admin.strip().encode(), token.encode())


def scale(x_orchapod_admin: str = Header(default="")) -> float:
    """FastAPI dependency: 1 for the admin, else ORCHAPOD_ANON_SCALE (R7)."""
    return 1.0 if admin(x_orchapod_admin) else float(config.env("ORCHAPOD_ANON_SCALE"))


def kill_switch() -> bool:
    """ORCHAPOD_KILL_SWITCH: anything but blank or 0 is on, so a typo fails safe."""
    return config.env("ORCHAPOD_KILL_SWITCH").strip() != "0"


async def spent_today(db: AsyncSession) -> float:
    """UTC-day spend: Run.cost_usd of the runs created today plus today's control-plane ledger."""
    day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    runs = await db.scalar(select(func.sum(Run.cost_usd)).where(Run.created_at >= day))
    ledger = await db.scalar(select(func.sum(Spend.usd)).where(Spend.created_at >= day))
    return float(runs or 0) + float(ledger or 0)


def run_cap(scale: float) -> float:
    """ORCHAPOD_MAX_RUN_USD × the caller's scale."""
    return float(config.env("ORCHAPOD_MAX_RUN_USD")) * scale


async def left(db: AsyncSession, run: Run | None, scale: float) -> tuple[float, str, float]:
    """(budget left, the cap that binds: "run" | "day", that cap in $) for a caller at `scale`: the least of the run cap
    × scale less the run's cost, and of the caller's share of the day (day cap × scale) and the whole day cap, both less
    the day's spend. Other runs' running nodes' grants count against the whole day, and against the share only when
    granted at this scale or below: an admin node's grant never blocks anonymous callers, though admin spend does
    (contracts "Budget guard"; operating rule: no admin runs on the hosted instance)."""
    run_max, day = run_cap(scale), float(config.env("ORCHAPOD_MAX_DAY_USD"))
    granted = dict(_granted)  # a node that ends while spend is read stays counted: its cost commits before release
    if run is not None:
        await db.refresh(run)  # Run.cost_usd grows as nodes register cost_json
    spent = await spent_today(db)
    granted.update(_granted)  # no await from here to reserve()'s write, so two boundaries never share a grant
    granted.pop(run.id if run is not None else None, None)
    run_left = run_max - (float(run.cost_usd or 0) if run is not None else 0.0)
    share = day * scale - spent - sum(usd for usd, at in granted.values() if at <= scale)
    whole = day - spent - sum(usd for usd, _ in granted.values())
    return min((run_left, "run", run_max), (share, "day", day * scale), (whole, "day", day), key=lambda x: x[0])


async def reserve(db: AsyncSession, run: Run, scale: float) -> tuple[float, str, float]:
    """left() for the run's next node, granted to it at the caller's scale until release(run.id).
    ponytail: a node still reserves its run's whole remaining budget, and spend (not grants) counts against every
    share, so an admin who has spent the anonymous share of the day has used it up; a separate anonymous pot needs
    spend tagged by caller."""
    amount, which, cap = await left(db, run, scale)
    if amount > 0:
        _granted[run.id] = (amount, scale)
    return amount, which, cap


def release(run_id: uuid.UUID) -> None:
    _granted.pop(run_id, None)


def gpu_nodes(types) -> list[str]:
    """The node types among `types` that rent a GPU: runtime gpu (a Serverless Job) or `rents_gpu` (an api node such as
    vllm-serve that creates a GPU endpoint, billed from creation). Where a node runs still reads `runtime` alone."""
    from packages.workflow_schema.models import NODE_REGISTRY
    return sorted({t for t in types if NODE_REGISTRY.get(t, {}).get("runtime") == "gpu"
                   or NODE_REGISTRY.get(t, {}).get("rents_gpu")})


def gpu_guard(types, scale: float) -> None:
    """403 when an anonymous caller (scale < 1) would start a gpu node: rented GPU time bills from provisioning, by the
    hour, whatever the node's ORCHAPOD_MAX_COST_USD, so on the public app only the admin starts one."""
    if scale < 1 and (gpu := gpu_nodes(types)):
        raise HTTPException(status_code=403, detail=f"{', '.join(gpu)} runs on a rented GPU, billed by the hour: "
                                                    "only the admin can start it on the public app")


async def guard(db: AsyncSession, scale: float, run: Run | None = None, need: float = 0.0) -> None:
    """503 while the kill switch is on; 402 when nothing is left, or less than `need` (a plan's estimate)."""
    if kill_switch():
        raise HTTPException(status_code=503, detail="the kill switch is on (ORCHAPOD_KILL_SWITCH)")
    amount, which, cap = await left(db, run, scale)
    if amount <= 0 or need > amount:
        raise HTTPException(status_code=402, detail=f"{which} cap ${cap:g}: ${max(amount, 0):.2f} left"
                                                     + (f", the plan needs ${need:.2f}" if need else ""))


def meter(usage: list[float]) -> Callable:
    """An on_usage hook that appends each call's $ to `usage`; it runs on worker threads, and list.append is atomic."""
    return lambda *_, usd=None, **__: usage.append(usd or 0.0)


async def record(db: AsyncSession, source: str, usd: float) -> None:
    """One row of control-plane spend in today's ledger (R6)."""
    db.add(Spend(source=source, usd=Decimal(str(round(usd, 6)))))
    await db.commit()


async def control_plane(db: AsyncSession, source: str, call: Callable[[TokenFactory], dict]) -> dict:
    """Run one sync Token Factory call in a worker thread; whatever it bills goes into today's ledger,
    also when the call then fails (TF bills before the reply is parsed)."""
    usage: list[float] = []
    try:
        return await asyncio.to_thread(call, TokenFactory(on_usage=meter(usage)))
    finally:
        if usage:
            await record(db, source, sum(usage))
