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
    WEB_RESEARCH         = "web-research"
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
    JUDGE_EVAL           = "judge-eval"


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
        default=["nebius"],
        description="Ordered list of preferred providers; vastai only when named here"
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
    test_split: float = Field(default=0.0, ge=0.0, description="Held out as test_jsonl; eval gets 1 - train - test. "
                              "Each split is rounded; from 3 rows on, a requested test split and an eval share above 0 keep at least one row each")
    quality_filter: bool = Field(default=False, description="Chat formats only: Nemotron 3.5 Lightning scores each "
                                 "row 1-5 and rows under 3 are dropped (about $0.01 per 300 rows); skipped under STUB")

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
    """Synthetic data from a Nemotron teacher on Token Factory: chat rows (self-instruct, evol-instruct, magpie,
    grounded Q&A from a web-research corpus) or rows matching row_schema (structured)."""
    pipeline_template: Literal["self-instruct", "evol-instruct", "magpie", "grounded", "structured"] = Field(
        default="self-instruct",
    )
    teacher_model: str = Field(default="nvidia/nemotron-3-super-120b-a12b", description="Token Factory model id")
    n_samples: int = Field(default=1000, ge=10)
    seed_prompts: str | None = Field(default=None, description="R2 URI to seed prompts JSONL")
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    max_tokens: int = Field(default=512, ge=64, description="Per call; a batch asks for what fits "
                                                             "(150 tokens per grounded pair, 100 per structured row)")
    corpus: str | None = Field(default=None, description="r2 URI of a web-research corpus: required for grounded, "
                                                         "real values for structured")
    row_schema: dict | str | None = Field(default=None, description="JSON Schema of one structured row; "
                                                                    "a string is parsed as JSON")
    instructions: str = Field(default="", description="Domain, audience and style hints; for structured, "
                                                      "the target value distributions")
    max_usd: float = Field(default=1.0, description="Stop before a call whose worst case would pass "
                                                    "min(max_usd, the node budget); what was made is kept")

    @model_validator(mode="after")
    def _template_inputs(self):
        if self.pipeline_template == "grounded" and not self.corpus:
            raise ValueError("grounded needs corpus")
        if self.pipeline_template == "structured" and not self.row_schema:
            raise ValueError("structured needs row_schema")
        return self

class SynthDistilabelOutputs(BaseModel):
    dataset: str  # JSONL: chat rows {"messages"} (grounded adds context, source_url) or row_schema objects


class UnslothTrainInputs(BaseModel):
    model: str = Field(default="nvidia/Llama-3.1-Nemotron-Nano-8B-v1",
                       description="Hugging Face id of the student; NemotronH students such as "
                                   "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 need an 80 GB GPU and train ~12x slower")
    train_data: str = Field(description="data-prep's train_jsonl (chat rows)")
    eval_data: str = Field(default="", description="data-prep's eval_jsonl; empty = no validation")
    lora_r: int = Field(default=16)
    lora_alpha: int = Field(default=32)
    max_steps: int = Field(default=500, ge=1, description="Training stops here; demos use about 60 (the Job times out at 1 h)")
    learning_rate: float = Field(default=2e-4)
    target_modules: str = Field(default="all-linear", description="all-linear = q, k, v, o, gate, up, down (NemotronH: "
                                                                  "attention, in_proj, shared experts); else a regex or a comma list")
    checkpoint_steps: int = Field(default=100, ge=1, description="Upload a checkpoint (and validate) every N steps; "
                                                                 "a retry resumes from the newest")
    load_in_4bit: bool = Field(default=False, description="QLoRA; the default is 16-bit LoRA")
    merge: bool = Field(default=True, description="Also merge the adapter into 16-bit weights (merged_model, ~16 GB for "
                                                  "8B); false when the plan reads only lora_adapter (vllm-serve with "
                                                  "lora_adapter, quantize)")

