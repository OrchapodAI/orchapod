"""The API's fixtures (in-memory database, ASGI client, budget grants cleared) without tests/api's other autouse ones:
the drills keep the real per-IP rate limits, and start every test with full buckets."""

import pytest

from tests.api.conftest import client, db, no_grants  # noqa: F401 (fixtures)


@pytest.fixture(autouse=True)
def full_buckets(monkeypatch):
    """backend-w4's per-IP buckets live in the process: one drill must not spend the next one's."""
    from api.services import ratelimit
    monkeypatch.setattr(ratelimit, "_buckets", {})
