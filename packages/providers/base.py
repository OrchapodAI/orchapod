"""
packages/providers/base.py

GPUProvider Protocol — the contract every provider adapter must implement.
Adding a new provider = implement this Protocol + register in PROVIDERS dict.
Target: 3-day task per new provider (Hyperstack, Lambda, Salad, etc.)
"""

from __future__ import annotations
import hashlib
import os
import random
import time
from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable

import httpx


@dataclass
class GPUSpec:
    """Parsed GPU requirement from workflow YAML resources block."""
    gpu_type: str        # e.g. "H100", "A100", "4090"
    count: int = 1       # number of GPUs
    vram_gb: int = 80    # minimum VRAM


@dataclass
class Quote:
    provider: str
    price_per_hour: float
    available: bool
    gpu_type: str
    region: str | None = None
    note: str | None = None  # e.g. "spot — may be interrupted"


@dataclass
class Pod:
    provider: str
    pod_id: str
    public_ip: str | None = None
    public_port: int | None = None  # for vllm-serve TCP exposure


@runtime_checkable
class GPUProvider(Protocol):
    name: str

    async def quote(self, gpu_spec: GPUSpec) -> Quote:
        """
        Return current price + availability for the requested spec.
        Called before every run to show cost estimate to the user.
        """
        ...

    async def provision(
        self,
        gpu_spec: GPUSpec,
        image: str,
        env: dict[str, str],
        ports: list[int] = [],
    ) -> Pod:
        """
        Provision a GPU pod, pull the container image, start it.
        Returns when the container is running (not when it completes).
        Raises: ProvisionError if no capacity or image pull fails.
        ports: TCP ports to expose publicly (e.g. [8000] for vllm-serve).
        """
        ...

    async def stream_logs(self, pod: Pod) -> AsyncIterator[str]:
        """
        Yield log lines from the running container.
        Used to stream logs via SSE to the frontend run viewer.
        """
        ...

    async def wait(self, pod: Pod) -> int:
        """
        Block until the container exits.
        Returns the exit code (0 = success).
        """
        ...

    async def terminate(self, pod: Pod) -> None:
        """
        Terminate and deallocate the pod.
        Called after every node completes (except vllm-serve which stays alive).
        """
        ...


class ProvisionError(Exception):
    """Raised when a provider cannot fulfill a GPU request."""
    pass


class NoCapacity(Exception):
    """Raised when no provider has available GPUs matching the spec."""
    pass


# --- HTTP API clients (tokenfactory.py, tavily.py): one error, one retry policy, one STUB switch ---

class ProviderError(Exception):
    """kind ∈ rate_limit | quota | auth | bad_request | bad_output | unsupported | server.
    str() = "<provider> <kind> <status>: <message>", which the node logs as its last ERROR line."""

    def __init__(self, provider: str, kind: str, status: int | None, message: str):
        super().__init__(f"{provider} {kind} {status}: {message}")
        self.provider, self.kind, self.status, self.message = provider, kind, status, message


def http_client(stub_handler) -> httpx.Client:
    """STUB=1: answered in-process by `stub_handler` (no network). Otherwise connect 10 s, read 120 s."""
    if os.environ.get("STUB") == "1":
        return httpx.Client(transport=httpx.MockTransport(stub_handler))
    return httpx.Client(timeout=httpx.Timeout(120.0, connect=10.0))


def stub_hash(request: httpx.Request) -> str:
    """First 8 hex of sha256 of the request (multipart's random boundary removed, so uploads hash stably)."""
    boundary = request.headers.get("content-type", "").partition("boundary=")[2].encode()
    body = request.content.replace(boundary, b"") if boundary else request.content
    return hashlib.sha256(request.method.encode() + request.url.raw_path + body).hexdigest()[:8]


def _kind(status: int) -> str:
    if status == 429:
        return "rate_limit"
    if status in (401, 403):
        return "auth"
    if status in (402, 432, 433):  # 432/433: Tavily plan and pay-as-you-go limits
        return "quota"
    return "server" if status >= 500 else "bad_request"


def request(http: httpx.Client, provider: str, method: str, url: str, *, create: bool = False,
            stream: bool = False, **kwargs) -> httpx.Response:
    """Send with up to 3 retries on 429 (Retry-After, capped at 60 s), 500/502/503/504, timeouts and connection
    errors, backing off 1, 2, 4 s plus up to 1 s of jitter. A create retries only on 429 and connect errors, so a
    lost response never starts a second paid job. stream=True returns the open response (the caller closes it)."""
    for attempt in range(4):
        wait = None
        try:
            resp = http.send(http.build_request(method, url, **kwargs), stream=stream)
            if resp.is_success:
                return resp
            resp.read()
        except httpx.TransportError as e:
            err = ProviderError(provider, "server", None, repr(e))
            if create and not isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)):  # it may have landed
                raise err from e
        else:
            err = ProviderError(provider, _kind(resp.status_code), resp.status_code, resp.text[:500])
            if resp.status_code == 429:
                try:
                    wait = min(max(float(resp.headers.get("retry-after", "")), 0.0), 60.0)
                except ValueError:
                    pass
            elif create or resp.status_code not in (500, 502, 503, 504):
                raise err
        if attempt == 3:
            raise err
        time.sleep(wait if wait is not None else 2 ** attempt + random.random())