class UnslothTrainOutputs(BaseModel):
    lora_adapter: str               # PEFT dir; metadata {format: peft, base_model}
    merged_model: str | None = None  # with merge: 16-bit HF dir (vllm-serve's model); metadata {format: hf, base_model}


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
    model_id: str = Field(description="Hugging Face model id, e.g. 'Qwen/Qwen2.5-Math-1.5B-Instruct'; a gated model "
                                      "needs HF_TOKEN in the env and its licence accepted")
    revision: str = Field(default="main", description="Branch, tag or commit SHA")
    ignore_patterns: list[str] | None = Field(default=None, description="Glob patterns to skip (default: non-PyTorch formats)")

class HFDownloadOutputs(BaseModel):
    hf_model: str   # r2 dir of the snapshot; metadata {format: hf, model_id, revision}


class QuantizeInputs(BaseModel):
    model: str = Field(description="Hugging Face id, or hf-download's hf_model (r2 dir)")
    method: QuantizeMethod = Field(description="gguf runs on CPU; awq needs a GPU job (exits 1 here)")
    precision: GGUFPrecision = Field(default=GGUFPrecision.Q4_K_M, description="GGUF only")
    bits: int = Field(default=4, description="AWQ only")
    keep_f16: bool = Field(default=False, description="Also write the f16 GGUF as gguf_f16, judge-eval's baseline for one "
                                                       "model's quantization loss; not with lora_adapter (tuned vs "
                                                       "base: both sides are gguf_file, the tuned with tuned_lora)")
    lora_adapter: str | None = Field(default=None, description="r2 PEFT LoRA dir trained on this model (unsloth-train or "
                                                               "tf-finetune lora_adapter): also written as gguf_lora, which "
                                                               "judge-eval's tuned_lora serves on top of gguf_file on CPU")

class QuantizeOutputs(BaseModel):
    gguf_file: str | None = None    # method=gguf: the quantized file; metadata {format, precision, base_model, size_bytes}
    gguf_f16: str | None = None     # method=gguf with keep_f16: the f16 file it was quantized from
    gguf_lora: str | None = None    # with lora_adapter: the adapter as an f32 GGUF LoRA (llama-server --lora)
    awq_model: str | None = None    # method=awq (a GPU job; not built yet)


class LMEvalInputs(BaseModel):
    models: list[str] = Field(description="List of model URIs to compare")
    tasks: list[str] = Field(default=["hellaswag", "mmlu_stem", "gsm8k"])
    judge_eval_set: str = Field(description="R2 URI to held-out eval JSONL")

class LMEvalOutputs(BaseModel):
    eval_report_json: str
    eval_report_html: str
    comparison_table_md: str


class VLLMServeInputs(BaseModel):
    model: str = Field(description="Hugging Face id (the base; a gated one needs HF_TOKEN in the env), or an r2 model "
                                   "dir such as unsloth-train's merged_model")
    lora_adapter: str | None = Field(default=None, description="r2 PEFT dir (tf-finetune or unsloth-train lora_adapter), "
                                                               "served as 'tuned' beside the base on one endpoint")
    max_model_len: int = Field(default=8192)
    keep_alive_min: int = Field(default=30, ge=1, le=120, description="The backend deletes the endpoint after this; "
                                                                      "GPU time bills until then")
    served_model_name: str | None = Field(default=None, description="The base's name in /v1/models (default: the HF "
                                                                    "id; 'tuned' for an r2 dir)")
    gpu_memory_utilization: float = Field(default=0.90)
    dtype: str = Field(default="bfloat16")
    platform: str = Field(default="gpu-l40s-a", description="Nebius GPU platform (priced in orchapod.prices)")
    preset: str = Field(default="1gpu-8vcpu-32gb")

