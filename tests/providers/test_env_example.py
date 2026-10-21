""".env.example, the compose files and the code agree on the docs/contracts.md "Config" variables."""

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
    "ORCHAPOD_ADMIN_TOKEN": "", "ORCHAPOD_NODE_TIMEOUT_S": "5400", "ORCHAPOD_MAX_COMPARES": "4",
    "STUB": "", "HF_TOKEN": "", "RESEND_API_KEY": "",
    "ORCHAPOD_FROM_EMAIL": "noreply@orchapod.ai", "ORCHAPOD_ALERT_EMAIL": "",
}
HOSTED = {"DOMAIN": "", "POSTGRES_PASSWORD": ""}  # only infra/docker-compose.prod.yml reads these
REMOVED = ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "JUDGE_MODEL", "NEBIUS_FOLDER_ID", "NEBIUS_SUBNET_ID",
           "RUNPOD_API_KEY", "GITHUB_ORG", "CLOUDFLARE_TUNNEL_TOKEN"]
NOT_IN_ENV_EXAMPLE = {  # read by code, set by nobody's .env
    **dict.fromkeys(["ORCHAPOD_NODE_INPUTS", "ORCHAPOD_NODE_OUTPUTS_DIR", "ORCHAPOD_RUN_ID", "ORCHAPOD_NODE_ID",
                     "ORCHAPOD_MAX_COST_USD", "ORCHAPOD_RESUME_CHECKPOINT_URI"], "the executor sets it per node"),
    "ORCHAPOD_CHECKPOINT_STEPS": "SDK default 100; the executor does not forward it",
    "NEBIUS_FOLDER_ID": "removed from Config; only the legacy Compute code in nebius.py reads it, until its rewrite",
    "NEBIUS_SUBNET_ID": "removed from Config; only the legacy Compute code in nebius.py reads it, until its rewrite",
}
READ = re.compile(r"""os\.(?:environ\.get|getenv|environ\.setdefault)\(\s*["']([A-Z][A-Z0-9_]*)["']"""
                  r"""|os\.environ\[\s*["']([A-Z][A-Z0-9_]*)["']\s*\]""")


def names_read() -> set[str]:
    """Every env name the Python under apps/ and packages/ reads (apps/web is TypeScript)."""
    files = [*ROOT.glob("apps/api/**/*.py"), *ROOT.glob("packages/**/*.py")]
    return {a or b for f in files for a, b in READ.findall(f.read_text())}


def test_env_example_is_the_contract_config():
    text = ENV_EXAMPLE.read_text()
    env = dict(re.findall(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, re.M))
    assert env == CONFIG | HOSTED
    assert [name for name in REMOVED if name in text] == []


def test_vastai_key_is_documented_but_never_live():
    """A set VASTAI_API_KEY registers vast.ai, so a gpu node whose provider_pref names it rents a vast.ai GPU."""
    assert re.search(r"^# VASTAI_API_KEY=$", ENV_EXAMPLE.read_text(), re.M)


def test_every_env_name_the_code_reads_is_in_env_example():
    documented = set(re.findall(r"^#? ?([A-Z][A-Z0-9_]*)=", ENV_EXAMPLE.read_text(), re.M))
    read = names_read()
    assert "DATABASE_URL" in read  # the scan sees a read split over lines (apps/api/database.py)
    assert sorted(read - documented - set(NOT_IN_ENV_EXAMPLE)) == []
    assert sorted(set(NOT_IN_ENV_EXAMPLE) - read) == []  # a stale allow-list entry goes


def test_compose_api_gets_the_contract_config_on_8001():
    text = COMPOSE.read_text()
    services = yaml.safe_load(text)["services"]
    assert services["api"]["ports"] == ["8001:8000"]  # host 8000 belongs to another project
    assert set(services["api"]["environment"]) == set(CONFIG) | {"VASTAI_API_KEY"}  # spikes may set it locally
    assert services["web"]["environment"]["NEXT_PUBLIC_API_URL"] == "http://localhost:8001"
    assert [name for name in REMOVED + ["253B"] if name in text] == []
