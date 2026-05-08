"""
packages/providers/vastai.py

Vast.ai GPU provider — primary provider for Orchapod testing/development.

API: https://console.vast.ai/api/v0/
Auth: Bearer token via VASTAI_API_KEY env var

Instance lifecycle:
  GET /bundles/            → find cheapest offer
  PUT /asks/{offer_id}/   → create instance (returns new_contract.id)
  GET /instances/{id}/    → poll actual_status until "running"
  GET /instances/request_logs/{id}/ → stream logs
  GET /instances/{id}/    → poll until "exited" | "offline"
  DELETE /instances/{id}/ → cleanup

GPU naming: Vast.ai uses underscore style (H100_SXM5, A100_SXM4_80GB).
Bid price: on-demand uses 115% of listed dph_total to ensure acquisition.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import AsyncIterator

import httpx

from .base import GPUProvider, GPUSpec, Quote, Pod, ProvisionError

_BASE = "https://console.vast.ai/api/v0"

# Map our canonical GPU names → Vast.ai gpu_name values
_GPU_MAP: dict[str, str] = {
    "H100":           "H100_SXM5",
    "H100_SXM":       "H100_SXM5",
    "H100_SXM5":      "H100_SXM5",
    "H100_PCIE":      "H100_PCIE",
    "A100":           "A100_SXM4_80GB",
    "A100_80GB":      "A100_SXM4_80GB",
    "A100_40GB":      "A100_PCIE_40GB",
    "4090":           "RTX_4090",
    "RTX_4090":       "RTX_4090",
    "3090":           "RTX_3090",
    "RTX_3090":       "RTX_3090",
}

# Fallback prices (USD/hr) used when the API search fails
_FALLBACK_PRICES: dict[str, float] = {
    "H100_SXM5":      2.20,
    "H100_PCIE":      1.89,
    "A100_SXM4_80GB": 1.50,
    "A100_PCIE_40GB": 0.99,
    "RTX_4090":       0.55,
    "RTX_3090":       0.35,
}

_PROVISION_TIMEOUT = 600   # seconds to wait for "running" state
_PROVISION_POLL    = 10    # seconds between status polls during provision
_WAIT_POLL         = 15    # seconds between polls while container runs
_LOG_POLL          = 3     # seconds between log fetches


class VastAIProvider:
    name = "vastai"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ["VASTAI_API_KEY"]
        self._headers = {"Authorization": f"Bearer {self.api_key}"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _vast_gpu_name(self, gpu_spec: GPUSpec) -> str:
        return _GPU_MAP.get(gpu_spec.gpu_type, gpu_spec.gpu_type)

    @staticmethod
    def _env_str(env: dict[str, str]) -> str:
        """Convert env dict to Vast.ai's docker-flag env string."""
        parts = []
        for k, v in env.items():
            safe = str(v).replace("\n", " ").replace("\r", "")
            if any(c in safe for c in " \t'\"\\"):
                safe = '"' + safe.replace('"', '\\"') + '"'
            parts.append(f"-e {k}={safe}")
        return " ".join(parts)

    @staticmethod
    def _ports_str(ports: list[int]) -> str:
        """Convert list of port ints to Vast.ai ports string, e.g. '8000/tcp'."""
        return " ".join(f"{p}/tcp" for p in ports)

    async def _search_offers(
        self,
        client: httpx.AsyncClient,
        gpu_name: str,
        count: int,
    ) -> list[dict]:
        """Return available offers sorted cheapest first."""
        q = json.dumps({
            "gpu_name":  {"eq": gpu_name},
            "num_gpus":  {"gte": count},
            "rentable":  {"eq": True},
            "type":      "ask",
        })
        resp = await client.get(
            f"{_BASE}/bundles/",
            params={"q": q, "order": "dph_total+asc", "type": "ask"},
            headers=self._headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("offers", [])

    async def _get_instance(
        self,
        client: httpx.AsyncClient,
        instance_id: int,
    ) -> dict | None:
        resp = await client.get(
            f"{_BASE}/instances/{instance_id}/",
            headers=self._headers,
            timeout=30,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        instances = resp.json().get("instances", [])
        return instances[0] if instances else None

    async def _fetch_logs(
        self,
        client: httpx.AsyncClient,
        pod_id: str,
    ) -> str:
        resp = await client.get(
            f"{_BASE}/instances/request_logs/{pod_id}/",
            headers=self._headers,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.text
        return ""

    # ------------------------------------------------------------------
    # Protocol implementation
    # ------------------------------------------------------------------

    async def quote(self, gpu_spec: GPUSpec) -> Quote:
        gpu_name = self._vast_gpu_name(gpu_spec)
        async with httpx.AsyncClient() as client:
            try:
                offers = await self._search_offers(client, gpu_name, gpu_spec.count)
                if not offers:
                    return Quote(
                        provider=self.name,
                        price_per_hour=_FALLBACK_PRICES.get(gpu_name, 9.99),
                        available=False,
                        gpu_type=gpu_name,
                        note="no offers found",
                    )
                cheapest = offers[0]
                dph = float(cheapest.get("dph_total", 0)) * gpu_spec.count
                return Quote(
                    provider=self.name,
                    price_per_hour=round(dph, 4),
                    available=True,
                    gpu_type=gpu_name,
                    note="on-demand",
                )
            except Exception as exc:
                return Quote(
                    provider=self.name,
                    price_per_hour=_FALLBACK_PRICES.get(gpu_name, 9.99),
                    available=True,
                    gpu_type=gpu_name,
                    note=f"fallback price (api error: {exc})",
                )

    async def provision(
        self,
        gpu_spec: GPUSpec,
        image: str,
        env: dict[str, str],
        ports: list[int] = [],
    ) -> Pod:
        gpu_name = self._vast_gpu_name(gpu_spec)

        async with httpx.AsyncClient() as client:
            # 1. Find cheapest available offer
            offers = await self._search_offers(client, gpu_name, gpu_spec.count)
            if not offers:
                raise ProvisionError(
                    f"No Vast.ai offers for {gpu_name} ×{gpu_spec.count}"
                )
            offer = offers[0]
            offer_id = int(offer["id"])
            # Bid 15% above listed dph_total to ensure acquisition
            listed_dph = float(offer.get("dph_total", 0))
            bid_price = round(listed_dph * 1.15, 6)

            # 2. Create instance
            body: dict = {
                "client_id":       "me",
                "image":           image,
                "env":             self._env_str(env),
                "onstart":         "",
                "runtype":         "args",
                "args_str":        "",
                "use_jupyter_lab": False,
                "price":           bid_price,
                "disk":            50,
                "label":           "orchapod",
            }
            if ports:
                body["ports"] = self._ports_str(ports)

            resp = await client.put(
                f"{_BASE}/asks/{offer_id}/",
                headers=self._headers,
                json=body,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                raise ProvisionError(f"Vast.ai create_instance failed: {data}")

            instance_id = int(data["new_contract"]["id"])

            # 3. Poll until running (or terminal state)
            deadline = time.monotonic() + _PROVISION_TIMEOUT
            while time.monotonic() < deadline:
                instance = await self._get_instance(client, instance_id)
                if instance is None:
                    raise ProvisionError(
                        f"Vast.ai instance {instance_id} disappeared during provisioning"
                    )
                status = instance.get("actual_status", "")
                if status == "running":
                    return Pod(
                        provider=self.name,
                        pod_id=str(instance_id),
                        public_ip=instance.get("ssh_host") or instance.get("public_ipaddr"),
                        public_port=instance.get("ssh_port") or 22,
                    )
                if status in ("exited", "offline", "destroyed"):
                    raise ProvisionError(
                        f"Vast.ai instance {instance_id} entered '{status}' "
                        "before reaching running state"
                    )
                await asyncio.sleep(_PROVISION_POLL)

            raise ProvisionError(
                f"Vast.ai instance {instance_id} did not become running "
                f"within {_PROVISION_TIMEOUT}s"
            )

    async def stream_logs(self, pod: Pod) -> AsyncIterator[str]:
        """Poll the Vast.ai HTTP log endpoint, yielding new lines."""
        seen_lines = 0
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    text = await self._fetch_logs(client, pod.pod_id)
                    lines = text.splitlines()
                    for line in lines[seen_lines:]:
                        yield line
                    seen_lines = len(lines)
                except Exception:
                    pass

                try:
                    instance = await self._get_instance(client, int(pod.pod_id))
                    if instance and instance.get("actual_status") in (
                        "exited", "offline", "destroyed"
                    ):
                        text = await self._fetch_logs(client, pod.pod_id)
                        lines = text.splitlines()
                        for line in lines[seen_lines:]:
                            yield line
                        return
                except Exception:
                    pass

                await asyncio.sleep(_LOG_POLL)

    async def wait(self, pod: Pod) -> int:
        """Poll instance status until it exits. Returns exit code (0 = success)."""
        async with httpx.AsyncClient() as client:
            while True:
                try:
                    instance = await self._get_instance(client, int(pod.pod_id))
                    if instance is None:
                        return 1
                    status = instance.get("actual_status", "")
                    if status == "exited":
                        code = instance.get("exit_code")
                        return int(code) if code is not None else 0
                    if status in ("offline", "destroyed"):
                        return 1
                except Exception:
                    pass
                await asyncio.sleep(_WAIT_POLL)

    async def terminate(self, pod: Pod) -> None:
        """Destroy the Vast.ai instance (best-effort)."""
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.delete(
                    f"{_BASE}/instances/{pod.pod_id}/",
                    headers=self._headers,
                    timeout=30,
                )
                resp.raise_for_status()
            except Exception:
                pass  # best-effort; billing ends when status reaches "offline"


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

PROVIDERS: dict[str, GPUProvider] = {}


def register_providers(vastai_key: str = "") -> None:
    if vastai_key:
        PROVIDERS["vastai"] = VastAIProvider(api_key=vastai_key)


async def pick_provider(resources) -> GPUProvider:
    """Pick the first available provider from the resource preference list."""
    from .base import NoCapacity
    pref = getattr(resources, "provider_pref", None) or ["vastai"]
    for name in pref:
        provider = PROVIDERS.get(name)
        if provider is None:
            continue
        gpu_type = resources.gpu.split("x")[-1] if hasattr(resources, "gpu") else "H100"
        gpu_spec = GPUSpec(gpu_type=gpu_type, count=1)
        quote = await provider.quote(gpu_spec)
        if quote.available:
            return provider
    raise NoCapacity("No GPU provider has available capacity for this spec.")
