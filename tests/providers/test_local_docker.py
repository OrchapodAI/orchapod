"""LocalDockerProvider: image resolution and graceful terminate (no docker daemon needed)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from packages.providers import local_docker
from packages.providers.base import Pod
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
