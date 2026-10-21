"""apps/api/config.py: every docs/contracts.md "Config" default in one module, read on every call."""

from __future__ import annotations

import re
from pathlib import Path

from api import config

API = Path(__file__).resolve().parents[2] / "apps/api"


def test_the_api_reads_its_env_only_through_config_env():
    files = [p for p in API.rglob("*.py") if p.name != "config.py" and "alembic" not in p.parts]
    assert [str(p.relative_to(API)) for p in files if re.search(r"os\.(environ|getenv)", p.read_text())] == []
    names = {n for p in files for n in re.findall(r"""config\.env\(\s*["']([A-Z0-9_]+)["']""", p.read_text())}
    assert "ORCHAPOD_KILL_SWITCH" in names and sorted(names - set(config.DEFAULTS)) == []


def test_blank_or_unset_is_the_default_and_a_change_is_seen_at_once(monkeypatch):
    monkeypatch.delenv("ORCHAPOD_CONTROL_URL", raising=False)
    assert config.env("ORCHAPOD_CONTROL_URL") == "http://localhost:8001"  # contracts "Config"; this Mac's .env says 8002
    monkeypatch.setenv("ORCHAPOD_CONTROL_URL", "")  # compose passes ${VAR:-}
    assert config.env("ORCHAPOD_CONTROL_URL") == "http://localhost:8001"
    monkeypatch.setenv("ORCHAPOD_CONTROL_URL", "http://host.docker.internal:8002")
    assert config.env("ORCHAPOD_CONTROL_URL") == "http://host.docker.internal:8002"
