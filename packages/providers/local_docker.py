"""
packages/providers/local_docker.py — KAN-10-followup

Local-Docker provider that runs CPU node containers via `docker run` on the
host instead of provisioning a remote GPU pod. Implements the same
GPUProvider Protocol so the executor can pick it transparently for any node
whose `runtime` is `"cpu"` in NODE_REGISTRY.

Why this exists:
  - The MVP plan punted local execution. KAN-6 added a one-off short-circuit
    for the file-upload node, but every other CPU node (hf-import, data-prep,
    s3-import, auto-label-cleanlab, synth-distilabel, quantize) was routed
    to the GPU provider path — which crashes when no GPU SDK / API key is
    installed, and is wasteful when CPU is what we actually want.
  - With this provider in place, you can click Run on the canvas and any CPU
    workflow finishes locally with no GPU provider configured.

Contract assumptions:
  - Image: `orchapod/<node-type>:dev` when built locally, else
    `${ORCHAPOD_IMAGE_PREFIX:-ghcr.io/bangadpurva}/<node-type>:latest`, which
    docker pulls (contracts "Images, LocalDocker").
  - The control plane and MinIO are reachable from inside the container via
    `host.docker.internal` (Docker Desktop default on macOS/Windows; works
    via `--add-host=host.docker.internal:host-gateway` on Linux).
  - We never log decrypted secrets — the env dict is passed straight to
    docker without echoing it.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
from typing import AsyncIterator

from packages.providers.base import GPUSpec, Pod, ProvisionError, Quote


log = logging.getLogger("orchapod.local_docker")


# Translate dev-host references inside env vars so the container can reach them.
# The api/host runs on `localhost`, but inside a container `localhost` is the
# container itself — `host.docker.internal` is the bridge.
_HOST_REWRITES = (
    ("http://localhost:", "http://host.docker.internal:"),
    ("http://127.0.0.1:", "http://host.docker.internal:"),
    ("https://localhost:", "https://host.docker.internal:"),
    ("https://127.0.0.1:", "https://host.docker.internal:"),
)


def _rewrite_localhost(value: str) -> str:
    """Rewrite any localhost URL to host.docker.internal so the container can
    reach the dev MinIO + API. Untouched if the value already points at a
    real hostname (production R2, etc.)."""
    if not isinstance(value, str):
        return value
    for old, new in _HOST_REWRITES:
        if value.startswith(old):
            return new + value[len(old):]
    return value


def _rewrite_env(env: dict[str, str]) -> dict[str, str]:
    return {k: _rewrite_localhost(v) for k, v in env.items()}


def _resolve_image(image: str) -> str:
    """`orchapod/<type>:dev` if built locally, else `${ORCHAPOD_IMAGE_PREFIX:-ghcr.io/bangadpurva}/<type>:latest`."""
    node_type = image.rsplit("/", 1)[-1].split(":", 1)[0]
    if _image_exists(f"orchapod/{node_type}:dev"):
        return f"orchapod/{node_type}:dev"
    return f"{os.environ.get('ORCHAPOD_IMAGE_PREFIX') or 'ghcr.io/bangadpurva'}/{node_type}:latest"


def _image_exists(tag: str) -> bool:
    """Check `docker image inspect` synchronously — only used at provision time."""
    if shutil.which("docker") is None:
        return False
    proc = os.popen(f"docker image inspect {shlex.quote(tag)} >/dev/null 2>&1; echo $?")
    try:
        return proc.read().strip() == "0"
    finally:
        proc.close()


class LocalDockerProvider:
    """In-process docker-cli wrapper. Implements the GPUProvider Protocol."""

    name = "local-docker"

    async def quote(self, gpu_spec: GPUSpec) -> Quote:  # noqa: ARG002
        """Local Docker is always free + always available (no GPU)."""
        return Quote(
            provider=self.name,
            price_per_hour=0.0,
            available=True,
            gpu_type="cpu",
            note="local docker (host CPU)",
        )

    async def provision(
        self,
        gpu_spec: GPUSpec,  # noqa: ARG002 — local docker has no GPU spec
        image: str,
        env: dict[str, str],
    ) -> Pod:
        """Start the container detached and return its container_id as the pod_id.

        Adds `--add-host=host.docker.internal:host-gateway` so the same
        addressability works on Linux without Docker Desktop. Rewrites env
        URLs in `env` so the container can reach the host's localhost
        services.
        """
        if shutil.which("docker") is None:
            raise ProvisionError(
                "docker CLI not found on PATH — install Docker Desktop or daemon."
            )

        resolved_image = _resolve_image(image)
        rewritten_env = _rewrite_env(env)

        # `-d` returns the id at once. No `--rm`: a container that exits fast would be gone before `docker wait`
        # reads its code; `terminate` (which the executor also runs after `wait`) removes it.
        argv = [
            "docker", "run", "-d",
            "--add-host=host.docker.internal:host-gateway",
            # the API's startup sweep finds the containers it started by these (a teardown in flight dies with the process)
            "--label", f"orchapod.run_id={env.get('ORCHAPOD_RUN_ID', '')}",
            "--label", f"orchapod.control_url={env.get('ORCHAPOD_CONTROL_URL', '')}",
        ]
        for k, v in rewritten_env.items():
            argv += ["-e", f"{k}={v}"]
        argv.append(resolved_image)

        log.info("LocalDockerProvider: starting %s (image=%s)", " ".join(argv[:3]), resolved_image)
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise ProvisionError(
                f"docker run failed (exit={proc.returncode}): "
                f"{(stderr or b'').decode('utf-8', errors='replace').strip()}"
            )
        container_id = stdout.decode("utf-8", errors="replace").strip()
        if not container_id:
            raise ProvisionError("docker run returned empty container id")
        log.info("LocalDockerProvider: container started id=%s", container_id[:12])
        return Pod(provider=self.name, pod_id=container_id)

    async def stream_logs(self, pod: Pod) -> AsyncIterator[str]:
        """Yield log lines until the container exits or we're cancelled."""
        proc = await asyncio.create_subprocess_exec(
            "docker", "logs", "-f", pod.pod_id,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            while True:
                if proc.stdout is None:
                    break
                line = await proc.stdout.readline()
                if not line:
                    break
                yield line.decode("utf-8", errors="replace").rstrip("\n")
        finally:
            if proc.returncode is None:
                try:
                    proc.terminate()
                    await proc.wait()
                except ProcessLookupError:
                    pass

    async def wait(self, pod: Pod) -> int:
        """Block until the container exits; return its exit code."""
        proc = await asyncio.create_subprocess_exec(
            "docker", "wait", pod.pod_id,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:  # an unread exit code is a failure, never a success
            raise ProvisionError(f"docker wait failed: {(stderr or b'').decode('utf-8', errors='replace').strip()}")
        try:
            return int(stdout.decode("utf-8").strip())
        except ValueError:
            return 1

    async def terminate(self, pod: Pod) -> None:
        """SIGTERM, 30 s grace, then SIGKILL (`docker stop -t 30`), then `docker rm -f`; after `wait` it only removes
        the exited container. Best-effort: exit codes are ignored."""
        for argv in (("docker", "stop", "-t", "30", pod.pod_id), ("docker", "rm", "-f", pod.pod_id)):
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
