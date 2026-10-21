"""The GPU-hour rates in orchapod.prices are the ones nebius.com/prices lists (read 2026-10-20)."""

from orchapod.prices import PRICES


def test_gpu_hour_rates_are_the_price_page_rates():
    gpu = PRICES["nebius_serverless"]
    # gpu-l40s-a is the Intel L40S ("from $1.55"); $1.82 is the AMD platform gpu-l40s-d, which no node uses.
    assert (gpu["gpu-h100-sxm"], gpu["gpu-l40s-a"]) == (4.50, 1.55)
