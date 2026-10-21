"""Harness checks: CI wiring that nothing else would notice breaking."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CI = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())


def test_ci_installs_only_requirements_files():
    run = next(s["run"] for s in CI["jobs"]["test"]["steps"] if "pip install" in s.get("run", ""))
    assert run.split()[-1].endswith(".txt"), run


def test_requirements_dev_has_lint_and_container_test_deps():
    text = (ROOT / "requirements-dev.txt").read_text()
    assert all(dep in text for dep in ("ruff==", "huggingface_hub", "jsonschema")), text


def test_ci_pushes_latest_only_on_nebiushackathon():
    latest = [
        ln
        for job in CI["jobs"].values()
        for step in job["steps"]
        for ln in str(step.get("with", {}).get("tags", "")).splitlines()
        if ":latest" in ln
    ]
    assert latest and all("NebiusHackathon" in ln for ln in latest), latest


def test_ci_builds_every_container():
    matrix = set(CI["jobs"]["containers"]["strategy"]["matrix"]["node"])
    assert matrix == {p.parent.name for p in (ROOT / "containers").glob("*/Dockerfile")}