class VLLMServeOutputs(BaseModel):
    model_ref: str                      # ModelRef JSON (api_key_env ORCHAPOD_ENDPOINT_TOKEN); metadata adds endpoint_id, expires_at
    base_model_ref: str | None = None   # with lora_adapter: the same endpoint, model = the base


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
# Row keys: description, inputs_schema, outputs_schema, runtime (cpu | gpu | api), hidden (the agent never plans it),
# rents_gpu (an api node that bills GPU time, such as vllm-serve's endpoint: the budget's gpu guard counts it as gpu).
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
        "hidden": True,  # the agent never plans it: no container
    },
    NodeType.FILE_UPLOAD: {
        "description": "Upload a CSV/JSONL/Parquet file from your computer.",
        "inputs_schema": FileUploadInputs,
        "outputs_schema": FileUploadOutputs,
        "runtime": "cpu",
        "hidden": True,  # the agent never plans it: no container
    },
    NodeType.S3_IMPORT: {
        "description": "Read CSV/JSONL/Parquet files from an S3-compatible bucket (AWS, R2, MinIO).",
        "inputs_schema": S3ImportInputs,
        "outputs_schema": S3ImportOutputs,
        "runtime": "cpu",
        "hidden": True,  # the agent never plans it: no container
    },
    NodeType.DATA_PREP: {
        "description": "Load (r2 or Hugging Face), convert to chat or keep structured rows, dedupe, optionally "
                       "drop low-quality chat rows (Lightning scores), split train/eval/test (seed 42, stratified "
                       "by source_url).",
        "inputs_schema": DataPrepInputs,
        "outputs_schema": DataPrepOutputs,
        "runtime": "cpu",
    },
    NodeType.AUTO_LABEL_CLEANLAB: {
        "description": "Auto-label rows with Cleanlab TLM quality scores; threshold-filter low-quality rows.",
        "inputs_schema": AutoLabelCleanlabInputs,
        "outputs_schema": AutoLabelCleanlabOutputs,
        "runtime": "cpu",
        "hidden": True,  # the agent never plans it: no container
    },
    NodeType.SYNTH_DISTILABEL: {
        "description": "Synthetic data from Nemotron 3 Super on Token Factory: self-instruct, evol-instruct, magpie, "
                       "grounded Q&A from a web-research corpus (rows keep context and source_url), or structured "
                       "rows matching a JSON Schema (row_schema).",
        "inputs_schema": SynthDistilabelInputs,
        "outputs_schema": SynthDistilabelOutputs,
        "runtime": "cpu",
    },
    NodeType.UNSLOTH_TRAIN: {
        "description": "Fine-tune a model with LoRA SFT via Unsloth (2-5x faster, 80% less VRAM): lora_adapter, and with "
                       "merge (default true) the merged 16-bit weights as merged_model.",
        "inputs_schema": UnslothTrainInputs,
        "outputs_schema": UnslothTrainOutputs,
        "runtime": "gpu",
    },
    NodeType.DISTILL_SFT: {
        "description": "Distill a large teacher model into a smaller student via off-policy SFT.",
        "inputs_schema": DistillSFTInputs,
        "outputs_schema": DistillSFTOutputs,
        "runtime": "gpu",
        "hidden": True,  # the agent never plans it: off the demo path
    },
    NodeType.QUANTIZE: {
        "description": "Quantize a model to GGUF (for Ollama/llama.cpp) or AWQ (for vLLM); with lora_adapter, also "
                       "convert that LoRA to a GGUF LoRA (gguf_lora), so judge-eval can serve the tuned model on CPU.",
        "inputs_schema": QuantizeInputs,
        "outputs_schema": QuantizeOutputs,
        "runtime": "cpu",  # GGUF is CPU; AWQ needs GPU — handled inside the container
    },
    NodeType.LM_EVAL: {
        "description": "Evaluate and compare models with lm-evaluation-harness + LLM-as-judge.",
        "inputs_schema": LMEvalInputs,
        "outputs_schema": LMEvalOutputs,
        "runtime": "gpu",
        "hidden": True,  # the agent never plans it: off the demo path
    },
    NodeType.VLLM_SERVE: {
        "description": "Serve a model (and optionally a LoRA adapter beside it) from a Nebius Serverless Endpoint with "
                       "vLLM for keep_alive_min minutes: model_ref (tuned) and base_model_ref for judge-eval and compare.",
        "inputs_schema": VLLMServeInputs,
        "outputs_schema": VLLMServeOutputs,
        "runtime": "api",  # it creates the endpoint and exits after POST /internal/ttl
        "rents_gpu": True,  # but the endpoint bills GPU hours: budget's gpu guard must treat it as a gpu node
    },
}


