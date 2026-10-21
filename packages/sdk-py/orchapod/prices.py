"""The one price table (contracts R5, R16): orchapod.cost re-exports it, the provider clients import it from here.

Unknown prices are absent, so every lookup of them fails closed. Spike 1 adds Nano, Llama-3.1-8B (a LoRA is
priced as its base_model) and the fine-tune rates (GET /v1/models?verbose=true returns `pricing`).
"""

PRICES = {
    # $ per 1M tokens, by Token Factory model id.
    "token_factory": {
        "nvidia/nemotron-3-super-120b-a12b": {"in": 0.30, "out": 0.90},
        "nvidia/Nemotron-3-Ultra-550b-a55b": {"in": 1.00, "out": 3.00},
        "nvidia/Nemotron-3_5-Lightning": {"in": 0.06, "out": 0.24},
    },
    # $ per trained token, by base model.
    "token_factory_finetune": {},
    # $ per credit: search 1 (basic) or 2 (advanced); extract 1 or 2 per 5 successful URLs.
    "tavily": {"credit": 0.008},
    # $ per GPU-hour, by platform. Source: nebius.com/prices, on-demand, read 2026-10-20; Serverless Jobs and Endpoints bill at
    # Compute rates (docs.nebius.com/serverless/pricing-quotas), platform ids per docs.nebius.com/compute/virtual-machines/types.
    # gpu-h100-sxm = "NVIDIA HGX H100" $4.50. gpu-l40s-a = "L40S with Intel CPU" from $1.55 (8-40 vCPU, our preset 1gpu-8vcpu-32gb).
    # $1.82, which we first used for gpu-l40s-a, is the AMD platform gpu-l40s-d ("from", 16+ vCPU): add it only if a node targets it.
    "nebius_serverless": {"gpu-h100-sxm": 4.50, "gpu-l40s-a": 1.55},
}
