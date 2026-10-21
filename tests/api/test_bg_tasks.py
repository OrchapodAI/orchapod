"""no_bg_tasks: a stubbed asyncio.create_task must not leave its coroutine un-awaited."""

import asyncio
import inspect


async def test_no_bg_tasks_closes_the_coroutine_it_is_handed(no_bg_tasks):
    async def job():
        pass

    coro = job()
    asyncio.create_task(coro)

    # CORO_CREATED here is what later surfaces as "coroutine ... was never awaited"
    assert inspect.getcoroutinestate(coro) == inspect.CORO_CLOSED
