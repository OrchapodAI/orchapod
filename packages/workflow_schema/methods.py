from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field


class TrainingMethod(BaseModel):
    method_id: str
    display_name: str
    framework: str
    container: str
    description: str = ""
    runtime: str = "gpu"
    default_hyperparams: dict[str, Any] = Field(default_factory=dict)
    supported_models: list[str] = Field(default_factory=list)


TRAINING_METHOD_REGISTRY: dict[str, TrainingMethod] = {
    "unsloth-lora-sft": TrainingMethod(
        method_id="unsloth-lora-sft",
        display_name="Unsloth LoRA SFT",
        framework="unsloth",
        container="ghcr.io/orchapod/unsloth-train:latest",
        description="Fine-tune with LoRA via Unsloth (2-5x faster, 80% less VRAM).",
        runtime="gpu",
        default_hyperparams={"lora_r": 16, "lora_alpha": 32, "max_steps": 500,
                              "learning_rate": 2e-4, "target_modules": "all-linear"},
        supported_models=[
            "Qwen/Qwen3-4B-Instruct", "Qwen/Qwen3-1.7B-Instruct", "Qwen/Qwen3-8B-Instruct",
            "meta-llama/Llama-3.1-8B-Instruct", "meta-llama/Llama-3.2-3B-Instruct",
            "mistralai/Mistral-7B-Instruct-v0.3", "microsoft/Phi-3.5-mini-instruct",
            "google/gemma-2-2b-it",
        ],
    ),
    "unsloth-distill-sft": TrainingMethod(
        method_id="unsloth-distill-sft",
        display_name="Unsloth Distill SFT",
        framework="unsloth",
        container="ghcr.io/orchapod/unsloth-distill:latest",
        description="Distill a large teacher into a smaller student via off-policy SFT.",
        runtime="gpu",
        default_hyperparams={"n_synthetic": 5000, "lora_r": 16, "lora_alpha": 32,
                              "max_steps": 300, "learning_rate": 2e-4},
        supported_models=[
            "Qwen/Qwen3-1.7B-Instruct", "meta-llama/Llama-3.2-3B-Instruct",
            "google/gemma-2-2b-it",
        ],
    ),
    "quant-gguf": TrainingMethod(
        method_id="quant-gguf",
        display_name="Quantize GGUF",
        framework="llama.cpp",
        container="ghcr.io/orchapod/quant-gguf:latest",
        description="Quantize a model to GGUF format for Ollama/llama.cpp deployment.",
        runtime="cpu",
        default_hyperparams={"precision": "q4_k_m"},
        supported_models=["*"],
    ),
    "quant-awq": TrainingMethod(
        method_id="quant-awq",
        display_name="Quantize AWQ",
        framework="autoawq",
        container="ghcr.io/orchapod/quant-awq:latest",
        description="Quantize a model to AWQ format for vLLM deployment.",
        runtime="gpu",
        default_hyperparams={"bits": 4, "group_size": 128},
        supported_models=["*"],
    ),
}


def list_methods() -> list[TrainingMethod]:
    return list(TRAINING_METHOD_REGISTRY.values())


def get_method(method_id: str) -> TrainingMethod | None:
    return TRAINING_METHOD_REGISTRY.get(method_id)


if __name__ == "__main__":
    import json
    for m in TRAINING_METHOD_REGISTRY.values():
        print(f"  {m.method_id:<22}  {m.display_name}  [{m.runtime}]  {m.container}")
