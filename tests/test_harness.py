"""Harness checks: CI wiring that nothing else would notice breaking."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CI = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())


def _step(job, match):
    return next(s for s in CI["jobs"][job]["steps"] if match(s))


def test_ci_installs_only_requirements_files():
    run = _step("test", lambda s: "pip install" in s.get("run", ""))["run"]
    assert all(a == "-r" or a.endswith(".txt") for a in run.split()[2:]), run


def test_requirements_dev_has_lint_and_container_test_deps():
    lines = {ln.strip() for ln in (ROOT / "requirements-dev.txt").read_text().splitlines()}
    assert {"huggingface_hub", "ruff==0.17.1", "jsonschema"} <= lines


def test_ci_pushes_latest_only_on_nebiushackathon():
    build = _step("containers", lambda s: "build-push-action" in s.get("uses", ""))
    latest = [t for t in build["with"]["tags"].splitlines() if ":latest" in t]
    assert len(latest) == 1 and "github.ref_name == 'NebiusHackathon'" in latest[0], latest


def test_ci_builds_every_container():
    matrix = set(CI["jobs"]["containers"]["strategy"]["matrix"]["node"])
    assert matrix == {p.parent.name for p in (ROOT / "containers").glob("*/Dockerfile")}
