"""Budget guard per contracts "Budget guard", R6 (control-plane day ledger) and R7 (anonymous scale)."""

from __future__ import annotations

import asyncio
import threading
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from api.executor import run_workflow as ex
from api.models.db import NodeRun, NodeStatus, RunStatus, Spend, utcnow
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from api.services import budget
from tests.api.test_executor import FakeProvider, drain, launched, nodes, provider, seed  # noqa: F401 (fixtures)

ADMIN = {"X-Orchapod-Admin": "s3cret"}


@pytest.fixture(autouse=True)
def caps(monkeypatch):
    for k in ("ORCHAPOD_MAX_RUN_USD", "ORCHAPOD_MAX_DAY_USD", "ORCHAPOD_KILL_SWITCH", "ORCHAPOD_ANON_SCALE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ORCHAPOD_ADMIN_TOKEN", "s3cret")


def test_only_the_admin_token_lifts_the_anonymous_scale(monkeypatch):
    assert budget.scale("s3cret") == budget.scale(" s3cret ") == 1.0
    assert budget.scale("") == budget.scale("nope") == 0.1
    monkeypatch.setenv("ORCHAPOD_ANON_SCALE", "0.5")
    assert budget.scale("nope") == 0.5
    for blank in ("", "  "):  # a blank token is unset: everyone is anonymous, even with a blank header
        monkeypatch.setenv("ORCHAPOD_ADMIN_TOKEN", blank)
        assert budget.scale("") == budget.scale(blank) == 0.5


def test_kill_switch_is_on_for_anything_but_zero(monkeypatch):
    assert not budget.kill_switch()
    for value, on in (("0", False), ("", False), ("1", True), ("true", True)):
        monkeypatch.setenv("ORCHAPOD_KILL_SWITCH", value)
        assert budget.kill_switch() is on


async def test_left_is_the_smaller_of_run_and_day(db):
    run = await seed(db, cost_usd=Decimal("1.0"))
    assert await budget.left(db, run, 1.0) == (pytest.approx(2.0), "run", 3.0)        # $3 run cap
    await seed(db, cost_usd=Decimal("13.5"))
    await seed(db, cost_usd=Decimal("9"), created_at=utcnow() - timedelta(days=1))    # yesterday's
    assert await budget.left(db, run, 1.0) == (pytest.approx(0.5), "day", 15.0)       # $15 day cap
    db.add(Spend(source="planner", usd=Decimal("0.25")))                                # control plane (R6)
    await db.commit()
    assert await budget.left(db, run, 1.0) == (pytest.approx(0.25), "day", 15.0)
    assert (await budget.left(db, None, 0.1))[1:] == ("day", pytest.approx(1.5))        # anonymous: caps x 0.1


async def test_control_plane_spend_from_worker_threads_lands_in_the_ledger(db):
    def burst(tf):  # on_usage fires on worker threads (to_thread, Starlette's threadpool)
        def bill():
            for _ in range(1000):
                tf.on_usage("token_factory", "m", 10, 10, usd=0.001)
        threads = [threading.Thread(target=bill) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return "plan"

    assert await budget.control_plane(db, "planner", burst) == "plan"
    assert await budget.spent_today(db) == pytest.approx(8.0)


async def test_control_plane_spend_is_recorded_when_the_call_fails(db):
    def billed_then_failed(tf):
        tf.on_usage("token_factory", "m", 100, 4096, usd=0.004)  # TF bills before the reply is parsed
        raise ValueError("bad_output")

    with pytest.raises(ValueError):
        await budget.control_plane(db, "reporter", billed_then_failed)
    assert await budget.spent_today(db) == pytest.approx(0.004)


# --- routes and executor --------------------------------------------------------

async def test_start_and_retry_refuse_when_killed_or_over_budget(client, db, monkeypatch, launched):
    pending = await seed(db, status=RunStatus.PENDING)
    failed = await seed(db, status=RunStatus.FAILED, cost_usd=Decimal("0.5"))
    db.add(NodeRun(run_id=failed.id, node_id="a", node_type="data-prep", status=NodeStatus.FAILED, error="exit 1"))
    await db.commit()

    monkeypatch.setenv("ORCHAPOD_KILL_SWITCH", "1")
    assert (await client.post(f"/runs/{pending.id}/start", headers=ADMIN)).status_code == 503
    assert (await client.post(f"/runs/{failed.id}/nodes/a/retry", headers=ADMIN)).status_code == 503
    monkeypatch.delenv("ORCHAPOD_KILL_SWITCH")

    r = await client.post(f"/runs/{failed.id}/nodes/a/retry")  # anonymous: $0.30 run cap, $0.50 spent
    assert r.status_code == 402 and "run cap $0.3" in r.json()["detail"]
    db.add(Spend(source="compare", usd=Decimal("15")))  # the day's budget is gone
    await db.commit()
    assert (await client.post(f"/runs/{pending.id}/start", headers=ADMIN)).status_code == 402
    assert launched == []


async def test_the_executor_runs_with_the_callers_caps(client, db, provider, launched):
    anon, admin = await seed(db, status=RunStatus.PENDING), await seed(db, status=RunStatus.PENDING)
    provider.script = {"a": {"exit": 1}}

    await client.post(f"/runs/{anon.id}/start")
    await asyncio.wait_for(launched[-1], 5)
    assert provider.envs["a"]["ORCHAPOD_MAX_COST_USD"] == "0.3000"   # $3 x 0.1
    await client.post(f"/runs/{admin.id}/start", headers=ADMIN)
    await asyncio.wait_for(launched[-1], 5)
    assert provider.envs["a"]["ORCHAPOD_MAX_COST_USD"] == "3.0000"


async def test_every_node_boundary_checks_budget_and_kill_switch(db, provider, monkeypatch):
    spent = await seed(db, cost_usd=Decimal("3"))
    await ex.run_workflow(spent.id, db, AsyncMock(), 1.0)
    assert (await nodes(db, spent))["a"].error == "budget: run cap $3 reached"

    monkeypatch.setenv("ORCHAPOD_KILL_SWITCH", "1")
    killed = await seed(db)
    await ex.run_workflow(killed.id, db, AsyncMock(), 1.0)
    assert (await nodes(db, killed))["a"].error == "kill switch"
    assert provider.provisioned == []


async def concurrent_first_nodes(db, provider, n):
    """n runs at once, each first node kept running: returns their runs and executor tasks once every run holds
    its node's grant or has stopped at the boundary."""
    provider.script = {"a": {"exit": None}}
    runs = [await seed(db) for _ in range(n)]
    sessions = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)

    async def execute(run):
        async with sessions() as s:
            await ex.run_workflow(run.id, s, AsyncMock(), 1.0)

    tasks = [asyncio.create_task(execute(r)) for r in runs]
    for _ in range(500):
        if len(provider.granted) + sum(t.done() for t in tasks) == len(runs):
            break
        await asyncio.sleep(0.01)
    return runs, tasks


