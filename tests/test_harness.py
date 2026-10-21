"""Harness checks: CI wiring that nothing else would notice breaking."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
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


def test_ci_web_job_runs_the_web_tests():
    test = next((s for s in CI["jobs"]["web"]["steps"] if s.get("run") == "pnpm test"), None)
    assert test and test["working-directory"] == "apps/web", CI["jobs"]["web"]["steps"]


@pytest.mark.skipif(not shutil.which("make"), reason="make is not installed")
def test_make_check_runs_lint_unit_web_and_stub_e2e():
    dry_run = subprocess.run(["make", "-n", "check"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    for step in ("ruff check", "pytest tests", "-C apps/web test", "scripts/e2e_demo.py --stub"):
        assert step in dry_run, f"make check no longer runs {step!r}:\n{dry_run}"


def test_build_script_builds_and_pushes_every_container(tmp_path):
    """Its node list is containers/*/Dockerfile (it had 6 of 8), so it matches CI; docker is a recording fake."""
    (tmp_path / "docker").write_text('#!/bin/sh\necho "$@" >> "$FAKE_DOCKER_LOG"\n')
    (tmp_path / "docker").chmod(0o755)
    log = tmp_path / "docker.log"
    env = {k: v for k, v in os.environ.items() if k not in ("ORCHAPOD_IMAGE_PREFIX", "IMAGE_TAG")}
    env |= {"PATH": f"{tmp_path}:{os.environ['PATH']}", "FAKE_DOCKER_LOG": str(log)}
    subprocess.run(["bash", "scripts/build-and-push-containers.sh"], cwd=ROOT, env=env, check=True,
                   capture_output=True, timeout=60)
    calls = [line.split() for line in log.read_text().splitlines()]
    builds = [c for c in calls if c[0] == "build"]
    nodes = {c[c.index("-f") + 1].split("/")[1] for c in builds}
    assert nodes == {p.parent.name for p in (ROOT / "containers").glob("*/Dockerfile")}
    assert nodes == set(CI["jobs"]["containers"]["strategy"]["matrix"]["node"])
    images = {c[c.index("-t") + 1] for c in builds}
    assert images == {f"ghcr.io/bangadpurva/{n}:latest" for n in nodes}  # contracts R4: the registry CI pushes to
    assert images == {c[1] for c in calls if c[0] == "push"}
