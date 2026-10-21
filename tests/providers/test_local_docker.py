"""LocalDockerProvider: image resolution and graceful terminate; the exit-code test needs a docker daemon."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from unittest.mock import AsyncMock

import pytest

from packages.providers import local_docker
from packages.providers.base import Pod, ProvisionError
from packages.providers.local_docker import LocalDockerProvider, _resolve_image


def test_local_dev_image_wins_when_built(monkeypatch):
    monkeypatch.setattr(local_docker, "_image_exists", lambda tag: tag == "orchapod/data-prep:dev")
    assert _resolve_image("ghcr.io/bangadpurva/data-prep:latest") == "orchapod/data-prep:dev"


def test_otherwise_the_registry_ref_under_the_image_prefix(monkeypatch):
    monkeypatch.setattr(local_docker, "_image_exists", lambda tag: False)
    monkeypatch.delenv("ORCHAPOD_IMAGE_PREFIX", raising=False)
    assert _resolve_image("ghcr.io/orchapod/data-prep:latest") == "ghcr.io/bangadpurva/data-prep:latest"
    monkeypatch.setenv("ORCHAPOD_IMAGE_PREFIX", "")  # .env.example ships blanks: blank = the default
    assert _resolve_image("ghcr.io/orchapod/data-prep:latest") == "ghcr.io/bangadpurva/data-prep:latest"
    monkeypatch.setenv("ORCHAPOD_IMAGE_PREFIX", "registry.example/team")
    assert _resolve_image("ghcr.io/bangadpurva/data-prep:latest") == "registry.example/team/data-prep:latest"


async def test_terminate_sends_sigterm_with_30s_grace_then_removes(monkeypatch):
    argvs = []

    async def fake_exec(*argv, **kwargs):
        argvs.append(argv)
        proc = AsyncMock()
        proc.communicate.return_value = (b"", b"")
        return proc

    monkeypatch.setattr(local_docker.asyncio, "create_subprocess_exec", fake_exec)
    await LocalDockerProvider().terminate(Pod(provider="local-docker", pod_id="c0ffee"))
    assert argvs == [("docker", "stop", "-t", "30", "c0ffee"), ("docker", "rm", "-f", "c0ffee")]


async def test_an_unreadable_exit_code_fails_instead_of_reading_as_success(monkeypatch):
    async def fake_exec(*argv, **kwargs):
        proc = AsyncMock(returncode=1)
        proc.communicate.return_value = (b"", b"Error response from daemon: No such container: c0ffee\n")
        return proc

    monkeypatch.setattr(local_docker.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(ProvisionError, match="docker wait failed"):
        await LocalDockerProvider().wait(Pod(provider="local-docker", pod_id="c0ffee"))


async def test_a_container_that_fails_at_once_keeps_its_exit_code_until_terminate(monkeypatch):
    """With auto-remove, such a container was gone before `docker wait` and the node read as succeeded."""
    if not shutil.which("docker") or subprocess.run(["docker", "info"], capture_output=True).returncode:
        pytest.skip("needs a docker daemon")
    tag = "orchapod-test/exit1:latest"  # throwaway: alpine whose command exits 1
    try:
        subprocess.run(["docker", "build", "-q", "-t", tag, "-"], input=b'FROM alpine:latest\nCMD ["false"]\n',
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        pytest.skip(f"cannot build the throwaway image: {e.stderr.decode(errors='replace')[-200:]}")
    monkeypatch.setattr(local_docker, "_resolve_image", lambda image: tag)
    provider, pod = LocalDockerProvider(), None
    try:
        pod = await provider.provision(None, "exit1", {})
        await asyncio.sleep(1)  # the executor commits and starts the log stream before it waits
        assert await provider.wait(pod) == 1
    finally:
        if pod:
            await provider.terminate(pod)
        subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)
    assert subprocess.run(["docker", "inspect", pod.pod_id], capture_output=True).returncode  # removed
