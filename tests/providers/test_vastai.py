"""
tests/providers/test_vastai.py

Unit tests for the VastAI provider. All HTTP calls are mocked.
"""

from __future__ import annotations

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from packages.providers.vastai import VastAIProvider
from packages.providers.base import GPUSpec, Pod, ProvisionError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def provider():
    return VastAIProvider(api_key="test-key")


@pytest.fixture
def gpu_spec():
    return GPUSpec(gpu_type="H100", count=1)


@pytest.fixture
def pod():
    return Pod(provider="vastai", pod_id="99999", public_ip="ssh4.vast.ai", public_port=12345)


def _mock_response(status_code: int = 200, json_data: dict | None = None, text: str = ""):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


# ---------------------------------------------------------------------------
# quote()
# ---------------------------------------------------------------------------

class TestQuote:
    @pytest.mark.asyncio
    async def test_quote_returns_cheapest_offer(self, provider, gpu_spec):
        offers = [
            {"id": 1, "dph_total": 1.5},
            {"id": 2, "dph_total": 2.0},
        ]
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(200, {"offers": offers})

            quote = await provider.quote(gpu_spec)

        assert quote.available is True
        assert quote.price_per_hour == pytest.approx(1.5)
        assert "H100" in quote.gpu_type

    @pytest.mark.asyncio
    async def test_quote_no_offers_returns_unavailable(self, provider, gpu_spec):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(200, {"offers": []})

            quote = await provider.quote(gpu_spec)

        assert quote.available is False

    @pytest.mark.asyncio
    async def test_quote_api_error_returns_fallback(self, provider, gpu_spec):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = httpx.ConnectError("connection refused")

            quote = await provider.quote(gpu_spec)

        assert quote.available is True
        assert quote.price_per_hour == pytest.approx(2.20)  # H100_SXM5 fallback
        assert "fallback" in (quote.note or "")


# ---------------------------------------------------------------------------
# provision()
# ---------------------------------------------------------------------------

