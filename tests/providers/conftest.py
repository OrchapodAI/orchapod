"""Shared fixtures for the provider clients: recorded responses replayed through httpx.MockTransport."""

from __future__ import annotations

import time

import httpx
import pytest


@pytest.fixture(autouse=True)
def provider_env(monkeypatch):
    monkeypatch.delenv("STUB", raising=False)
    monkeypatch.delenv("NEBIUS_BASE_URL", raising=False)
    monkeypatch.setenv("NEBIUS_API_KEY", "tf-key")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-key")


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Backoff sleeps are recorded, never slept."""
    s: list[float] = []
    monkeypatch.setattr(time, "sleep", s.append)
    return s


@pytest.fixture
def recorder():
    """(calls, on_usage): on_usage records each call as (args, kwargs)."""
    calls = []
    return calls, lambda *a, **k: calls.append((a, k))


@pytest.fixture
def replay():
    """replay(*answers) -> (httpx.Client, seen requests); each request gets the next answer (a Response, or an exception to raise)."""
    def make(*answers):
        queue, seen = list(answers), []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            answer = queue.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        return httpx.Client(transport=httpx.MockTransport(handler)), seen
    return make