async def stop(tasks):
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await drain()
    assert budget._granted == {}  # each node's grant goes with its container


async def test_concurrent_runs_never_grant_more_than_the_day_cap(db, provider, monkeypatch):
    monkeypatch.setenv("ORCHAPOD_MAX_DAY_USD", "1")
    runs, tasks = await concurrent_first_nodes(db, provider, 5)

    assert sum(provider.granted) <= 1.0 and provider.granted  # one day cap, however many nodes run at once
    errors = [(await nodes(db, r))["a"].error for r in runs]
    assert errors.count("budget: day cap $1 reached") == len(runs) - len(provider.granted)
    await stop(tasks)


async def test_grants_of_several_runs_add_up_to_the_day_cap(db, provider, monkeypatch):
    monkeypatch.setenv("ORCHAPOD_MAX_RUN_USD", "1")
    monkeypatch.setenv("ORCHAPOD_MAX_DAY_USD", "2.5")
    runs, tasks = await concurrent_first_nodes(db, provider, 4)

    # $1 each while the day has room, then the $0.50 the others' grants leave, then nothing
    assert sorted(provider.granted) == [0.5, 1.0, 1.0]
    errors = [(await nodes(db, r))["a"].error for r in runs]
    assert errors.count("budget: day cap $2.5 reached") == 1
    await stop(tasks)


async def test_an_admin_run_in_flight_never_blocks_anonymous_callers(client, db, provider, launched):
    provider.script = {"a": {"exit": None}}  # first nodes keep running
    admin, anon = await seed(db, status=RunStatus.PENDING), await seed(db, status=RunStatus.PENDING)

    assert (await client.post(f"/runs/{admin.id}/start", headers=ADMIN)).status_code == 200
    await asyncio.wait_for(provider.started.wait(), 5)  # its node holds the run's whole $3
    assert (await client.post(f"/runs/{anon.id}/start")).status_code == 200  # anonymous: $0.30 run, $1.50 of the day
    for _ in range(500):
        if len(provider.granted) == 2:
            break
        await asyncio.sleep(0.01)
    assert provider.granted == [3.0, 0.3]
    await stop(launched)


async def test_a_grant_counts_against_the_whole_day_and_only_its_own_scales_share(db, monkeypatch):
    monkeypatch.setenv("ORCHAPOD_MAX_DAY_USD", "4")
    monkeypatch.setenv("ORCHAPOD_ANON_SCALE", "0.5")  # anonymous: $1.50 run cap and a $2 share of the day
    admin, a1, a2, admin2 = [await seed(db) for _ in range(4)]

    assert await budget.reserve(db, admin, 1.0) == (pytest.approx(3.0), "run", 3.0)
    assert await budget.reserve(db, a1, 0.5) == (pytest.approx(1.0), "day", 4.0)  # the admin's $3 left the day $1
    assert await budget.reserve(db, a2, 0.5) == (pytest.approx(0.0), "day", 4.0)  # the day is full
    budget.release(admin.id)
    assert await budget.reserve(db, a2, 0.5) == (pytest.approx(1.0), "day", 2.0)  # anonymous grants fill the share
    assert await budget.left(db, admin2, 1.0) == (pytest.approx(2.0), "day", 4.0)  # an admin counts every grant
