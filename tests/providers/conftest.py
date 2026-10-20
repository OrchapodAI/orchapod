"""Shared fixtures for the provider clients: recorded responses replayed through httpx.MockTransport."""

from __future__ import annotations

import sys
import time

import httpx
import pytest

# tests/containers/test_unsloth_train.py leaves a fake, non-package `orchapod` in sys.modules for the rest of the
# session. Import the real price table past it, then put the fakes back for that file's run-time lookups.
_fakes = {name: sys.modules.pop(name) for name in list(sys.modules) if name.split(".")[0] == "orchapod"}
import orchapod.prices  # noqa: E402,F401
sys.modules.update(_fakes)


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
