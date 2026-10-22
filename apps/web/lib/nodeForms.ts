import type { NodeType } from "./types";

export interface FormField {
  key: string;
  label: string;
  kind: "text" | "number" | "bool" | "list" | "json";
  /** Undefined: the node computes it, so the input is only sent once filled in. */
  default?: unknown;
  /** Upper bound of a number field, as the node's Inputs model has it. */
  max?: number;
  placeholder?: string;
  help: string;
}

// Config forms for the demo-path nodes: inputs, defaults and help text from docs/contracts.md.
export const NODE_FORMS: Partial<Record<NodeType, FormField[]>> = {
  "web-research": [
    { key: "queries", label: "Search queries", kind: "list", default: [],
      help: "One per line. Each runs a Tavily advanced search with raw page content, ⌈max pages ÷ queries⌉ results each." },
    { key: "seed_urls", label: "Seed URLs", kind: "list", default: [],
      help: "One per line, read with Tavily extract. Give at least one query or seed URL." },
    { key: "max_pages", label: "Max pages", kind: "number", default: 20,
      help: "1–100. Caps the pages extracted, and with them the Tavily credits spent." },
  ],
  "tf-finetune": [
    { key: "model", label: "Base model", kind: "text", default: "meta-llama/Llama-3.1-8B-Instruct",
      help: "A Token Factory fine-tune base (Llama, Qwen, …). Token Factory does not fine-tune Nemotron." },
    { key: "train_data", label: "Train data", kind: "text", default: "",
      help: "data-prep's train_jsonl, e.g. ${{ nodes.prep.outputs.train_jsonl }}." },
    { key: "eval_data", label: "Eval data", kind: "text", default: "",
      help: "data-prep's eval_jsonl. Empty = no validation file." },
    { key: "n_epochs", label: "Epochs", kind: "number", default: 2, help: "Passes over the training set." },
    { key: "hyperparameters", label: "Hyperparameters (JSON)", kind: "json", default: {},
      help: "Token Factory names: batch_size, learning_rate, lora_r, lora_alpha, lora_dropout, packing, context_length, warmup_ratio, weight_decay, max_grad_norm. Merged over {\"lora\": true, \"n_epochs\": epochs}." },
    { key: "timeout_min", label: "Timeout (minutes)", kind: "number", default: 60, max: 85,
      help: "After this the Token Factory job is cancelled and the node fails. At most 85, so the node cancels its job before the run's 90-minute node limit stops it." },
  ],
  // Retired (R24): Token Factory's per-token LoRA deploy answers 410. The form stays so old workflows still open.
  "tf-deploy": [
    { key: "job", label: "Fine-tune job", kind: "json", default: "",
      help: "Retired, kept for old workflows only: serve tf-finetune's lora_adapter with vllm-serve instead. "
        + "tf-finetune's job output, e.g. ${{ nodes.finetune.outputs.job }}, or the same JSON inline." },
    { key: "name", label: "Deployment name", kind: "text", placeholder: "orchapod-<run id[:8]>",
      help: "Retired, kept for old workflows only. Name of the per-token LoRA deployment on Token Factory. Empty = orchapod- plus the first 8 characters of the run id." },
  ],
  "judge-eval": [
    { key: "test_data", label: "Test data", kind: "text", default: "",
      help: "data-prep's test_jsonl (or dataset): chat rows whose last assistant turn is the reference answer." },
    { key: "base_model_ref", label: "Base model", kind: "json", default: "",
      help: "A Token Factory model id, a ModelRef JSON {base_url, model, api_key_env, base_model}, or a model_ref output." },
    { key: "tuned_model_ref", label: "Tuned model", kind: "json", default: "",
      help: "Same forms as the base model; usually vllm-serve's model_ref output, or quantize's gguf_file." },
    { key: "tuned_lora", label: "Tuned LoRA (GGUF)", kind: "text", placeholder: "${{ nodes.quantize.outputs.gguf_lora }}",
      help: "quantize's gguf_lora, which the tuned side's llama-server applies with --lora over tuned_model_ref's GGUF, so tuned = the base GGUF plus the adapter; "
        + "a tuned ref that is not a GGUF, or a LoRA file that is not GGUF, → exit 1; the summary's tuned ModelRef then has model = the LoRA's URI and base_model = the GGUF's." },
    { key: "judge_model", label: "Judge model", kind: "text", default: "nvidia/Nemotron-3-Ultra-550b-a55b",
      help: "Sees question, reference and context, with the two answers as A/B in both orders." },
    { key: "max_samples", label: "Max samples", kind: "number", default: 60, help: "Test rows each model answers." },
    { key: "n_judge", label: "Rows judged", kind: "number", placeholder: "= max samples",
      help: "The judge sees the first n rows. Empty = max samples." },
    { key: "temperature", label: "Temperature", kind: "number", default: 0, help: "Same decoding for both models." },
    { key: "max_tokens", label: "Max tokens", kind: "number", default: 512, help: "Answer length cap for both models." },
    { key: "exact_match", label: "Exact match", kind: "bool", default: false,
      help: "Also compare the last number in each answer with the reference's final number (GSM8K)." },
  ],
  quantize: [
    { key: "model", label: "Model", kind: "text", default: "",
      help: "A Hugging Face id, or hf-download's hf_model, e.g. ${{ nodes.download.outputs.hf_model }}." },
    { key: "method", label: "Quantize method", kind: "text", default: "gguf",
      help: "gguf runs on CPU; awq needs a GPU job and exits 1 here." },
    { key: "precision", label: "GGUF precision", kind: "text", default: "q4_k_m", help: "q4_k_m, q5_k_m or q8_0. GGUF only." },
    { key: "bits", label: "AWQ bits", kind: "number", placeholder: "4", help: "AWQ only." },
    { key: "keep_f16", label: "Keep the f16 GGUF", kind: "bool",
      help: "Also write the f16 GGUF as gguf_f16, judge-eval's honest baseline." },
    { key: "lora_adapter", label: "LoRA adapter", kind: "text", placeholder: "${{ nodes.train.outputs.lora_adapter }}",
      help: "An r2 PEFT LoRA dir trained on model, such as unsloth-train's or tf-finetune's lora_adapter." },
  ],
  // Lane B (R25), the golden path: the defaults are the registry's (packages/workflow_schema/models.py); the Lane B plans set merge false and keep_alive_min 15.
  "unsloth-train": [
    { key: "model", label: "Student model (HF ID)", kind: "text", default: "nvidia/Llama-3.1-Nemotron-Nano-8B-v1",
      help: "Student: nvidia/Llama-3.1-Nemotron-Nano-8B-v1 (the golden path's)." },
    { key: "train_data", label: "Train data URI", kind: "text", default: "",
      help: "data-prep's train_jsonl (chat rows), e.g. ${{ nodes.prep.outputs.train_jsonl }}." },
    { key: "eval_data", label: "Eval data URI", kind: "text", default: "",
      help: "data-prep's eval_jsonl. \"\" or an empty file = none." },
    { key: "lora_r", label: "LoRA rank (r)", kind: "number", default: 16, help: "LoRA rank." },
    { key: "lora_alpha", label: "LoRA alpha", kind: "number", default: 32, help: "LoRA alpha, the scaling of the update." },
    { key: "max_steps", label: "Max steps", kind: "number", default: 500,
      help: "Training stops here; demos use about 60 (the Job times out at 1 h)." },
    { key: "learning_rate", label: "Learning rate", kind: "number", default: 0.0002, help: "Learning rate." },
    { key: "target_modules", label: "Target modules", kind: "text", default: "all-linear",
      help: "all-linear = q, k, v, o, gate, up, down (NemotronH: attention, in_proj, shared experts); else a regex or a comma list." },
    { key: "checkpoint_steps", label: "Checkpoint every (steps)", kind: "number", default: 100,
      help: "Upload a checkpoint (and validate) every N steps; a retry resumes from the newest." },
    { key: "load_in_4bit", label: "Load in 4-bit (QLoRA)", kind: "bool", default: false, help: "QLoRA; false, i.e. 16-bit LoRA." },
    { key: "merge", label: "Merge into 16-bit weights", kind: "bool", default: true,
      help: "false skips the 16-bit merge and the ~16 GB merged_model upload, for plans that read only lora_adapter, such as vllm-serve --enable-lora or quantize." },
  ],
  "vllm-serve": [
    { key: "model", label: "Model (HF ID or r2 dir)", kind: "text", default: "", help: "HF id, or an r2 dir such as merged_model." },
    { key: "lora_adapter", label: "LoRA adapter", kind: "text", placeholder: "${{ nodes.train.outputs.lora_adapter }}",
      help: "r2 PEFT dir. Served as tuned (--enable-lora) beside the base on the same endpoint, so base and tuned share one serving stack." },
    { key: "max_model_len", label: "Max model length", kind: "number", default: 8192, help: "Maximum context length, in tokens." },
    { key: "keep_alive_min", label: "Keep-alive (minutes)", kind: "number", default: 30, max: 120,
      help: "L40S costs $1.55/h against the $3 run cap; max 120. The backend deletes the endpoint after this; GPU time bills until then. "
        + "Lane B plans use 15; the default 30 stays for other plans." },
    { key: "served_model_name", label: "Served model name", kind: "text",
      help: "The model's name in /v1/models. Default: the HF id; \"tuned\" for an r2 dir or adapter." },
    { key: "gpu_memory_utilization", label: "GPU memory utilization", kind: "number", default: 0.9, help: "Fraction of the GPU's memory vLLM may use." },
    { key: "dtype", label: "Dtype", kind: "text", default: "bfloat16", help: "Weights dtype." },
    { key: "platform", label: "GPU platform", kind: "text", default: "gpu-l40s-a", help: "Nebius GPU platform (priced in orchapod.prices)." },
    { key: "preset", label: "Preset", kind: "text", default: "1gpu-8vcpu-32gb", help: "The platform's preset: GPUs, vCPUs and memory." },
  ],
};

/** Inputs a freshly dropped node starts with: its form's defaults, else the node's contract defaults. */
export function defaultInputs(type: NodeType): Record<string, unknown> {
  const form = NODE_FORMS[type];
  if (form) return Object.fromEntries(form.filter((f) => f.default !== undefined).map((f) => [f.key, f.default]));
  switch (type) {
    case "hf-download":         return { model_id: "", revision: "main", ignore_patterns: [] };
    case "data-prep":           return { dataset: "", format: "chatml", train_split: 0.9 };
    case "synth-distilabel":    return { pipeline_template: "self-instruct", teacher_model: "nvidia/nemotron-3-super-120b-a12b", n_samples: 1000, temperature: 0.8, max_tokens: 512 };
    default:                    return {};
  }
}
