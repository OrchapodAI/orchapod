"""The README must stay true to docs/contracts.md and the Makefile.

A cheap drift guard: it fails when the README goes back to a stale name, URL or
port, names a `make` target or env var that does not exist, or loses a section.
"""

from __future__ import annotations

import json
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
    "$1.82",  # gpu-l40s-a is $1.55/h (Intel L40S); $1.82 is the AMD gpu-l40s-d (DECISION 2026-10-21)
    "No pipeline has run live",  # intents #2 and #3 ran live through the Agent on 2026-10-22 (runs 84e57f84, 59786797)
    "no live run yet",
    "drives the real-estate template card",  # the smoke's golden-path test clicks template 4's card since qa-w8
]
# Every TODO names when it clears: D8 (a live run, the hosted app) or G3 (the repo and its images go public).
BARE_TODO = r"TODO(?!\((?:D8|G3)\))"


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


def test_a_code_block_starts_the_web_app_on_pnpm_11():
    # qa-w10 F1: on pnpm 11 a plain `pnpm dev` dies after install's ERR_PNPM_IGNORED_BUILDS; the fix in prose was missed.
    blocks = re.findall(r"```bash\n(.*?)```", README, re.S)
    assert any("pnpm --config.verify-deps-before-run=false dev" in b for b in blocks)


def test_no_stale_strings():
    assert [s for s in STALE if s in README] == []


def test_every_todo_names_its_day():
    assert not re.search(BARE_TODO, README)


def test_unbuilt_make_targets_are_marked_todo():
    # `make e2e API=…` exists since qa-w9 but has not run live (it needs the hosted API and GPU quota). `make agent-e2e` ran
    # live on 2026-10-22, so it is no longer pinned. Drop this test when `make e2e` has a live result.
    for line in README.splitlines():
        if re.search(r"\bmake e2e\b", line):
            assert "TODO(D8)" in line, f"the target does not work yet: {line[:70]}"


def _templates() -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(ROOT.glob("apps/api/agent/templates/*.json"))]


def _node_types() -> set[str]:
    from packages.workflow_schema.models import NODE_REGISTRY
    return {t.value for t in NODE_REGISTRY}


def test_every_template_card_is_in_the_readme():
    titles = [t["title"] for t in _templates()]
    assert titles and [t for t in titles if t not in README] == []


def test_each_intent_row_shows_its_templates_node_chain():
    for t in _templates():
        row = next((ln for ln in README.splitlines() if f"| **{t['title']}** |" in ln), "")
        assert row, f"no intents-table row for {t['title']}"
        chain = [seg.split()[0] for seg in row.rsplit("|", 2)[-2].split("→")]
        assert [s for s in chain if s in _node_types()] == [n["type"] for n in t["plan"]["nodes"]], t["title"]


def test_the_image_lists_are_the_templates_node_types():
    names = "|".join(map(re.escape, _node_types()))
    section = README.partition("**Node images.**")[2].partition("**GPU nodes")[0]
    lists = re.findall(rf"(?<![\w-])(?:(?:{names}) )+(?:{names})(?![\w-])", section)
    assert {frozenset(m.split()) for m in lists} == {frozenset(n["type"] for n in t["plan"]["nodes"]) for t in _templates()}


def test_node_table_matches_the_registry():
    from packages.workflow_schema.models import NODE_REGISTRY
    visible = {t.value: row["runtime"] for t, row in NODE_REGISTRY.items() if not row.get("hidden")}
    assert dict(re.findall(r"^\| `([a-z-]+)` \| (cpu|gpu|api) \|", README, re.M)) == visible


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
