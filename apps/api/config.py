"""
apps/api/config.py

docs/contracts.md "Config": every variable the API reads, with its default, in one place. env() reads os.environ on
every call, so no value is cached (tests, the kill switch); blank counts as unset, because compose passes `${VAR:-}`.
Provider clients and node containers read os.environ themselves.
"""

from __future__ import annotations

import os

from packages.providers.tokenfactory import TF_BASE

DEFAULTS = {
    # Token Factory, Tavily, Hugging Face, Nebius AI Cloud ("" = none)
    "NEBIUS_API_KEY": "", "NEBIUS_BASE_URL": TF_BASE, "TAVILY_API_KEY": "", "HF_TOKEN": "",
    "NEBIUS_PROJECT_ID": "", "NEBIUS_IAM_TOKEN": "", "ORCHAPOD_ENDPOINT_TOKEN": "",
    # object storage: the compose MinIO; node images
    "ORCHAPOD_R2_ENDPOINT": "http://localhost:9000", "ORCHAPOD_R2_REGION": "auto", "ORCHAPOD_R2_ACCESS_KEY": "orchapod",
    "ORCHAPOD_R2_SECRET_KEY": "orchapod_dev", "ORCHAPOD_R2_BUCKET": "orchapod-artifacts",
    "ORCHAPOD_IMAGE_PREFIX": "ghcr.io/bangadpurva",
    # control plane
    "DATABASE_URL": "sqlite+aiosqlite:///./orchapod_dev.db", "REDIS_URL": "redis://localhost:6379",
    "ORCHAPOD_CONTROL_URL": "http://localhost:8001", "ORCHAPOD_INTERNAL_SECRET": "",
    "ORCHAPOD_CORS_ORIGINS": "",
    # budget
    "ORCHAPOD_MAX_RUN_USD": "3", "ORCHAPOD_MAX_DAY_USD": "15", "ORCHAPOD_KILL_SWITCH": "0", "ORCHAPOD_ANON_SCALE": "0.1",
    "ORCHAPOD_ADMIN_TOKEN": "", "ORCHAPOD_NODE_TIMEOUT_S": "5400", "ORCHAPOD_MAX_COMPARES": "4",
    # nodes; optional
    "STUB": "", "VASTAI_API_KEY": "", "RESEND_API_KEY": "", "ORCHAPOD_FROM_EMAIL": "noreply@orchapod.ai",
    "ORCHAPOD_ALERT_EMAIL": "",
}


def env(name: str) -> str:
    """os.environ[name], or its default when unset or blank; a name missing from DEFAULTS is a KeyError."""
    return os.environ.get(name) or DEFAULTS[name]
