"""The one price table (contracts R5, R16): orchapod.cost re-exports it, the provider clients import it from here.

Unknown prices are absent, so every lookup of them fails closed.
"""

PRICES = {
    # $ per 1M tokens, by Token Factory model id. Source: GET /v1/models?verbose=true `pricing.prompt`/`.completion`
    # ($ per token), read 2026-10-22 by spike 1. meta-llama/Llama-3.1-8B-Instruct is not in that serverless catalog
    # (no Llama is), so it has no per-token price and stays absent.
    "token_factory": {
        "nvidia/nemotron-3-super-120b-a12b": {"in": 0.30, "out": 0.90},
        "nvidia/Nemotron-3-Ultra-550b-a55b": {"in": 1.00, "out": 3.00},
        "nvidia/Nemotron-3_5-Lightning": {"in": 0.06, "out": 0.24},
        "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": {"in": 0.06, "out": 0.24},
    },
    # $ per trained token, by base model. Unverified as of 2026-10-22 (spike 1): the API does not return it and the
    # public price link (nebius.com/token-factory/prices) opens the console's billing page behind a login; absent.
    "token_factory_finetune": {},
    # $ per credit: search 1 (basic) or 2 (advanced); extract 1 or 2 per 5 successful URLs.
    "tavily": {"credit": 0.008},
    # $ per GPU-hour, by platform. Source: nebius.com/prices, on-demand, read 2026-10-20; Serverless Jobs and Endpoints bill at
    # Compute rates (docs.nebius.com/serverless/pricing-quotas), platform ids per docs.nebius.com/compute/virtual-machines/types.
    # gpu-h100-sxm = "NVIDIA HGX H100" $4.50. gpu-l40s-a = "L40S with Intel CPU" from $1.55 (8-40 vCPU, our preset 1gpu-8vcpu-32gb).
    # $1.82, which we first used for gpu-l40s-a, is the AMD platform gpu-l40s-d ("from", 16+ vCPU): add it only if a node targets it.
    "nebius_serverless": {"gpu-h100-sxm": 4.50, "gpu-l40s-a": 1.55},
}
