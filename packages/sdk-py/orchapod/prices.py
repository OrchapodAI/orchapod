"""
packages/sdk-py/orchapod/prices.py

The one price table (R5, R16). Platform owns the numbers; this empty stub only lets
the SDK import until platform's file merges, and an empty table fails closed.
Shape: {"token_factory": {model: {"in", "out"}} ($/1M tokens), "token_factory_finetune":
{model: $/trained token}, "tavily": {"credit": $}, "nebius_serverless": {platform: $/GPU-hour}}.
"""

PRICES: dict = {}
