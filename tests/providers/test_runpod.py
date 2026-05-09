"""
tests/providers/test_runpod.py

Unit tests for the RunPod provider.
All RunPod SDK and HTTP calls are mocked — no real API key needed.
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from packages.providers.base import Pod, GPUSpec, ProvisionError
from packages.providers.runpod import RunPodProvider, _pod_state, _extract_ip


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def provider():
    with patch.dict(os.environ, {"RUNPOD_API_KEY": "test-key"}):
        with patch("packages.providers.runpod.runpod"):
            return RunPodProvider(api_key="test-key")


def make_pod(pod_id: str = "pod-123") -> Pod:
    return Pod(provider="runpod", pod_id=pod_id)


# ── _pod_state ────────────────────────────────────────────────────────────────

def test_pod_state_desired_status():
    assert _pod_state({"desiredStatus": "running"}) == "RUNNING"


def test_pod_state_status_fallback():
    assert _pod_state({"status": "exited"}) == "EXITED"


def test_pod_state_empty():
    assert _pod_state({}) == ""


# ── _extract_ip ───────────────────────────────────────────────────────────────

def test_extract_ip_from_ports():
    info = {"runtime": {"ports": [{"isIpPublic": True, "ip": "1.2.3.4"}]}}
    assert _extract_ip(info) == "1.2.3.4"


def test_extract_ip_missing():
    assert _extract_ip({}) is None


# ── quote ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_quote_uses_live_data(provider):
    gpu_types = [
        {"id": "NVIDIA H100 80GB HBM3", "secureCloud": True, "securePrice": 2.49}
    ]
    with patch("packages.providers.runpod.runpod.get_gpus", return_value=gpu_types):
        q = await provider.quote(GPUSpec(gpu_type="H100"))

    assert q.price_per_hour == 2.49
    assert q.available is True
    assert q.provider == "runpod"


@pytest.mark.asyncio
async def test_quote_falls_back_on_api_error(provider):
    with patch("packages.providers.runpod.runpod.get_gpus", side_effect=Exception("network")):
        q = await provider.quote(GPUSpec(gpu_type="H100"))

    assert q.price_per_hour == 2.49   # hardcoded fallback
    assert "estimated" in (q.note or "")


# ── provision ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_provision_waits_for_running(provider):
    """Provision resolves once the pod reaches RUNNING."""
    call_count = 0

    def fake_get_pod(pod_id):
        nonlocal call_count
        call_count += 1
        # First two polls return CREATED, third returns RUNNING
        if call_count < 3:
            return {"desiredStatus": "CREATED"}
        return {"desiredStatus": "RUNNING", "runtime": {"ports": []}}

    with patch("packages.providers.runpod.runpod.create_pod", return_value={"id": "pod-abc"}), \
         patch("packages.providers.runpod.runpod.get_pod", side_effect=fake_get_pod), \
         patch("packages.providers.runpod.PROVISION_POLL_S", 0):   # no sleep in tests

        pod = await provider.provision(
            gpu_spec=GPUSpec(gpu_type="H100"),
            image="ghcr.io/orchapod/unsloth-train:latest",
            env={"KEY": "value"},
        )

    assert pod.pod_id == "pod-abc"
    assert call_count == 3


@pytest.mark.asyncio
async def test_provision_raises_if_pod_goes_dead(provider):
    with patch("packages.providers.runpod.runpod.create_pod", return_value={"id": "pod-dead"}), \
         patch("packages.providers.runpod.runpod.get_pod", return_value={"desiredStatus": "DEAD"}), \
         patch("packages.providers.runpod.PROVISION_POLL_S", 0):

        with pytest.raises(ProvisionError, match="terminal state"):
            await provider.provision(
                gpu_spec=GPUSpec(gpu_type="H100"),
                image="ghcr.io/orchapod/unsloth-train:latest",
                env={},
            )


@pytest.mark.asyncio
async def test_provision_raises_on_timeout(provider):
    import time
    start = time.monotonic()

    with patch("packages.providers.runpod.runpod.create_pod", return_value={"id": "pod-slow"}), \
         patch("packages.providers.runpod.runpod.get_pod", return_value={"desiredStatus": "CREATED"}), \
         patch("packages.providers.runpod.PROVISION_POLL_S", 0), \
         patch("packages.providers.runpod.PROVISION_TIMEOUT_S", 0):  # instant timeout

        with pytest.raises(ProvisionError, match="did not reach RUNNING"):
            await provider.provision(
                gpu_spec=GPUSpec(gpu_type="H100"),
                image="ghcr.io/orchapod/unsloth-train:latest",
                env={},
            )


# ── wait ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wait_returns_0_on_exited(provider):
    states = iter([
        {"desiredStatus": "RUNNING"},
        {"desiredStatus": "RUNNING"},
        {"desiredStatus": "EXITED"},
    ])

    with patch("packages.providers.runpod.runpod.get_pod", side_effect=lambda _: next(states)), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        code = await provider.wait(make_pod())

    assert code == 0


@pytest.mark.asyncio
async def test_wait_returns_1_on_dead(provider):
    with patch("packages.providers.runpod.runpod.get_pod", return_value={"desiredStatus": "DEAD"}), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        code = await provider.wait(make_pod())

    assert code == 1


@pytest.mark.asyncio
async def test_wait_retries_on_api_error(provider):
    call_count = 0

    def flaky_get_pod(_):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("timeout")
        return {"desiredStatus": "EXITED"}

    with patch("packages.providers.runpod.runpod.get_pod", side_effect=flaky_get_pod), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        code = await provider.wait(make_pod())

    assert code == 0
    assert call_count == 3


# ── stream_logs ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_logs_yields_new_lines(provider):
    log_responses = [
        "line 1\nline 2\n",
        "line 1\nline 2\nline 3\n",   # line 3 is new
        "line 1\nline 2\nline 3\n",   # no new content
    ]
    pod_responses = [
        {"desiredStatus": "RUNNING"},
        {"desiredStatus": "RUNNING"},
        {"desiredStatus": "EXITED"},
    ]

    log_iter = iter(log_responses)
    pod_iter = iter(pod_responses)

    async def fake_fetch_logs(_):
        return next(log_iter)

    with patch.object(provider, "_fetch_logs", side_effect=fake_fetch_logs), \
         patch("packages.providers.runpod.runpod.get_pod", side_effect=lambda _: next(pod_iter)), \
         patch("asyncio.sleep", new_callable=AsyncMock):

        lines = [line async for line in provider.stream_logs(make_pod())]

    assert "line 1" in lines
    assert "line 2" in lines
    assert "line 3" in lines
    # No duplicates
    assert lines.count("line 1") == 1


@pytest.mark.asyncio
async def test_stream_logs_stops_on_terminal_state(provider):
    async def fake_fetch_logs(_):
        return "done\n"

    with patch.object(provider, "_fetch_logs", side_effect=fake_fetch_logs), \
         patch("packages.providers.runpod.runpod.get_pod", return_value={"desiredStatus": "EXITED"}), \
         patch("asyncio.sleep", new_callable=AsyncMock):

        lines = [line async for line in provider.stream_logs(make_pod())]

    # Generator must terminate
    assert len(lines) >= 1


# ── terminate ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_terminate_calls_sdk(provider):
    with patch("packages.providers.runpod.runpod.terminate_pod") as mock_term:
        await provider.terminate(make_pod("pod-xyz"))
    mock_term.assert_called_once_with("pod-xyz")
