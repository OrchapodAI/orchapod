"""
apps/api/routes/compare.py

The compare playground (docs/contracts.md "Run control API" and "ModelRef"): one prompt, two models, both answers
streamed side by side. Keys are resolved here, under the pairing rule, so they never reach the browser.

Routes:
  POST /compare  — SSE {"i", "delta"} … then {"i", "done": true, "usd"} for each of the two refs
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Iterator, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api import config
from api.agent.planner import tf_base
from api.database import get_session
from api.models.db import Artifact, ArtifactKind
from api.services import budget
from packages.providers.base import ProviderError
from packages.providers.tokenfactory import TokenFactory

log = logging.getLogger("api.compare")
router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]
Scale = Annotated[float, Depends(budget.scale)]  # 1 for X-Orchapod-Admin, else ORCHAPOD_ANON_SCALE (R7)

# Compares still streaming: each answer runs to its end and records its spend, also when the client has hung up or
# the request was refused after the other answer had started. ponytail: the client bills after the last chunk, so an
# answer that breaks mid-stream records $0 of what Token Factory charged for it.
_streams: set[asyncio.Task] = set()
# Each compare holds two worker threads until both answers end; past this many, 503. The default pool has
# min(32, cpus + 4) threads, so the planner and reporter (asyncio.to_thread too) find a free one on 5+ CPUs;
# on smaller hosts they wait behind running answers (bounded by max_tokens, no deadlock).
_slots = asyncio.Semaphore(int(config.env("ORCHAPOD_MAX_COMPARES")))


class ModelRef(BaseModel):
    """contracts "ModelRef"; extra keys (tf-deploy's `proof`) are ignored."""
    base_url: str
    model: str
    api_key_env: str
    base_model: str | None = None


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class CompareRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=50)
    refs: list[ModelRef] = Field(min_length=2, max_length=2)
    max_tokens: int = Field(512, ge=1, le=2048)

    @model_validator(mode="after")
    def _short(self):
        """At most 16,000 characters of prompt, so one compare's worst case stays at cents."""
        if sum(len(m.content) for m in self.messages) > 16_000:
            raise ValueError("the messages hold more than 16,000 characters")
        return self