# ---------------------------------------------------------------------------
# web-research (owner: data-engineering; contracts "Data nodes → web-research")
# ---------------------------------------------------------------------------

class WebResearchInputs(BaseModel):
    """Tavily search and extract → a corpus of passages with source URLs."""
    queries: list[str] = Field(default=[], description="Each runs a Tavily advanced search with raw page content, "
                                                       "⌈max_pages / len(queries)⌉ results (Tavily caps 20)")
    seed_urls: list[str] = Field(default=[], description="Read with Tavily extract, before the searches")
    max_pages: int = Field(default=20, ge=1, le=100, description="Caps the pages read, and with them the credits")

    @model_validator(mode="after")
    def _a_source(self):
        if not self.queries and not self.seed_urls:
            raise ValueError("give at least one of queries and seed_urls")
        return self

class WebResearchOutputs(BaseModel):
    corpus: str  # JSONL {"url", "text"}: passages of 200–2,000 chars, URLs normalised and deduped

NODE_REGISTRY[NodeType.WEB_RESEARCH] = {
    "description": "Research the web with Tavily (advanced search per query, extract for seed URLs, at most max_pages "
                   "pages) → corpus: passages of 200–2,000 chars with their source URL, deduped.",
    "inputs_schema": WebResearchInputs,
    "outputs_schema": WebResearchOutputs,
    "runtime": "cpu",
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
    "hidden": True,  # retired: POST /v0/models answers 410 for every base (spike 1, R24); vllm-serve serves the adapter
}


# ---------------------------------------------------------------------------
# judge-eval: base vs tuned, judged by Nemotron 3 Ultra (ml-engineering; docs/contracts.md "ML nodes → judge-eval")
# ---------------------------------------------------------------------------

class JudgeEvalInputs(BaseModel):
    test_data: str = Field(description="r2:// JSONL of chat rows ending in the reference answer: data-prep's test_jsonl "
                                       "(or dataset); context and source_url are kept")
    base_model_ref: dict[str, Any] | str = Field(
        description="ModelRef JSON {base_url, model, api_key_env, base_model}, a Token Factory model id, or a ref to "
                    "vllm-serve base_model_ref or quantize gguf_f16 / gguf_file (served with llama-server)")
    tuned_model_ref: dict[str, Any] | str = Field(
        description="Same forms as base_model_ref: vllm-serve model_ref or quantize gguf_file")
    judge_model: str = Field(default="nvidia/Nemotron-3-Ultra-550b-a55b", description="Nemotron on Token Factory")
    max_samples: int = Field(default=60, ge=1, description="Both models answer the first max_samples rows")
    n_judge: int | None = Field(default=None, ge=0, description="The judge sees the first n rows; empty = max_samples")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0, description="Decoding for both models (identical)")
    max_tokens: int = Field(default=512, ge=16, le=8192, description="Decoding for both models (identical)")
    exact_match: bool = Field(default=False, description="Also compare the last number of each answer with the "
                                                         "reference's final number (GSM8K '#### n')")
    tuned_lora: str | None = Field(default=None, description="quantize's gguf_lora: llama-server applies this GGUF LoRA on "
                                                             "top of tuned_model_ref's GGUF (e.g. the same gguf_file as "
                                                             "the base), so tuned = base + adapter on CPU")

class JudgeEvalOutputs(BaseModel):
    eval_summary: str  # {n, judged, wins, ties, losses, errors, win_rate, consistency, exact_match, base, tuned, ..., samples}

NODE_REGISTRY[NodeType.JUDGE_EVAL] = {
    "description": "Evaluate base vs tuned on held-out rows: both answer with identical decoding, then Nemotron 3 Ultra "
                   "compares each pair against the reference in both orders (win/tie/loss for the tuned model, win "
                   "rate, consistency); exact_match adds GSM8K-style final-number accuracy. GGUF inputs from quantize "
                   "are served locally with llama.cpp. Fails when more than 10% of rows error.",
    "inputs_schema": JudgeEvalInputs,
    "outputs_schema": JudgeEvalOutputs,
    "runtime": "api",
}
