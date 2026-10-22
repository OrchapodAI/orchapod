"""The GPU-hour rates in orchapod.prices are the ones nebius.com/prices lists (read 2026-10-20), and they are the only table."""

import pytest

from orchapod.prices import PRICES
from packages.providers.base import GPUSpec
from packages.providers.nebius import NebiusProvider


def test_gpu_hour_rates_are_the_price_page_rates():
    gpu = PRICES["nebius_serverless"]
    # gpu-l40s-a is the Intel L40S ("from $1.55"); $1.82 is the AMD platform gpu-l40s-d, which no node uses.
    assert (gpu["gpu-h100-sxm"], gpu["gpu-l40s-a"]) == (4.50, 1.55)


def test_token_rates_are_the_catalog_rates():
    """GET /v1/models?verbose=true `pricing` ($ per token), read 2026-10-22 by spike 1, in $ per 1M."""
    assert PRICES["token_factory"] == {
        "nvidia/nemotron-3-super-120b-a12b": {"in": 0.30, "out": 0.90},
        "nvidia/Nemotron-3-Ultra-550b-a55b": {"in": 1.00, "out": 3.00},
        "nvidia/Nemotron-3_5-Lightning": {"in": 0.06, "out": 0.24},
        "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": {"in": 0.06, "out": 0.24},
    }


async def test_nebius_quote_reads_the_one_price_table():
    """R5/R16: nebius.py's own table (H100 at a stale $2.49) is gone; quote prices from orchapod.prices."""
    for gpu, platform in (("H100", "gpu-h100-sxm"), ("L40S", "gpu-l40s-a")):
        quote = await NebiusProvider().quote(GPUSpec(gpu_type=gpu))
        assert (quote.gpu_type, quote.price_per_hour) == (platform, PRICES["nebius_serverless"][platform])


async def test_nebius_quote_fails_closed_for_a_spec_jobs_do_not_run(monkeypatch):
    for spec in (GPUSpec(gpu_type="H200"), GPUSpec(gpu_type="H100", count=2)):
        with pytest.raises(LookupError, match="1xH100 or 1xL40S"):
            await NebiusProvider().quote(spec)
    monkeypatch.delitem(PRICES["nebius_serverless"], "gpu-l40s-a")
    with pytest.raises(LookupError, match="no price for nebius_serverless gpu-l40s-a"):
        await NebiusProvider().quote(GPUSpec(gpu_type="L40S"))