@router.post("")
async def compare(body: CompareRequest, db: Session, scale: Scale):
    """Both answers start before the 200, so a refusal is an HTTP error, never a broken stream: 422 for a ref outside the
    key↔URL pairs or a request Token Factory rejects (an unpriced model, an unknown one); 502 when a model call fails;
    402/503 for the day budget and the kill switch, 503 too while ORCHAPOD_MAX_COMPARES compares are in flight. The same
    decoding for both: temperature 0, max_tokens."""
    await budget.guard(db, scale)
    keys = [await _key(db, ref) for ref in body.refs]
    if _slots.locked():
        raise HTTPException(status_code=503, detail="too many compares in flight; try again in a moment")
    await _slots.acquire()  # held until both answers have ended (_both)
    messages = [m.model_dump() for m in body.messages]
    spent: list[list[float]] = [[], []]
    answers = [TokenFactory(on_usage=budget.meter(spent[i])).stream_chat(
        messages, ref.model, base_url=ref.base_url, api_key=key, base_model=ref.base_model, max_tokens=body.max_tokens)
        for i, (ref, key) in enumerate(zip(body.refs, keys))]
    try:
        firsts = await asyncio.gather(*(asyncio.to_thread(next, a, None) for a in answers), return_exceptions=True)
    except BaseException:  # cancelled (shutdown) before _both owns the slot: give it back
        _slots.release()
        raise
    failed = next(((i, e) for i, e in enumerate(firsts) if isinstance(e, BaseException)), None)

    queue: asyncio.Queue = asyncio.Queue()
    for i, first in enumerate(firsts):
        if failed is None and first is not None:
            queue.put_nowait({"i": i, "delta": first})
    # a refused compare still drains the answer that started, into a queue nobody reads, so its spend is recorded
    task = asyncio.create_task(_both([_finish(i, a, queue if failed is None else asyncio.Queue(), spent[i])
                                      for i, a in enumerate(answers)]))
    _streams.add(task)
    task.add_done_callback(_streams.discard)
    if failed:
        i, e = failed
        if isinstance(e, ProviderError) and e.kind == "bad_request":
            raise HTTPException(status_code=422, detail=f"refs[{i}]: {e}")
        log.warning("compare refs[%d] %s failed: %r", i, body.refs[i].model, e)
        raise HTTPException(status_code=502, detail=f"refs[{i}] ({body.refs[i].model}) failed; the API log has the cause")
    return StreamingResponse(_sse(queue, len(answers)), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _key(db: AsyncSession, ref: ModelRef) -> str:
    """The key the pairing rule allows for this ref: NEBIUS_API_KEY only with Token Factory, ORCHAPOD_ENDPOINT_TOKEN only
    with an endpoint registered through /internal/ttl. Anything else would hand our key (or our network) to a caller's URL."""
    url = ref.base_url.strip().rstrip("/")
    if ref.api_key_env == "NEBIUS_API_KEY" and url == tf_base():
        return config.env("NEBIUS_API_KEY")
    if ref.api_key_env == "ORCHAPOD_ENDPOINT_TOKEN" and await _registered(db, url):
        return config.env("ORCHAPOD_ENDPOINT_TOKEN")
    raise HTTPException(status_code=422, detail=f"refused ModelRef {ref.model} at {ref.base_url} with {ref.api_key_env!r}: "
                                                "NEBIUS_API_KEY goes only to Token Factory, ORCHAPOD_ENDPOINT_TOKEN only to "
                                                "an endpoint registered through /internal/ttl")


async def _registered(db: AsyncSession, url: str) -> bool:
    """An endpoint our vllm-serve registered (its base URL, with or without /v1) that has neither expired nor been deleted."""
    root = url.removesuffix("/v1")
    rows = await db.scalars(select(Artifact).where(Artifact.kind == ArtifactKind.ENDPOINT,
                                                   Artifact.uri.in_([root, root + "/", root + "/v1", root + "/v1/"])))
    now = datetime.now(timezone.utc)
    return any(a.meta.get("expires_at") and not a.meta.get("deleted_at")
               and datetime.fromisoformat(a.meta["expires_at"]) > now for a in rows)


async def _both(finishes: list) -> None:
    """Both answers to their end, then the compare's slot is free."""
    try:
        await asyncio.gather(*finishes)
    finally:
        _slots.release()


async def _finish(i: int, answer: Iterator[str], queue: asyncio.Queue, spent: list[float]) -> None:
    """Stream the rest of one answer into the queue, put its spend into the day ledger, then its done event."""
    loop, done = asyncio.get_running_loop(), {"i": i, "done": True}

    def drain():  # on a worker thread: the client is sync
        for delta in answer:
            loop.call_soon_threadsafe(queue.put_nowait, {"i": i, "delta": delta})

    try:
        await asyncio.to_thread(drain)
        done["usd"] = round(sum(spent, 0.0), 6)
    except Exception as e:
        log.warning("compare refs[%d] failed mid-stream: %r", i, e)
        done |= {"usd": None, "error": "the model call failed mid-stream; the API log has the cause"}
    try:
        if sum(spent):
            from api import database
            async with database.AsyncSessionLocal() as db:
                await budget.record(db, "compare", sum(spent))
    except Exception as e:  # the answer still ends: a client must never wait on our ledger
        log.error("compare spend $%.6f is not in the day ledger: %r", sum(spent), e)
    queue.put_nowait(done)


async def _sse(queue: asyncio.Queue, n: int):
    finished = 0
    while finished < n:
        event = await queue.get()
        finished += bool(event.get("done"))
        yield f"data: {json.dumps(event)}\n\n"
