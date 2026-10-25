"""The submission docs (docs/feedback.md, docs/devpost.md) must stay sourced and consistent.

Cheap drift guards, stdlib only: every feedback finding cites a source, every repo path a doc cites
exists, and no doc carries a stale name or an unmarked TODO.
"""

from __future__ import annotations

import re

from tests.docs.test_readme import BARE_TODO, MODELS, README, ROOT, STALE, _read


def _section(text: str, title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"missing section: {title}"
    return match.group(1)


CHANGELOG = _read("CHANGELOG.md")
DEVPOST = _read("docs", "devpost.md")
FEEDBACK = _read("docs", "feedback.md")
DOCS = {"devpost": DEVPOST, "feedback": FEEDBACK}
FINDINGS = re.findall(r"^- .*(?:\n  .*)*", FEEDBACK, re.M)

FIELDS = [
    "Title",
    "Tagline",
    "Description",
    "Built with",
    "Track",
    "Links",
    "What changed during the submission period",
]
# The plan's checklist: the description names the sponsor pieces explicitly.
SPONSORS = [
    "Nebius Token Factory",
    "Nebius AI Cloud",
    "Serverless Jobs",
    "Serverless Endpoints",
    "Object Storage",
    "NVIDIA Nemotron",
    "Tavily",
]
AREAS = ["Token Factory", "Nebius AI Cloud", "NVIDIA Nemotron models"]
# One needle per seed finding, found in no other bullet: deleting the bullet fails the test.
SEEDS = [
    "our sources disagree",  # serving a fine-tune per token: the docs disagree
    "deploy-custom-model",  # the 404 deploy page
    "has no `/v0/models`",  # the live OpenAPI
    "left Token Factory serverless",  # Llama-3.3-70B, 2026-08-31
    "custom-weights",  # Dedicated endpoints: beta, on request
    "result_files",  # checkpoint downloads
    "response_format",  # json_object and text vs json_schema
    "not available over REST",  # Job logs
]


def test_devpost_fields_and_track():
    for title in FIELDS:
        assert _section(DEVPOST, title).strip(), f"empty or missing field: {title}"
    assert _section(DEVPOST, "Track").strip() == "Best Apps and Agents"


def test_devpost_names_the_sponsor_pieces_and_model_ids():
    description = _section(DEVPOST, "Description")
    assert [s for s in SPONSORS + MODELS if s not in description] == []


def test_devpost_period_paragraph_matches_the_changelog():
    first = re.search(r"first commit is (\w+ \d+, \d{4})", CHANGELOG)
    assert first, "CHANGELOG.md must state the date of the first commit"
    assert first.group(1) in _section(DEVPOST, "What changed during the submission period")


def test_every_feedback_finding_cites_a_source():
    for area in AREAS:
        findings = re.findall(r"^- .*(?:\n  .*)*", _section(FEEDBACK, area), re.M)
        assert findings, f"no findings under {area}"
        assert [f[:60] for f in findings if "Source:" not in f] == []


def test_feedback_carries_the_seed_findings():
    assert [s for s in SEEDS if s not in FEEDBACK] == []


def test_findings_that_cite_the_openapi_name_its_version():
    assert [f[:60] for f in FINDINGS if "OpenAPI" in f and "20261020" not in f] == []


def test_the_report_is_written_by_super_or_a_deterministic_template():
    # contracts "Agent API" (backend-w7): Super writes it when the run ends; STUB=1, or a failed call, gets the template.
    for name, text in {"README": README, "devpost": DEVPOST}.items():
        line = next((ln for ln in text.splitlines() if "deterministic template" in ln), "")
        assert line, f"{name}: no line says a deterministic template can write the report"
        assert "Nemotron 3 Super writes" in line and "Lightning writes" not in line, f"{name}: Super writes the report"
    assert "| Reporter | `nvidia/nemotron-3-super-120b-a12b` |" in README


def test_docs_have_no_stale_strings_or_bare_todos():
    for name, text in DOCS.items():
        assert [s for s in STALE if s in text] == [], name
        assert not re.search(BARE_TODO, text), f"{name}: every TODO names its day"


def test_the_cpu_exact_match_is_called_noise_wherever_it_appears():
    # f16 0.78 vs q4_k_m 0.84 at n = 50 is a 3-question gap: never present it as q4 beating f16.
    for name, text in {"README": README, **DOCS}.items():
        assert [ln[:60] for ln in text.splitlines() if re.search(r"\b0\.84\b", ln) and "noise" not in ln] == [], name


def test_cited_repo_paths_exist():
    for name, text in DOCS.items():
        for path in re.findall(r"`((?:hackathon|docs|containers)/[\w./-]+|CHANGELOG\.md|README\.md)`", text):
            assert (ROOT / path).exists(), f"{name} cites {path}, which does not exist"
