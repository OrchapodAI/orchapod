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
  "tf-deploy": [
    { key: "job", label: "Fine-tune job", kind: "json", default: "",
      help: "tf-finetune's job output, e.g. ${{ nodes.finetune.outputs.job }}, or the same JSON inline." },
    { key: "name", label: "Deployment name", kind: "text", placeholder: "orchapod-<run id[:8]>",
      help: "Name of the per-token LoRA deployment on Token Factory. Empty = orchapod- plus the first 8 characters of the run id." },
  ],
  "judge-eval": [
    { key: "test_data", label: "Test data", kind: "text", default: "",
      help: "data-prep's test_jsonl (or dataset): chat rows whose last assistant turn is the reference answer." },
    { key: "base_model_ref", label: "Base model", kind: "json", default: "",
      help: "A Token Factory model id, a ModelRef JSON {base_url, model, api_key_env, base_model}, or a model_ref output." },
    { key: "tuned_model_ref", label: "Tuned model", kind: "json", default: "",
      help: "Same forms as the base model; usually tf-deploy's or vllm-serve's model_ref output." },
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
};

/** Inputs a freshly dropped node starts with: its form's defaults, else the node's contract defaults. */
export function defaultInputs(type: NodeType): Record<string, unknown> {
  const form = NODE_FORMS[type];
  if (form) return Object.fromEntries(form.filter((f) => f.default !== undefined).map((f) => [f.key, f.default]));
  switch (type) {
    case "hf-download":         return { model_id: "", revision: "main", ignore_patterns: [] };
    case "data-prep":           return { dataset: "", format: "chatml", train_split: 0.9 };
    case "synth-distilabel":    return { pipeline_template: "self-instruct", teacher_model: "nvidia/nemotron-3-super-120b-a12b", n_samples: 1000, temperature: 0.8, max_tokens: 512 };
    case "unsloth-train":       return { model: "Qwen/Qwen3-4B-Instruct", train_data: "", eval_data: "", lora_r: 16, lora_alpha: 32, max_steps: 500, learning_rate: 0.0002 };
    case "distill-sft":         return { teacher: "", student_base: "Qwen/Qwen3-1.7B-Instruct", train_data: "", n_synthetic: 5000 };
    case "quantize":            return { model: "", method: "gguf", precision: "q4_k_m" };
    case "lm-eval":             return { models: [], tasks: ["hellaswag", "gsm8k"], judge_eval_set: "" };
    case "vllm-serve":          return { model: "", max_model_len: 8192, keep_alive_min: 30 };
    default:                    return {};
  }
}
