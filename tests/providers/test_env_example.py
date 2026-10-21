""".env.example and compose's api service carry exactly the docs/contracts.md "Config" variables."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = ROOT / ".env.example"
COMPOSE = ROOT / "infra" / "docker-compose.dev.yml"

CONFIG = {  # name → the value .env.example ships ("" = none; you fill it in)
    "NEBIUS_API_KEY": "", "NEBIUS_BASE_URL": "https://api.tokenfactory.nebius.com/v1", "TAVILY_API_KEY": "",
    "NEBIUS_PROJECT_ID": "", "NEBIUS_IAM_TOKEN": "", "ORCHAPOD_ENDPOINT_TOKEN": "",
    "ORCHAPOD_R2_ENDPOINT": "http://localhost:9000", "ORCHAPOD_R2_REGION": "auto", "ORCHAPOD_R2_ACCESS_KEY": "orchapod",
    "ORCHAPOD_R2_SECRET_KEY": "orchapod_dev", "ORCHAPOD_R2_BUCKET": "orchapod-artifacts",
    "ORCHAPOD_IMAGE_PREFIX": "ghcr.io/bangadpurva",
    "DATABASE_URL": "postgresql+asyncpg://orchapod:orchapod_dev@localhost:5432/orchapod",
    "REDIS_URL": "redis://localhost:6379", "ORCHAPOD_CONTROL_URL": "http://localhost:8001", "ORCHAPOD_INTERNAL_SECRET": "",
    "ORCHAPOD_MAX_RUN_USD": "3", "ORCHAPOD_MAX_DAY_USD": "15", "ORCHAPOD_KILL_SWITCH": "0", "ORCHAPOD_ANON_SCALE": "0.1",
    "ORCHAPOD_ADMIN_TOKEN": "", "ORCHAPOD_NODE_TIMEOUT_S": "5400",
    "STUB": "", "HF_TOKEN": "", "VASTAI_API_KEY": "", "RESEND_API_KEY": "",
    "ORCHAPOD_FROM_EMAIL": "noreply@orchapod.ai", "ORCHAPOD_ALERT_EMAIL": "",
}
REMOVED = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "JUDGE_MODEL", "NEBIUS_FOLDER_ID", "NEBIUS_SUBNET_ID",
           "RUNPOD_API_KEY", "GITHUB_ORG", "CLOUDFLARE_TUNNEL_TOKEN"]


def test_env_example_is_the_contract_config():
    text = ENV_EXAMPLE.read_text()
    env = dict(re.findall(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, re.M))
    assert env == CONFIG
    assert [name for name in REMOVED if name in text] == []


def test_compose_api_gets_the_contract_config_on_8001():
    text = COMPOSE.read_text()
    services = yaml.safe_load(text)["services"]
    assert services["api"]["ports"] == ["8001:8000"]  # host 8000 belongs to another project
    assert set(services["api"]["environment"]) == set(CONFIG)
    assert services["web"]["environment"]["NEXT_PUBLIC_API_URL"] == "http://localhost:8001"
    assert [name for name in REMOVED + ["253B"] if name in text] == []
