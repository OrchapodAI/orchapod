"""
packages/workflow_schema/models.py
(Canonical location. Python-importable copy lives in packages/workflow_schema/models.py)

Pydantic models for the YAML workflow DSL.
These are the source of truth for what a valid workflow looks like.
Every node type registers its input/output schema here.
The canvas auto-generates config forms from these models.
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    # Data ingestion
    HF_DOWNLOAD          = "hf-download"
    HF_IMPORT            = "hf-import"
    FILE_UPLOAD          = "file-upload"
    S3_IMPORT            = "s3-import"
    # Data processing
    DATA_PREP            = "data-prep"
    AUTO_LABEL_CLEANLAB  = "auto-label-cleanlab"
    SYNTH_DISTILABEL     = "synth-distilabel"
    # Training
    UNSLOTH_TRAIN        = "unsloth-train"
    DISTILL_SFT          = "distill-sft"
    TF_FINETUNE          = "tf-finetune"
    # Post-training
    QUANTIZE             = "quantize"
    LM_EVAL              = "lm-eval"
    VLLM_SERVE           = "vllm-serve"
    TF_DEPLOY            = "tf-deploy"


class DataFormat(str, Enum):
    CHATML    = "chatml"
    ALPACA    = "alpaca"
    SHAREGPT  = "sharegpt"
    QA        = "qa"
    STRUCTURED = "structured"


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
    dataset: str = Field(description="r2:// URI (JSONL unless the name ends in .csv), hf://<id> or <org>/<name>")
    hf_config: str | None = Field(default=None, description="Hugging Face config, e.g. 'main' for openai/gsm8k")
    hf_split: str = Field(default="train", description="Hugging Face split; slices work, e.g. 'test[:50]'")
    format: DataFormat = Field(default=DataFormat.CHATML,
                               description="qa: question → user, answer → assistant; structured: rows kept as they are")
    train_split: float = Field(default=0.9, ge=0.5, le=0.99)
    test_split: float = Field(default=0.0, ge=0.0, description="Held out as test_jsonl; eval gets 1 - train - test")

    @model_validator(mode="after")
    def _splits_fit(self):
        if self.train_split + self.test_split > 1 + 1e-9:
            raise ValueError("train_split + test_split must be <= 1")
        return self

class DataPrepOutputs(BaseModel):
    dataset: str      # every cleaned row, extra keys kept
    train_jsonl: str  # chat rows reduced to {"messages"}; structured rows unchanged
    eval_jsonl: str
    test_jsonl: str   # held out; keeps context and source_url


class HFImportInputs(BaseModel):
    """KAN-7 — Import a HuggingFace Hub dataset, detect format, validate rows."""
    dataset_id: str = Field(description="HuggingFace dataset ID, e.g. 'databricks/databricks-dolly-15k'")
    split: str = Field(default="train", description="Dataset split to import")
    format: Literal["auto", "chatml", "alpaca", "sharegpt", "dpo"] = Field(default="auto")
    max_rows: int | None = Field(default=None, ge=1, description="Cap on rows to import")

class HFImportOutputs(BaseModel):
    dataset: str  # R2 URI to canonical JSONL


class FileUploadInputs(BaseModel):
    """KAN-6 — Reference to a user-uploaded CSV/JSONL/Parquet file."""
    upload_id: str = Field(description="Upload ID returned by POST /uploads")
    format: Literal["auto", "chatml", "alpaca", "sharegpt", "dpo"] = Field(default="auto")

class FileUploadOutputs(BaseModel):
    dataset: str  # R2 URI to canonical JSONL


class S3ImportInputs(BaseModel):
    """KAN-9 — Read from an S3-compatible bucket."""
    bucket: str = Field(description="S3 bucket name")
    prefix: str = Field(default="", description="Key prefix filter")
    endpoint_url: str | None = Field(default=None, description="Custom endpoint for R2/MinIO")
    access_key_id: str | None = Field(default=None)
    secret_access_key: str | None = Field(default=None)
    format: Literal["auto", "chatml", "alpaca", "sharegpt", "dpo"] = Field(default="auto")
    max_rows: int | None = Field(default=None)

class S3ImportOutputs(BaseModel):
    dataset: str  # R2 URI to canonical JSONL


class AutoLabelCleanlabInputs(BaseModel):
    """KAN-11 — Auto-label dataset rows using Cleanlab TLM trustworthiness scores."""
    dataset: str = Field(description="R2 URI to input dataset JSONL")
    quality_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    cleanlab_api_key: str | None = Field(default=None, description="Cleanlab API key (stub mode if unset)")

class AutoLabelCleanlabOutputs(BaseModel):
    dataset: str   # filtered high-quality rows
    labels_json: str  # per-row quality scores


class SynthDistilabelInputs(BaseModel):
    """KAN-10 — Generate synthetic ChatML rows via a teacher LLM.

    Default teacher is NVIDIA Nemotron Super via Nebius Token Factory.
    Falls back to OpenAI or Anthropic if NEBIUS_API_KEY is not set.
    """
    pipeline_template: Literal["self-instruct", "evol-instruct", "magpie"] = Field(
        default="self-instruct",
    )
    teacher_kind: Literal["nebius", "openai", "anthropic"] = Field(
        default="nebius",
        description="Teacher LLM provider — 'nebius' uses Nemotron Super via Token Factory",
    )
    teacher_model: str = Field(
        default="nvidia/nemotron-3-super-120b-a12b",
        description="Model ID. Nemotron Super 49B is the default teacher.",
    )
    n_samples: int = Field(default=1000, ge=10)
    seed_prompts: str | None = Field(default=None, description="R2 URI to seed prompts JSONL")
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=64)

class SynthDistilabelOutputs(BaseModel):
    dataset: str          # R2 URI to generated ChatML JSONL
    cost_summary_json: str


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
    NodeType.HF_IMPORT: {
        "description": "Import a HuggingFace Hub dataset, auto-detect format, validate rows.",
        "inputs_schema": HFImportInputs,
        "outputs_schema": HFImportOutputs,
        "runtime": "cpu",
    },
    NodeType.FILE_UPLOAD: {
        "description": "Upload a CSV/JSONL/Parquet file from your computer.",
        "inputs_schema": FileUploadInputs,
        "outputs_schema": FileUploadOutputs,
        "runtime": "cpu",
    },
    NodeType.S3_IMPORT: {
        "description": "Read CSV/JSONL/Parquet files from an S3-compatible bucket (AWS, R2, MinIO).",
        "inputs_schema": S3ImportInputs,
        "outputs_schema": S3ImportOutputs,
        "runtime": "cpu",
    },
    NodeType.DATA_PREP: {
        "description": "Load (r2 or Hugging Face), convert to chat or keep structured rows, dedupe, "
                       "split train/eval/test (seed 42, stratified by source_url).",
        "inputs_schema": DataPrepInputs,
        "outputs_schema": DataPrepOutputs,
        "runtime": "cpu",
    },
    NodeType.AUTO_LABEL_CLEANLAB: {
        "description": "Auto-label rows with Cleanlab TLM quality scores; threshold-filter low-quality rows.",
        "inputs_schema": AutoLabelCleanlabInputs,
        "outputs_schema": AutoLabelCleanlabOutputs,
        "runtime": "cpu",
    },
    NodeType.SYNTH_DISTILABEL: {
        "description": "Generate synthetic training data via a teacher LLM (default: Nemotron Super via Nebius Token Factory).",
        "inputs_schema": SynthDistilabelInputs,
        "outputs_schema": SynthDistilabelOutputs,
        "runtime": "cpu",
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


# ---------------------------------------------------------------------------
# tf-finetune and tf-deploy: Lane A on Token Factory (ml-engineering; docs/contracts.md "ML nodes")
# ---------------------------------------------------------------------------

class TFFinetuneInputs(BaseModel):
    model: str = Field(default="meta-llama/Llama-3.1-8B-Instruct",
                       description="Token Factory fine-tune base (Llama, Qwen, gpt-oss, DeepSeek, Gemma; not Nemotron)")
    train_data: str = Field(description="r2:// URI of the train JSONL, e.g. data-prep's train_jsonl")
    eval_data: str = Field(default="", description="r2:// URI of the eval JSONL; empty, or an empty file, = no validation")
    n_epochs: int = Field(default=2, ge=1)
    hyperparameters: dict[str, Any] = Field(
        default={}, description="Token Factory names verbatim (batch_size, learning_rate, lora_r, lora_alpha, lora_dropout, "
                                "packing, context_length, warmup_ratio, weight_decay, max_grad_norm), merged over "
                                "{lora: true, n_epochs}")
    timeout_min: int = Field(default=60, ge=1, le=85, description="Then the job is cancelled and the node fails "
                                                                 "(at most 85, under the executor's 90-min backstop)")

class TFFinetuneOutputs(BaseModel):
    job: str           # {job_id, model, status, checkpoint_id, checkpoint_step, train_loss, valid_loss, trained_tokens}
    lora_adapter: str  # PEFT dir of the best checkpoint (lowest valid_loss, else the last)

NODE_REGISTRY[NodeType.TF_FINETUNE] = {
    "description": "LoRA fine-tune on Nebius Token Factory (Llama, Qwen, gpt-oss, DeepSeek, Gemma; not Nemotron). Keeps "
                   "the checkpoint with the lowest validation loss as a PEFT adapter and reports the loss curve.",
    "inputs_schema": TFFinetuneInputs,
    "outputs_schema": TFFinetuneOutputs,
    "runtime": "api",
}


class TFDeployInputs(BaseModel):
    job: dict[str, Any] | str = Field(description="tf-finetune's job output (r2:// URI), or the same JSON inline")
    name: str | None = Field(default=None, description="Deployment name; empty = orchapod-<run_id[:8]>")

class TFDeployOutputs(BaseModel):
    model_ref: str  # ModelRef JSON {base_url, model, api_key_env, base_model}; its metadata adds `proof`

NODE_REGISTRY[NodeType.TF_DEPLOY] = {
    "description": "Serve a tf-finetune checkpoint as a per-token LoRA model on Token Factory and prove it with one "
                   "completion. If Token Factory has no per-token LoRA for the base, it fails: serve tf-finetune's "
                   "lora_adapter with vllm-serve instead.",
    "inputs_schema": TFDeployInputs,
    "outputs_schema": TFDeployOutputs,
    "runtime": "api",
}
