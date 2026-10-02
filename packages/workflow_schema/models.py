"""
packages/workflow-schema/models.py
(Canonical location. Python-importable copy lives in packages/workflow_schema/models.py)

Pydantic models for the YAML workflow DSL.
These are the source of truth for what a valid workflow looks like.
Every node type registers its input/output schema here.
The canvas auto-generates config forms from these models.
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    HF_DOWNLOAD   = "hf-download"
    DATA_PREP     = "data-prep"
    UNSLOTH_TRAIN = "unsloth-train"
    DISTILL_SFT   = "distill-sft"
    QUANTIZE      = "quantize"
    LM_EVAL       = "lm-eval"
    VLLM_SERVE    = "vllm-serve"


class DataFormat(str, Enum):
    CHATML    = "chatml"
    ALPACA    = "alpaca"
    SHAREGPT  = "sharegpt"


class QuantizeMethod(str, Enum):
    GGUF = "gguf"
    AWQ  = "awq"


class GGUFPrecision(str, Enum):
    Q4_K_M = "q4_k_m"
    Q5_K_M = "q5_k_m"
    Q8_0   = "q8_0"


# ---------------------------------------------------------------------------
# Resource spec (GPU requirements per node)
# ---------------------------------------------------------------------------

class ResourceSpec(BaseModel):
    gpu: str = Field(default="1xH100", description="GPU spec string, e.g. '1xH100', '1xA100'")
    provider_pref: list[str] = Field(
        default=["nebius", "vastai"],
        description="Ordered list of preferred providers (nebius first for hackathon)"
    )


# ---------------------------------------------------------------------------
# Node input schemas (one per node type)
# ---------------------------------------------------------------------------

class DataPrepInputs(BaseModel):
    dataset: str = Field(description="URI to JSONL/CSV or HuggingFace dataset name")
    format: DataFormat = Field(default=DataFormat.CHATML)
    train_split: float = Field(default=0.9, ge=0.5, le=0.99)

class DataPrepOutputs(BaseModel):
    train_jsonl: str
    eval_jsonl: str
    stats_json: str


class UnslothTrainInputs(BaseModel):
    model: str = Field(default="Qwen/Qwen3-4B-Instruct", description="HuggingFace model ID")
    train_data: str = Field(description="R2 URI to train JSONL")
    eval_data: str = Field(default="", description="R2 URI to eval JSONL (empty = skip eval)")
    lora_r: int = Field(default=16)
    lora_alpha: int = Field(default=32)
    max_steps: int = Field(default=500)
    learning_rate: float = Field(default=2e-4)
    target_modules: str = Field(default="all-linear")
    checkpoint_steps: int = Field(default=100, description="Upload checkpoint to R2 every N steps")

class UnslothTrainOutputs(BaseModel):
    lora_adapter: str       # PEFT format
    merged_model: str       # Full HF format
    train_metrics_json: str


class DistillSFTInputs(BaseModel):
    teacher: str = Field(description="R2 URI or HF ID of teacher model")
    student_base: str = Field(default="Qwen/Qwen3-1.7B-Instruct")
    train_data: str = Field(description="R2 URI to prompts-only JSONL")
    n_synthetic: int = Field(default=5000)

class DistillSFTOutputs(BaseModel):
    student_model: str
    synthetic_dataset: str
    distill_metrics_json: str


class HFDownloadInputs(BaseModel):
    model_id:        str            = Field(description="HuggingFace model ID, e.g. 'Qwen/Qwen3-4B-Instruct'")
    hf_token:        str | None     = Field(default=None, description="HuggingFace token for private/gated models")
    revision:        str | None     = Field(default=None, description="Branch, tag, or commit SHA (default: main)")
    ignore_patterns: list[str] | None = Field(default=None, description="Glob patterns to skip (default: non-PyTorch formats)")

class HFDownloadOutputs(BaseModel):
    hf_model: str   # R2 URI to the downloaded HF model directory


class QuantizeInputs(BaseModel):
    model: str = Field(description="HF model ID (e.g. Qwen/Qwen3-4B-Instruct) or R2 URI")
    method: QuantizeMethod
    precision: GGUFPrecision = Field(default=GGUFPrecision.Q4_K_M, description="GGUF only")
    bits: int = Field(default=4, description="AWQ only")
    hf_token: str | None = Field(default=None, description="HuggingFace token for private models")

class QuantizeOutputs(BaseModel):
    gguf_file: str | None = None    # set when method=gguf
    awq_model: str | None = None    # set when method=awq


class LMEvalInputs(BaseModel):
    models: list[str] = Field(description="List of model URIs to compare")
    tasks: list[str] = Field(default=["hellaswag", "mmlu_stem", "gsm8k"])
    judge_eval_set: str = Field(description="R2 URI to held-out eval JSONL")

class LMEvalOutputs(BaseModel):
    eval_report_json: str
    eval_report_html: str
    comparison_table_md: str


class VLLMServeInputs(BaseModel):
    model: str = Field(description="HF model ID or R2 URI to AWQ model")
    max_model_len: int = Field(default=8192)
    keep_alive_min: int = Field(default=60)
    served_model_name: str | None = Field(default=None, description="Override name in /v1/models")
    gpu_memory_utilization: float = Field(default=0.90)
    dtype: str = Field(default="bfloat16")
    hf_token: str | None = Field(default=None, description="HuggingFace token for private models")

class VLLMServeOutputs(BaseModel):
    endpoint_url: str
    openai_api_key: str


# ---------------------------------------------------------------------------
# Generic node definition (what appears in workflow YAML)
# ---------------------------------------------------------------------------

class NodeDef(BaseModel):
    id: str = Field(description="Unique node ID within the workflow, e.g. 'train_1'")
    type: NodeType
    needs: list[str] = Field(default=[], description="Node IDs this node depends on")
    inputs: dict[str, Any] = Field(default={})
    resources: ResourceSpec = Field(default_factory=ResourceSpec)


# ---------------------------------------------------------------------------
# Top-level workflow schema
# ---------------------------------------------------------------------------

class WorkflowInput(BaseModel):
    type: Literal["string", "integer", "float", "boolean"] = "string"
    description: str = ""
    default: Any = None


class WorkflowSchema(BaseModel):
    """
    The YAML workflow schema. This is the source of truth —
    the canvas JSON derives from this, not the other way around.

    Example:
        name: "qwen3-finetune-distill-deploy"
        version: 1
        inputs:
          dataset_uri:
            type: string
            description: "JSONL or HF dataset"
          base_model:
            type: string
            default: "Qwen/Qwen3-4B-Instruct"
        nodes:
          - id: prep
            type: data-prep
            inputs:
              dataset: ${{ inputs.dataset_uri }}
              ...
    """
    name: str
    version: int = 1
    inputs: dict[str, WorkflowInput] = {}
    nodes: list[NodeDef]


# ---------------------------------------------------------------------------
# Node type registry (used by agent + canvas to list available nodes)
# ---------------------------------------------------------------------------

NODE_REGISTRY: dict[NodeType, dict] = {
    NodeType.HF_DOWNLOAD: {
        "description": "Download a HuggingFace model to R2 with SHA256 verification. "
                       "Download once, reuse across workflows.",
        "inputs_schema":  HFDownloadInputs,
        "outputs_schema": HFDownloadOutputs,
        "runtime": "cpu",
    },
    NodeType.DATA_PREP: {
        "description": "Load, validate, split, and reformat a dataset to ChatML.",
        "inputs_schema": DataPrepInputs,
        "outputs_schema": DataPrepOutputs,
        "runtime": "cpu",  # runs on control plane, no GPU pod needed
    },
    NodeType.UNSLOTH_TRAIN: {
        "description": "Fine-tune a model with LoRA SFT via Unsloth (2-5x faster, 80% less VRAM).",
        "inputs_schema": UnslothTrainInputs,
        "outputs_schema": UnslothTrainOutputs,
        "runtime": "gpu",
    },
    NodeType.DISTILL_SFT: {
        "description": "Distill a large teacher model into a smaller student via off-policy SFT.",
        "inputs_schema": DistillSFTInputs,
        "outputs_schema": DistillSFTOutputs,
        "runtime": "gpu",
    },
    NodeType.QUANTIZE: {
        "description": "Quantize a model to GGUF (for Ollama/llama.cpp) or AWQ (for vLLM).",
        "inputs_schema": QuantizeInputs,
        "outputs_schema": QuantizeOutputs,
        "runtime": "cpu",  # GGUF is CPU; AWQ needs GPU — handled inside the container
    },
    NodeType.LM_EVAL: {
        "description": "Evaluate and compare models with lm-evaluation-harness + LLM-as-judge.",
        "inputs_schema": LMEvalInputs,
        "outputs_schema": LMEvalOutputs,
        "runtime": "gpu",
    },
    NodeType.VLLM_SERVE: {
        "description": "Deploy a model as an OpenAI-compatible endpoint via vLLM.",
        "inputs_schema": VLLMServeInputs,
        "outputs_schema": VLLMServeOutputs,
        "runtime": "gpu",
        "long_running": True,  # pod stays alive after container exits
    },
}
