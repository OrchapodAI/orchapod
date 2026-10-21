"""Nebius AI Cloud Serverless (docs/contracts.md "NebiusServerless"): Jobs and Endpoints over REST, and NebiusProvider,
the GPUProvider that runs gpu nodes as Jobs.

    endpoint_id = NebiusServerless().endpoints.create(name, image, args=..., env={}, platform=..., preset=..., auth_token=...)

https://api.nebius.cloud/ai/v1 is a REST gateway over the gRPC protos in https://github.com/nebius/api
(nebius/ai/v1/job*.proto, endpoint*.proto), so bodies are those messages in proto3 JSON (camelCase), and errors are gRPC
codes as HTTP statuses (https://docs.nebius.com/rest-api/errors). Routes and bodies are from
https://docs.nebius.com/serverless/jobs/manage and /serverless/endpoints/manage; "proto" marks a field that only the
.proto names. `metadata.name` is unique per project and kind (both services have GetByName), so list() finds a create
whose reply was lost (R19). STUB=1 answers offline.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
import subprocess
import time
from collections.abc import AsyncIterator
from datetime import datetime

import httpx

from orchapod.prices import PRICES
from packages.providers.base import (GPUSpec, Pod, ProviderError, ProvisionError, Quote, http_client, json_of, request,
                                     stub_hash)

AI_BASE = "https://api.nebius.cloud/ai/v1"
P = "nebius_serverless"
GIB = 2 ** 30
PLATFORMS = {"H100": ("gpu-h100-sxm", "1gpu-16vcpu-200gb"), "L40S": ("gpu-l40s-a", "1gpu-8vcpu-32gb")}
log = logging.getLogger("orchapod.nebius")


class NebiusServerless:
    """Parent NEBIUS_PROJECT_ID, bearer NEBIUS_IAM_TOKEN; http is an httpx.Client (tests pass one on httpx.MockTransport)."""

    def __init__(self, *, http: httpx.Client | None = None):
        self.project = os.environ.get("NEBIUS_PROJECT_ID", "").strip()
        self.token = os.environ.get("NEBIUS_IAM_TOKEN", "").strip()
        self.stub = os.environ.get("STUB") == "1"
        self.http = http_client(_stub) if self.stub or http is None else http  # STUB never touches the network
        self.jobs, self.endpoints = _Jobs(self, "jobs"), _Endpoints(self, "endpoints")

    def _call(self, method: str, path: str, *, create: bool = False, **kwargs) -> dict:
        """The reply's JSON object. An empty token, or a 401, runs `nebius iam get-access-token` once and sends the
        call again: a 401 (UNAUTHENTICATED) is refused before anything runs, so even a create may go again."""
        renewed = False
        if not self.token and not self.stub:
            self._renew()
            renewed = True
        while True:
            try:
                return json_of(request(self.http, P, method, AI_BASE + path, create=create,
                                       headers={"Authorization": f"Bearer {self.token}"}, **kwargs), P)
            except ProviderError as e:
                if e.status != 401 or renewed:
                    raise
                self._renew()
                renewed = True

    def _renew(self) -> None:
        """R15: the CLI's profile on the host signs the token (12 h); no CLI or no token → ProviderError auth."""
        cli = shutil.which("nebius")
        if cli is None:
            raise ProviderError(P, "auth", None, "NEBIUS_IAM_TOKEN is empty or expired and the nebius CLI is not "
                                                 "installed to renew it (nebius iam get-access-token)")
        try:
            out = subprocess.run([cli, "iam", "get-access-token"], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as e:
            raise ProviderError(P, "auth", None, f"nebius iam get-access-token: {e}") from e
        if out.returncode or not out.stdout.strip():
            raise ProviderError(P, "auth", None, f"nebius iam get-access-token exited {out.returncode}: "
                                                 f"{out.stderr.strip()[-300:]}")
        self.token = out.stdout.strip()

    def _parent(self) -> str:
        if not self.project and not self.stub:
            raise ProviderError(P, "bad_request", None, "NEBIUS_PROJECT_ID is not set")
        return self.project


class _Kind:
    """Routes shared by jobs and endpoints: POST and GET ?parentId= on /ai/v1/<kind>, GET and DELETE on /<kind>/<id>."""

    def __init__(self, client: NebiusServerless, kind: str):
        self._c, self._kind = client, kind

    def _create(self, name, image, args, env, platform, preset, volumes, **extra) -> str:
        """The new resource's id: the Operation's resourceId. A reply without one is bad_output, and the resource may
        exist all the same: the caller finds it by name with list()."""
        spec = {"image": image, "args": args, "platform": platform, "preset": preset,
                "environmentVariables": [{"name": k, "value": v} for k, v in env.items() if v],
                "volumes": [_volume(v) for v in volumes],
                "disk": {"type": "NETWORK_SSD", "sizeBytes": str(250 * GIB)}, "shmSizeBytes": str(16 * GIB), **extra}
        reply = self._c._call("POST", f"/{self._kind}", create=True,
                              json={"metadata": {"parentId": self._c._parent(), "name": name}, "spec": spec})
        if not reply.get("resourceId"):  # never echo the reply: its `request` may carry the env values
            raise ProviderError(P, "bad_output", 200, f"{self._kind} create {name}: operation {reply.get('id')} "
                                                      "names no resourceId")
        return reply["resourceId"]

    def get(self, id: str) -> dict:
        """{id, name, state, url, code, message}"""
        return _view(self._c._call("GET", f"/{self._kind}/{id}"))

    def list(self) -> list[dict]:
        """Every one in the project as get() views, all pages, newest first by metadata.createdAt (the List call has no
        order). Match `name` to find a create whose reply was lost."""
        items, page = [], {}
        while True:
            reply = self._c._call("GET", f"/{self._kind}", params={"parentId": self._c._parent(), **page})
            items += reply.get("items") or []
            if not reply.get("nextPageToken"):
                break
            page = {"pageToken": reply["nextPageToken"]}  # proto ListJobsRequest.page_token
        items.sort(key=lambda i: datetime.fromisoformat(i["metadata"].get("createdAt") or "1970-01-01T00:00:00Z"),
                   reverse=True)
        return [_view(i) for i in items]

    def delete(self, id: str) -> None:
        """A 404 is done: it is gone already."""
        try:
            self._c._call("DELETE", f"/{self._kind}/{id}")
        except ProviderError as e:
            if e.status != 404:
                raise


class _Jobs(_Kind):
    def create(self, name: str, image: str, *, args: str = "", env: dict[str, str], platform: str, preset: str,
               volumes=()) -> str:
        """spec.timeout 3600 s: the CLAUDE.md cap and Nebius's minimum (the default is 24 h)."""
        return self._create(name, image, args, env, platform, preset, volumes, timeout="3600s")

    def cancel(self, id: str) -> None:
        """Stops the VM; the job stays listed until deleted. Refused once the job has ended."""
        self._c._call("POST", "/jobs/cancel", json={"id": id})


class _Endpoints(_Kind):
    def create(self, name: str, image: str, *, args: str = "", env: dict[str, str], platform: str, preset: str,
               port: int = 8000, auth_token: str, volumes=()) -> str:
        """One HTTP port, served at the endpoint's managed https URL behind auth_token."""
        if not auth_token:  # Nebius disables authentication without one: an open, paid GPU endpoint
            raise ProviderError(P, "bad_request", None, f"endpoint {name} needs an auth_token")
        return self._create(name, image, args, env, platform, preset, volumes,
                            ports=[{"containerPort": port, "protocol": "HTTP"}], authToken=auth_token)


def _view(item: dict) -> dict:
    """url = the first https public endpoint (http only in STUB), None until RUNNING; code and message =
    status.stateDetails (proto), the cause of FAILED or ERROR."""
    meta, status = item.get("metadata") or {}, item.get("status") or {}
    details = status.get("stateDetails") or {}
    urls = [u for u in status.get("publicEndpoints") or [] if u.startswith(("https://", "http://"))]
    return {"id": meta.get("id"), "name": meta.get("name"), "state": status.get("state"),
            "url": urls[0] if urls and status.get("state") == "RUNNING" else None,
            "code": details.get("code"), "message": details.get("message")}


def _volume(volume: str) -> dict:
    """"s3://<bucket>:<container_path>:ro|rw", the CLI's --volume form, → a VolumeMount of our bucket with s3Config
    (proto VolumeMount.S3Config) from ORCHAPOD_R2_*."""
    m = re.fullmatch(r"s3://([^:/]+):(/[^:]*):(ro|rw)", volume)
    if not m:
        raise ProviderError(P, "bad_request", None, f"volume {volume!r} is not s3://<bucket>:<container_path>:ro|rw")
    return {"source": f"s3://{m[1]}", "containerPath": m[2], "mode": "READ_ONLY" if m[3] == "ro" else "READ_WRITE",
            "s3Config": {"endpoint": os.environ.get("ORCHAPOD_R2_ENDPOINT", ""),
                         "region": os.environ.get("ORCHAPOD_R2_REGION", ""),
                         "credentials": {"accessKeyId": os.environ.get("ORCHAPOD_R2_ACCESS_KEY", ""),
                                         "secretAccessKey": os.environ.get("ORCHAPOD_R2_SECRET_KEY", "")}}}


def _platform(gpu_spec: GPUSpec) -> tuple[str, str]:
    if gpu_spec.count != 1 or gpu_spec.gpu_type not in PLATFORMS:
        raise LookupError(f"Nebius jobs run 1xH100 or 1xL40S, not {gpu_spec.count}x{gpu_spec.gpu_type}")
    return PLATFORMS[gpu_spec.gpu_type]


class NebiusProvider:
    """GPUProvider "nebius": a gpu node runs as one Serverless Job. The sync client runs in worker threads."""

    name = "nebius"

    def __init__(self, *, http: httpx.Client | None = None):
        self.client = NebiusServerless(http=http)

    async def quote(self, gpu_spec: GPUSpec) -> Quote:
        platform, _ = _platform(gpu_spec)
        price = PRICES["nebius_serverless"].get(platform)  # the one table (R5/R16)
        if price is None:  # unpriced fails closed
            raise LookupError(f"no price for nebius_serverless {platform} in orchapod.prices.PRICES")
        return Quote(provider=self.name, price_per_hour=price, available=True, gpu_type=platform,
                     note="Nebius AI Cloud Serverless Job")

    async def provision(self, gpu_spec: GPUSpec, image: str, env: dict[str, str]) -> Pod:
        """jobs.create under a name unique to this attempt; after a lost reply the job is adopted by that name."""
        platform, preset = _platform(gpu_spec)
        for key in ("ORCHAPOD_CONTROL_URL", "ORCHAPOD_R2_ENDPOINT"):  # the job reaches both from Nebius
            if not (env.get(key) or "").startswith("https://"):
                raise ProvisionError(f"{key} must be a public https URL for a Nebius job, not {env.get(key)!r}")
        name = re.sub(r"[^a-z0-9-]+", "-", f"orchapod-{env.get('ORCHAPOD_RUN_ID', '')[:8]}-{int(time.time())}-"
                                           f"{env.get('ORCHAPOD_NODE_ID', 'node')}".lower())[:63].strip("-")
        try:
            job_id = await asyncio.to_thread(self.client.jobs.create, name, image, env=env, platform=platform,
                                             preset=preset)
        except ProviderError as e:
            if e.kind not in ("server", "bad_output"):  # refused: nothing was created
                raise
            found = [j["id"] for j in await asyncio.to_thread(self.client.jobs.list) if j["name"] == name]
            if not found:
                raise
            job_id = found[0]
        return Pod(provider=self.name, pod_id=job_id)

    async def wait(self, pod: Pod) -> int:
        """Polls every 15 s: COMPLETED → 0; FAILED, CANCELLED or ERROR → its code and message to this log, 1. A 5xx or
        429 that outlasts the client's retries is polled through, so an API blip never cancels a paid job."""
        while True:
            try:
                job = await asyncio.to_thread(self.client.jobs.get, pod.pod_id)
            except ProviderError as e:
                if e.kind not in ("server", "rate_limit"):
                    raise
                log.warning("nebius job %s: %s", pod.pod_id, e)
            else:
                if job["state"] == "COMPLETED":
                    return 0
                if job["state"] in ("FAILED", "CANCELLED", "ERROR"):
                    log.error("nebius job %s %s: %s %s", pod.pod_id, job["state"], job["code"], job["message"])
                    return 1
            await asyncio.sleep(15)

    async def terminate(self, pod: Pod) -> None:
        """Cancel (refused once the job has ended), then delete."""
        with contextlib.suppress(ProviderError):
            await asyncio.to_thread(self.client.jobs.cancel, pod.pod_id)
        await asyncio.to_thread(self.client.jobs.delete, pod.pod_id)

    async def stream_logs(self, pod: Pod) -> AsyncIterator[str]:
        """Nothing: Jobs have no REST logs, so nodes post theirs to ORCHAPOD_CONTROL_URL through the SDK."""
        return
        yield


def _stub(request: httpx.Request) -> httpx.Response:
    """STUB=1: an offline Serverless in the real reply shapes; jobs are COMPLETED, endpoints RUNNING at http://stub.invalid."""
    h, path = stub_hash(request), request.url.path
    kind = "aijob" if path.startswith("/ai/v1/jobs") else "aiendpoint"
    if path in ("/ai/v1/jobs", "/ai/v1/endpoints"):
        return httpx.Response(200, json={"id": f"aiop-stub-{h}", "resourceId": f"{kind}-stub-{h}"}
                              if request.method == "POST" else {"items": []})
    if request.method == "GET":
        job = kind == "aijob"
        return httpx.Response(200, json={"metadata": {"id": path.rsplit("/", 1)[1]}, "status": {
            "state": "COMPLETED" if job else "RUNNING", "publicEndpoints": [] if job else ["http://stub.invalid"]}})
    return httpx.Response(200, json={"id": f"aiop-stub-{h}"})  # cancel, delete: an Operation