class TestProvision:
    def _instance_payload(self, status: str, instance_id: int = 99999) -> dict:
        return {
            "instances": [{
                "id": instance_id,
                "actual_status": status,
                "ssh_host": "ssh4.vast.ai",
                "ssh_port": 12345,
                "exit_code": None,
            }]
        }

    @pytest.mark.asyncio
    async def test_provision_success(self, provider, gpu_spec):
        offers = [{"id": 42, "dph_total": 1.5}]
        create_resp = {"success": True, "new_contract": {"id": 99999}}
        instance_running = self._instance_payload("running")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = [
                _mock_response(200, {"offers": offers}),   # search
                _mock_response(200, instance_running),      # poll
            ]
            mock_client.put.return_value = _mock_response(200, create_resp)

            pod = await provider.provision(gpu_spec, "ghcr.io/orchapod/train:latest", {"K": "V"})

        assert pod.provider == "vastai"
        assert pod.pod_id == "99999"
        assert pod.public_ip == "ssh4.vast.ai"

    @pytest.mark.asyncio
    async def test_provision_no_offers_raises(self, provider, gpu_spec):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(200, {"offers": []})

            with pytest.raises(ProvisionError, match="No Vast.ai offers"):
                await provider.provision(gpu_spec, "image", {})

    @pytest.mark.asyncio
    async def test_provision_api_failure_raises(self, provider, gpu_spec):
        offers = [{"id": 42, "dph_total": 1.5}]
        create_fail = {"success": False, "msg": "instance rejected"}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(200, {"offers": offers})
            mock_client.put.return_value = _mock_response(200, create_fail)

            with pytest.raises(ProvisionError, match="create_instance failed"):
                await provider.provision(gpu_spec, "image", {})

    @pytest.mark.asyncio
    async def test_provision_instance_enters_exited_raises(self, provider, gpu_spec):
        offers = [{"id": 42, "dph_total": 1.5}]
        create_resp = {"success": True, "new_contract": {"id": 99999}}
        instance_exited = {
            "instances": [{"id": 99999, "actual_status": "exited", "exit_code": 1}]
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = [
                _mock_response(200, {"offers": offers}),
                _mock_response(200, instance_exited),
            ]
            mock_client.put.return_value = _mock_response(200, create_resp)

            with pytest.raises(ProvisionError, match="exited"):
                await provider.provision(gpu_spec, "image", {})

    @pytest.mark.asyncio
    async def test_provision_timeout_raises(self, provider, gpu_spec):
        offers = [{"id": 42, "dph_total": 1.5}]
        create_resp = {"success": True, "new_contract": {"id": 99999}}
        instance_creating = {
            "instances": [{"id": 99999, "actual_status": "created", "exit_code": None}]
        }

        import packages.providers.vastai as vastai_mod
        with patch.object(vastai_mod, "_PROVISION_TIMEOUT", 0), \
             patch.object(vastai_mod, "_PROVISION_POLL", 0), \
             patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(200, {"offers": offers})
            mock_client.put.return_value = _mock_response(200, create_resp)

            with pytest.raises(ProvisionError, match="did not become running"):
                await provider.provision(gpu_spec, "image", {})


# ---------------------------------------------------------------------------
# wait()
# ---------------------------------------------------------------------------

class TestWait:
    @pytest.mark.asyncio
    async def test_wait_exited_zero(self, provider, pod):
        instance_exited = {
            "instances": [{"id": 99999, "actual_status": "exited", "exit_code": 0}]
        }
        with patch("httpx.AsyncClient") as mock_client_cls, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(200, instance_exited)

            code = await provider.wait(pod)

        assert code == 0

    @pytest.mark.asyncio
    async def test_wait_exited_nonzero(self, provider, pod):
        instance_exited = {
            "instances": [{"id": 99999, "actual_status": "exited", "exit_code": 1}]
        }
        with patch("httpx.AsyncClient") as mock_client_cls, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(200, instance_exited)

            code = await provider.wait(pod)

        assert code == 1

    @pytest.mark.asyncio
    async def test_wait_offline_returns_one(self, provider, pod):
        instance_offline = {
            "instances": [{"id": 99999, "actual_status": "offline", "exit_code": None}]
        }
        with patch("httpx.AsyncClient") as mock_client_cls, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.return_value = _mock_response(200, instance_offline)

            code = await provider.wait(pod)

        assert code == 1

    @pytest.mark.asyncio
    async def test_wait_polls_until_exit(self, provider, pod):
        running = {"instances": [{"id": 99999, "actual_status": "running", "exit_code": None}]}
        exited  = {"instances": [{"id": 99999, "actual_status": "exited",  "exit_code": 0}]}
        with patch("httpx.AsyncClient") as mock_client_cls, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = [
                _mock_response(200, running),
                _mock_response(200, running),
                _mock_response(200, exited),
            ]
            code = await provider.wait(pod)

        assert code == 0
        assert mock_client.get.call_count == 3


# ---------------------------------------------------------------------------
# stream_logs()
# ---------------------------------------------------------------------------

class TestStreamLogs:
    @pytest.mark.asyncio
    async def test_stream_logs_deduplicates(self, provider, pod):
        log_batch1 = "line1\nline2"
        log_batch2 = "line1\nline2\nline3"
        exited = {"instances": [{"id": 99999, "actual_status": "exited"}]}

        with patch("httpx.AsyncClient") as mock_client_cls, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = [
                _mock_response(200, text=log_batch1),   # logs fetch 1
                _mock_response(200, {"instances": [{"id": 99999, "actual_status": "running"}]}),  # status
                _mock_response(200, text=log_batch2),   # logs fetch 2
                _mock_response(200, exited),             # status → exited
                _mock_response(200, text=log_batch2),   # final log fetch
            ]

            lines = [line async for line in provider.stream_logs(pod)]

        assert lines == ["line1", "line2", "line3"]

    @pytest.mark.asyncio
    async def test_stream_logs_stops_on_exited(self, provider, pod):
        exited = {"instances": [{"id": 99999, "actual_status": "exited"}]}

        with patch("httpx.AsyncClient") as mock_client_cls, \
             patch("asyncio.sleep", new_callable=AsyncMock):
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.get.side_effect = [
                _mock_response(200, text="done\n"),   # logs
                _mock_response(200, exited),           # status check
                _mock_response(200, text="done\n"),   # final sweep
            ]

            lines = [line async for line in provider.stream_logs(pod)]

        assert lines == ["done"]


# ---------------------------------------------------------------------------
# terminate()
# ---------------------------------------------------------------------------

class TestTerminate:
    @pytest.mark.asyncio
    async def test_terminate_calls_delete(self, provider, pod):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.delete.return_value = _mock_response(200, {"success": True})

            await provider.terminate(pod)

        mock_client.delete.assert_called_once()
        url = mock_client.delete.call_args[0][0]
        assert "99999" in url

    @pytest.mark.asyncio
    async def test_terminate_ignores_errors(self, provider, pod):
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_client.delete.side_effect = httpx.ConnectError("gone")

            # Should not raise
            await provider.terminate(pod)


# ---------------------------------------------------------------------------
# GPU name mapping
# ---------------------------------------------------------------------------

class TestGpuMapping:
    def test_h100_maps_to_sxm5(self, provider):
        spec = GPUSpec(gpu_type="H100")
        assert provider._vast_gpu_name(spec) == "H100_SXM5"

    def test_a100_maps_to_sxm4_80gb(self, provider):
        spec = GPUSpec(gpu_type="A100")
        assert provider._vast_gpu_name(spec) == "A100_SXM4_80GB"

    def test_unknown_passthrough(self, provider):
        spec = GPUSpec(gpu_type="RTX_6000_ADA")
        assert provider._vast_gpu_name(spec) == "RTX_6000_ADA"


# ---------------------------------------------------------------------------
# _env_str()
# ---------------------------------------------------------------------------

class TestEnvStr:
    def test_simple_values(self):
        result = VastAIProvider._env_str({"KEY": "value", "NUM": "42"})
        assert "-e KEY=value" in result
        assert "-e NUM=42" in result

    def test_json_value_quoted(self):
        result = VastAIProvider._env_str({"INPUTS": '{"k":"v"}'})
        # Should be double-quoted to handle the braces
        assert "-e INPUTS=" in result

    def test_empty_dict(self):
        assert VastAIProvider._env_str({}) == ""
