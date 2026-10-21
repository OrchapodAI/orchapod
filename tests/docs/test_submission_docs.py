"""The submission docs (docs/feedback.md, docs/devpost.md) must stay sourced and consistent.

Cheap drift guards, stdlib only: every feedback finding cites a source, every repo path a doc cites
exists, and no doc carries a stale name or an unmarked TODO.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.docs.test_readme import STALE

ROOT = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _section(text: str, title: str) -> str:
    match = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"missing section: {title}"
    return match.group(1)


FEEDBACK = _read("docs", "feedback.md")
DOCS = {"feedback": FEEDBACK}

AREAS = ["Token Factory", "Nebius AI Cloud", "NVIDIA Nemotron models"]
# The first version must carry these findings; each needle appears only in its own bullet.
SEEDS = ["/v0/models", "Llama-3.3-70B", "2026-08-31", "over REST", "beta", "404"]


def test_every_feedback_finding_cites_a_source():
    for area in AREAS:
        findings = re.findall(r"^- .*(?:\n  .*)*", _section(FEEDBACK, area), re.M)
        assert findings, f"no findings under {area}"
        assert [f[:60] for f in findings if "Source:" not in f] == []


def test_feedback_carries_the_seed_findings():
    assert [s for s in SEEDS if s not in FEEDBACK] == []


def test_docs_have_no_stale_strings_or_bare_todos():
    for name, text in DOCS.items():
        assert [s for s in STALE if s in text] == [], name
        assert not re.search(r"TODO(?!\(D8\))", text), f"{name}: every TODO names its day"


def test_cited_repo_paths_exist():
    for name, text in DOCS.items():
        for path in re.findall(r"`((?:hackathon|docs|containers)/[\w./-]+|CHANGELOG\.md|README\.md)`", text):
            assert (ROOT / path).exists(), f"{name} cites {path}, which does not exist"
