"""
apps/api/services/events.py

Redis pub/sub event bus — the backbone for live run streaming.

Flow:
  container → POST /internal/log → event_bus.publish() → Redis channel
  WebSocket handler → event_bus.subscribe() → yields events → frontend

One channel per run: "run:{run_id}"
"""

from __future__ import annotations

import json
from typing import AsyncGenerator
from uuid import UUID

import redis.asyncio as aioredis

from api import config


class EventBus:
    def __init__(self):
        self._redis: aioredis.Redis | None = None
        self._url = config.env("REDIS_URL")

    async def connect(self) -> None:
        self._redis = aioredis.from_url(self._url, decode_responses=True)

    async def disconnect(self) -> None:
        if self._redis:
            await self._redis.aclose()

    @property
    def redis(self) -> aioredis.Redis:
        if self._redis is None:
            raise RuntimeError("EventBus not connected — call connect() at startup")
        return self._redis

    async def publish(self, run_id: UUID, event: dict) -> None:
        channel = f"run:{run_id}"
        await self.redis.publish(channel, json.dumps(event))

    async def subscribe(self, run_id: UUID) -> AsyncGenerator[dict, None]:
        """
        Async generator that yields events for a run until the run reaches
        a terminal state (succeeded / failed / cancelled).
        """
        pubsub = self.redis.pubsub()
        channel = f"run:{run_id}"
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                event = json.loads(message["data"])
                yield event
                # Stop streaming once the run finishes
                if event.get("type") == "run_status" and event.get("status") in (
                    "succeeded", "failed", "cancelled"
                ):
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()


# Singleton — imported everywhere
event_bus = EventBus()
