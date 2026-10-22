"""Every container image builds from the repo root (ruling R19), so COPY sources are root-relative."""

import re
import shlex
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILES = sorted(ROOT.glob("containers/*/Dockerfile"))
NODES = pytest.mark.parametrize("dockerfile", DOCKERFILES, ids=lambda p: p.parent.name)


def copy_sources(dockerfile: Path) -> list[str]:
    """Build-context sources of every COPY/ADD (flags, `--from=` stages and URLs are not context files)."""
    out: list[str] = []
    for line in re.sub(r"\\[ \t]*\n", " ", dockerfile.read_text()).splitlines():
        if not re.match(r"\s*(COPY|ADD)\s", line, re.I) or "--from" in line:
            continue
        args = [a for a in shlex.split(line, comments=True)[1:] if not a.startswith("--")]
        out += [a for a in args[:-1] if "://" not in a]
    return out


def test_dockerfiles_found():
    assert DOCKERFILES


@NODES
def test_copy_sources_exist_inside_the_repo_root_context(dockerfile):
    bad = [
        s for s in copy_sources(dockerfile)
        if not (ROOT / s).resolve().is_relative_to(ROOT) or not any(ROOT.glob(s))
    ]
    assert not bad, f"not in the repo-root build context: {bad}"


@NODES
def test_copies_the_one_sdk_and_its_own_run_py(dockerfile):
    srcs = [s.rstrip("/") for s in copy_sources(dockerfile)]
    assert "packages/sdk-py/orchapod" in srcs
    assert f"containers/{dockerfile.parent.name}/run.py" in srcs


def test_no_vendored_sdk_copy():
    assert not list(ROOT.glob("containers/*/sdk")), "vendored SDK copy: COPY packages/sdk-py/orchapod instead"


def test_continuation_with_trailing_whitespace(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM x\nCOPY a \\ \t\n     b /dst/\nRUN true\n")
    assert copy_sources(tmp_path / "Dockerfile") == ["a", "b"]


def test_unsloth_train_has_a_slim_stub_stage_first_and_the_cuda_image_last():
    """STUB=1 needs only the SDK and run.py (its GPU imports are lazy), so the stub stack builds `--target stub` on any
    machine; the CUDA stage stays last, the default target that CI, the build script and Nebius Jobs get."""
    stages = re.split(r"(?m)^FROM\s+", (ROOT / "containers/unsloth-train/Dockerfile").read_text())[1:]
    stub, cuda = stages[0], stages[-1]
    assert re.match(r"python:3\.12-slim\s+AS\s+stub\s*\n", stub, re.I), stub.splitlines()[0]
    assert all(f"COPY {src} " in stub for src in ("packages/sdk-py/orchapod", "containers/unsloth-train/run.py"))
    assert "CMD" in stub and "requirements.lock" not in stub  # runnable, and none of the GPU stack
    assert len(stages) == 2 and re.match(r"pytorch/pytorch:\S*cuda", cuda)
