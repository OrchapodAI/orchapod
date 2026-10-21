"""The README must stay true to docs/contracts.md and the Makefile.

A cheap drift guard: it fails when the README goes back to a stale name, URL or
port, names a `make` target or env var that does not exist, or loses a section.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


README = _read("README.md")
MAKEFILE = _read("Makefile")
CONTRACTS = _read("docs", "contracts.md") + _read("docs", "NODE_CONTRACT.md")

SECTIONS = [
    "What it is",
    "Why",
    "How it works",
    "How we use Nemotron, Token Factory, Nebius AI Cloud and Tavily",
    "Setup",
    "Run the demo",
    "Costs and caps",
    "What changed during the submission period",
    "License",
]
# The real ids, as pinned in docs/contracts.md (TokenFactory section).
MODELS = [
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/Nemotron-3-Ultra-550b-a55b",
    "nvidia/Nemotron-3_5-Lightning",
]
STALE = [
    "studio.nebius.ai",  # legacy Token Factory host
    "Super 49B",
    "Ultra 253B",
    "localhost:8000",  # our API is on 8001; 8000 belongs to another project
    "ANTHROPIC_API_KEY",  # stage one: no other model provider on the demo path
    "OPENAI_API_KEY",
]


def test_required_sections():
    for title in SECTIONS:
        assert re.search(rf"^## {re.escape(title)}", README, re.M), f"missing section: {title}"


def test_models_urls_and_clone_url():
    for model in MODELS:
        assert model in README, f"README must name {model}"
        assert model in CONTRACTS, f"{model} is not in docs/contracts.md"
    for needle in ("https://api.tokenfactory.nebius.com/v1", "github.com/bangadpurva/orchapod.ai"):
        assert needle in README, f"README must mention {needle}"
    assert not re.search(r"bangadpurva/orchapod(?!\.ai)", README), "the clone URL ends in orchapod.ai"


def test_setup_and_license_lines():
    for line in (
        "git clone -b NebiusHackathon https://github.com/bangadpurva/orchapod.ai.git",
        "make up",
        "make check",
        "[MIT](LICENSE)",
    ):
        assert line in README, f"README must contain: {line}"


def test_no_stale_strings():
    assert [s for s in STALE if s in README] == []


def test_every_todo_names_its_day():
    assert not re.search(r"TODO(?!\(D8\))", README)


def test_unbuilt_make_targets_are_marked_todo():
    # `make e2e` needs the real mode of scripts/e2e_demo.py (only --stub exists); e2e_agent.py and seed-golden-run.py are not
    # written yet. Drop this test when all three targets work.
    for line in README.splitlines():
        if re.search(r"\bmake (e2e|agent-e2e|demo)\b", line):
            assert "TODO(D8)" in line, f"the target does not work yet: {line[:70]}"


def test_unmeasured_claims_carry_a_todo():
    # Drop each needle when the golden run measures it (D8).
    for needle in ("An evaluation you can trust", "The guard checks the estimate"):
        line = next((ln for ln in README.splitlines() if needle in ln), "")
        assert line, f"the README line with {needle!r} is missing"
        assert "TODO(D8)" in line, f"nothing measured yet, so the line needs TODO(D8): {needle}"


def test_make_targets_and_env_vars_exist():
    code = " ".join(re.findall(r"```.*?```|`[^`\n]+`", README, re.S))
    targets = set(re.findall(r"^([a-z][\w-]*):", MAKEFILE, re.M))
    for target in re.findall(r"\bmake ([a-z][\w-]*)", code):
        assert target in targets, f"README says `make {target}`; the Makefile has no such target"
    for name in set(re.findall(r"\b(?:NEBIUS|TAVILY|ORCHAPOD)_[A-Z0-9_]+", README)):
        assert name in CONTRACTS, f"{name} is in neither docs/contracts.md nor docs/NODE_CONTRACT.md"
