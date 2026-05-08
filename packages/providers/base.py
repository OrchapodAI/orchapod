"""
packages/providers/base.py

GPUProvider Protocol — the contract every provider adapter must implement.
Adding a new provider = implement this Protocol + register in PROVIDERS dict.
Target: 3-day task per new provider (Hyperstack, Lambda, Salad, etc.)
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import AsyncIterator, Protocol, runtime_checkable


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
