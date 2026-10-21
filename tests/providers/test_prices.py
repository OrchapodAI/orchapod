"""The GPU-hour rates in orchapod.prices are the ones nebius.com/prices lists (read 2026-10-20), and they are the only table."""

import pytest

from orchapod.prices import PRICES
from packages.providers.base import GPUSpec
from packages.providers.nebius import NebiusProvider


def test_gpu_hour_rates_are_the_price_page_rates():
    gpu = PRICES["nebius_serverless"]
    # gpu-l40s-a is the Intel L40S ("from $1.55"); $1.82 is the AMD platform gpu-l40s-d, which no node uses.
    assert (gpu["gpu-h100-sxm"], gpu["gpu-l40s-a"]) == (4.50, 1.55)


async def test_nebius_quote_reads_the_one_price_table():
    """R5/R16: nebius.py's own table (H100 at a stale $2.49) is gone; quote prices from orchapod.prices."""
    quote = await NebiusProvider().quote(GPUSpec(gpu_type="H100", count=2))
    assert (quote.gpu_type, quote.price_per_hour) == ("gpu-h100-sxm", 2 * PRICES["nebius_serverless"]["gpu-h100-sxm"])


async def test_nebius_quote_fails_closed_for_an_unpriced_platform():
    with pytest.raises(LookupError, match="no price for nebius_serverless gpu-h200-sxm"):
        await NebiusProvider().quote(GPUSpec(gpu_type="H200"))
