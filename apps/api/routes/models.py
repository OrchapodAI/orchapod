"""
apps/api/routes/models.py

Registry endpoints — expose available base models and node types to the frontend.
The canvas uses these to populate dropdowns and auto-generate config forms.

Mounted at /registry (see main.py):
  GET /registry/models            — curated list of base models the user can fine-tune
  GET /registry/models/{model_id} — single model from catalog
  GET /registry/node-types        — full node type registry with input/output schemas
  GET /registry/datasets          — pre-loaded public datasets available for selection
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


# ---------------------------------------------------------------------------
# Curated base model catalog
# ---------------------------------------------------------------------------

BASE_MODELS = [
    {
        "id": "Qwen/Qwen3-4B-Instruct",
        "name": "Qwen3 4B Instruct",
        "family": "Qwen3",
        "params_b": 4,
        "context_len": 32768,
        "recommended_gpu": "1xH100",
        "use_cases": ["instruction-following", "reasoning", "code"],
        "hf_url": "https://huggingface.co/Qwen/Qwen3-4B-Instruct",
    },
    {
        "id": "Qwen/Qwen3-1.7B-Instruct",
        "name": "Qwen3 1.7B Instruct",
        "family": "Qwen3",
        "params_b": 1.7,
        "context_len": 32768,
        "recommended_gpu": "1xA100",
        "use_cases": ["instruction-following", "edge-deployment"],
        "hf_url": "https://huggingface.co/Qwen/Qwen3-1.7B-Instruct",
    },
    {
        "id": "Qwen/Qwen3-8B-Instruct",
        "name": "Qwen3 8B Instruct",
        "family": "Qwen3",
        "params_b": 8,
        "context_len": 32768,
        "recommended_gpu": "1xH100",
        "use_cases": ["instruction-following", "reasoning", "code", "multilingual"],
        "hf_url": "https://huggingface.co/Qwen/Qwen3-8B-Instruct",
    },
    {
        "id": "meta-llama/Llama-3.2-3B-Instruct",
        "name": "Llama 3.2 3B Instruct",
        "family": "Llama3",
        "params_b": 3,
        "context_len": 128000,
        "recommended_gpu": "1xA100",
        "use_cases": ["instruction-following", "summarization"],
        "hf_url": "https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct",
        "requires_hf_token": True,
    },
    {
        "id": "meta-llama/Llama-3.1-8B-Instruct",
        "name": "Llama 3.1 8B Instruct",
        "family": "Llama3",
        "params_b": 8,
        "context_len": 128000,
        "recommended_gpu": "1xH100",
        "use_cases": ["instruction-following", "reasoning", "code"],
        "hf_url": "https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct",
        "requires_hf_token": True,
    },
    {
        "id": "microsoft/Phi-3.5-mini-instruct",
        "name": "Phi-3.5 Mini Instruct",
        "family": "Phi",
        "params_b": 3.8,
        "context_len": 128000,
        "recommended_gpu": "1xA100",
        "use_cases": ["instruction-following", "reasoning", "edge-deployment"],
        "hf_url": "https://huggingface.co/microsoft/Phi-3.5-mini-instruct",
    },
    {
        "id": "mistralai/Mistral-7B-Instruct-v0.3",
        "name": "Mistral 7B Instruct v0.3",
        "family": "Mistral",
        "params_b": 7,
        "context_len": 32768,
        "recommended_gpu": "1xH100",
        "use_cases": ["instruction-following", "function-calling"],
        "hf_url": "https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.3",
    },
    {
        "id": "google/gemma-2-2b-it",
        "name": "Gemma 2 2B Instruct",
        "family": "Gemma",
        "params_b": 2,
        "context_len": 8192,
        "recommended_gpu": "1xA100",
        "use_cases": ["instruction-following", "edge-deployment"],
        "hf_url": "https://huggingface.co/google/gemma-2-2b-it",
        "requires_hf_token": True,
    },
]


# ---------------------------------------------------------------------------
# Pre-loaded public datasets
# ---------------------------------------------------------------------------

PUBLIC_DATASETS = [
    {
        "id": "databricks/databricks-dolly-15k",
        "name": "Databricks Dolly 15K",
        "description": "15K high-quality human-generated instruction/response pairs across 8 categories.",
        "size": "15000 examples",
        "format": "alpaca",
        "hf_url": "https://huggingface.co/datasets/databricks/databricks-dolly-15k",
        "use_cases": ["general instruction-following"],
    },
    {
        "id": "teknium/OpenHermes-2.5",
        "name": "OpenHermes 2.5",
        "description": "1M+ synthetic instruction-following examples from GPT-4 and other models.",
        "size": "1,000,000+ examples",
        "format": "chatml",
        "hf_url": "https://huggingface.co/datasets/teknium/OpenHermes-2.5",
        "use_cases": ["general instruction-following", "reasoning"],
    },
    {
        "id": "HuggingFaceH4/ultrachat_200k",
        "name": "UltraChat 200K",
        "description": "200K diverse multi-turn conversations generated by GPT-3.5-turbo.",
        "size": "200,000 examples",
        "format": "chatml",
        "hf_url": "https://huggingface.co/datasets/HuggingFaceH4/ultrachat_200k",
        "use_cases": ["multi-turn conversation", "instruction-following"],
    },
    {
        "id": "iamtarun/python_code_instructions_18k_alpaca",
        "name": "Python Code Instructions 18K",
        "description": "18K Python coding instruction/response pairs.",
        "size": "18,000 examples",
        "format": "alpaca",
        "hf_url": "https://huggingface.co/datasets/iamtarun/python_code_instructions_18k_alpaca",
        "use_cases": ["code generation", "Python"],
    },
    {
        "id": "meta-math/MetaMathQA",
        "name": "MetaMathQA",
        "description": "395K mathematical reasoning QA pairs augmented from GSM8K and MATH.",
        "size": "395,000 examples",
        "format": "alpaca",
        "hf_url": "https://huggingface.co/datasets/meta-math/MetaMathQA",
        "use_cases": ["math reasoning", "problem solving"],
    },
]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/models")
async def list_base_models():
    return {"models": BASE_MODELS}


@router.get("/models/{model_id:path}")
async def get_base_model(model_id: str):
    for m in BASE_MODELS:
        if m["id"] == model_id:
            return m
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail=f"Model '{model_id}' not in catalog")


@router.get("/node-types")
async def list_node_types():
    from packages.workflow_schema.models import NODE_REGISTRY
    result = {}
    for node_type, meta in NODE_REGISTRY.items():
        result[node_type.value] = {
            "description": meta["description"],
            "runtime": meta["runtime"],
            "long_running": meta.get("long_running", False),
            "inputs_schema": meta["inputs_schema"].model_json_schema(),
            "outputs_schema": meta["outputs_schema"].model_json_schema(),
        }
    return {"node_types": result}


@router.get("/datasets")
async def list_datasets():
    return {"datasets": PUBLIC_DATASETS}
