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
import os
from datetime import datetime, timezone
from typing import Annotated, Iterator, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.database import get_session
from api.models.db import Artifact, ArtifactKind
from api.services import budget
from packages.providers.base import ProviderError
from packages.providers.tokenfactory import TF_BASE, TokenFactory

log = logging.getLogger("api.compare")
router = APIRouter()

Session = Annotated[AsyncSession, Depends(get_session)]
Scale = Annotated[float, Depends(budget.scale)]  # 1 for X-Orchapod-Admin, else ORCHAPOD_ANON_SCALE (R7)

# Answers still streaming: each one runs to its end and records its spend even when the client has hung up.
# ponytail: two worker threads per compare while it streams; D6 rate limits bound how many run at once.
_streams: set[asyncio.Task] = set()


class ModelRef(BaseModel):
    """contracts "ModelRef"; extra keys (tf-deploy's `proof`) are ignored."""
    base_url: str
    model: str
    api_key_env: str
    base_model: str | None = None


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=8000)


class CompareRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=50)
    refs: list[ModelRef] = Field(min_length=2, max_length=2)
    max_tokens: int = Field(512, ge=1, le=2048)


@router.post("")
async def compare(body: CompareRequest, db: Session, scale: Scale):
    """Both answers start before the 200, so a refusal is an HTTP error, never a broken stream: 422 for a ref outside the
    key↔URL pairs or a request Token Factory rejects (an unpriced model, an unknown one); 502 when a model call fails;
    402/503 for the day budget and the kill switch. The same decoding for both: temperature 0, max_tokens."""
    await budget.guard(db, scale)
    keys = [await _key(db, ref) for ref in body.refs]
    messages = [m.model_dump() for m in body.messages]
    spent: list[list[float]] = [[], []]
    answers = [TokenFactory(on_usage=budget.meter(spent[i])).stream_chat(
        messages, ref.model, base_url=ref.base_url, api_key=key, base_model=ref.base_model, max_tokens=body.max_tokens)
        for i, (ref, key) in enumerate(zip(body.refs, keys))]
    firsts = await asyncio.gather(*(asyncio.to_thread(next, a, None) for a in answers), return_exceptions=True)
    for i, first in enumerate(firsts):
        if isinstance(first, BaseException):
            for a in answers:
                a.close()  # ponytail: an answer that had started is billed by Token Factory but not in our ledger
            if isinstance(first, ProviderError) and first.kind == "bad_request":
                raise HTTPException(status_code=422, detail=f"refs[{i}]: {first}")
            log.warning("compare refs[%d] %s failed: %r", i, body.refs[i].model, first)
            raise HTTPException(status_code=502, detail=f"refs[{i}] ({body.refs[i].model}) failed; the API log has the cause")

    queue: asyncio.Queue = asyncio.Queue()
    for i, (answer, first) in enumerate(zip(answers, firsts)):
        if first is not None:
            queue.put_nowait({"i": i, "delta": first})
        task = asyncio.create_task(_finish(i, answer, queue, spent[i]))
        _streams.add(task)
        task.add_done_callback(_streams.discard)
    return StreamingResponse(_sse(queue, len(answers)), media_type="text/event-stream")


async def _key(db: AsyncSession, ref: ModelRef) -> str:
    """The key the pairing rule allows for this ref: NEBIUS_API_KEY only with Token Factory, ORCHAPOD_ENDPOINT_TOKEN only
    with an endpoint registered through /internal/ttl. Anything else would hand our key (or our network) to a caller's URL."""
    url = ref.base_url.strip().rstrip("/")
    if ref.api_key_env == "NEBIUS_API_KEY" and url == (os.environ.get("NEBIUS_BASE_URL") or TF_BASE).strip().rstrip("/"):
        return os.environ.get("NEBIUS_API_KEY") or ""
    if ref.api_key_env == "ORCHAPOD_ENDPOINT_TOKEN" and await _registered(db, url):
        return os.environ.get("ORCHAPOD_ENDPOINT_TOKEN") or ""
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
