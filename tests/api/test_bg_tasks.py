"""The tests/api fixtures that keep background tasks from outliving, or never running in, a test."""

import asyncio
import inspect

from api.routes import internal

_left_behind: list[asyncio.Task] = []


async def test_no_bg_tasks_closes_the_coroutine_it_is_handed(no_bg_tasks):
    async def job():
        pass

    coro = job()
    asyncio.create_task(coro)

    # CORO_CREATED here is what later surfaces as "coroutine ... was never awaited"
    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED


async def test_leaves_a_ttl_task_running():
    task = asyncio.create_task(asyncio.sleep(3600))
    internal._ttl_tasks["leak"] = task
    _left_behind.append(task)


# relies on file order: runs right after the test above
async def test_ttl_tasks_are_cancelled_and_cleared_after_each_test():
    assert internal._ttl_tasks == {}
    assert all(t.cancelled() for t in _left_behind)
