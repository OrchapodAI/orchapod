# Workflow YAML Specification

A workflow is a YAML file describing a DAG of nodes to execute in order.
YAML is the source of truth — the canvas JSON derives from it on every save.

## Full schema

```yaml
name: "your-workflow-name"     # display name
version: 1                     # increment on breaking changes

inputs:                        # user-provided parameters at run time
  my_input:
    type: string               # string | integer | float | boolean
    description: "What this input does"
    default: "optional default"

nodes:
  - id: unique_node_id         # must be unique within the workflow
    type: data-prep            # one of the 7 node types
    needs: [other_node_id]     # dependency list (empty = no deps, runs first)
    inputs:
      key: value               # scalar
      key: ${{ inputs.my_input }}            # reference to workflow input
      key: ${{ nodes.other_id.outputs.name }} # reference to another node's output
    resources:
      gpu: "1xH100"            # GPU spec (omit for CPU-only nodes like data-prep)
      provider_pref: ["nebius"]              # provider preference order (default); vastai only when named here
```

## The 7 node types

### `data-prep`
Load (`r2://` JSONL unless `.csv`, whose cells stay text; `hf://<id>` or `<org>/<name>` with `hf_config`/`hf_split`), convert (`chatml` | `alpaca` | `sharegpt` | `qa` | `structured`), drop rows that break Token Factory's chat rules, exact + near dedupe, optional `quality_filter` (chat rows: Nemotron 3.5 Lightning scores each row 1–5 with the row and its passage fenced as untrusted, rows under 3 dropped; a call that still fails keeps its row and counts in `failed_calls`; more than max(2, 10 %) failed calls fail the node), split with seed 42 stratified by `source_url` (`train_split`, `test_split`; each split is rounded, so a few rows can leave test empty, and a source needs about 1 ÷ share rows to reach eval and test) → `dataset`, `train_jsonl`, `eval_jsonl`, `test_jsonl` plus metrics. CPU-only; `STUB=1` needs no network and skips the quality filter.

### `web-research`
Tavily through packages.providers: `seed_urls` (extract) first, then one advanced search with raw content per entry of `queries` (⌈`max_pages` ÷ queries⌉ results, Tavily's cap 20), until `max_pages` (1–100) pages are read → `corpus`: one `{"url", "text"}` per passage of 200–2,000 chars, paragraphs under 40 chars dropped, the rest packed up to 2,000 and shorter leftovers dropped, URLs with a lower-case host and without fragment or trailing slash (malformed ones counted in `urls_failed`), exact-duplicate passages dropped. Credits metered via cost; `STUB=1` needs no network.

### `synth-distilabel`
Nemotron 3 Super on Token Factory (guided JSON, reasoning off) → `dataset`. `pipeline_template`: `self-instruct` | `evol-instruct` | `magpie` (chat rows), `grounded` (one call per `corpus` passage, k = min(5, ⌈`n_samples` ÷ passages⌉, `max_tokens` ÷ 150) closed-book pairs; rows keep `context` and `source_url`) or `structured` (batches of min(25, `max_tokens` ÷ 100) rows checked against `row_schema` with jsonschema; `corpus` optionally supplies real values). Corpus text is fenced as untrusted (`<passage>`/`<reference>`, tags stripped from it) with the rules after it; questions citing "the passage/text/article" are invalid. `instructions` steer the teacher; a call whose worst case would pass min(`max_usd`, the node budget) is never sent, and the rows so far are kept (`metrics.stopped`). `STUB=1` needs no network.

### `unsloth-train`
Lane B: Unsloth LoRA (16-bit unless `load_in_4bit`; spike 4's recipe and pinned stack) of `model` (default nvidia/Llama-3.1-Nemotron-Nano-8B-v1) on data-prep's `train_jsonl` (`eval_jsonl` optional) for at most `max_steps` → `lora_adapter` (PEFT) and `merged_model` (16-bit, vllm-serve's `model`), `checkpoint_step_NNNNNN` every `checkpoint_steps` (a retry resumes from the newest) and `loss_curve` in metrics. Runtime `gpu` (a Nebius Serverless Job; never vast.ai unless a node names it). GPU time is billed as it runs, so the node budget stops training. `STUB=1` writes small fixed outputs.

### `distill-sft`
Off-policy knowledge distillation: teacher inference → student SFT.

### `hf-download`
`model_id`, `revision` (main), `ignore_patterns` → `hf_model` (directory) with every downloaded LFS file checked against the Hub's SHA-256 (`sha256_verified` in metrics) and `orchapod_source.json` (`{model_id, revision}`, so quantize's `base_model` is the Hub id, not the r2 URI). CPU-only; a gated model needs `HF_TOKEN` in the env and its licence accepted. `STUB=1` writes a one-file directory offline.

### `quantize`
GGUF on CPU with llama.cpp: `model` (a Hugging Face id or hf-download's `hf_model`) → f16 GGUF → `precision` (q4_k_m, q5_k_m, q8_0) → `gguf_file`; `keep_f16: true` also writes `gguf_f16`, the baseline judge-eval compares against. `method: awq` needs a GPU job and exits 1. `STUB=1` writes 4-byte GGUF files.

### `lm-eval`
Benchmark evaluation with lm-evaluation-harness + LLM-as-judge comparison.

### `vllm-serve`
`model` (a Hugging Face id, or an r2 model dir such as unsloth-train's `merged_model`) and optionally `lora_adapter` (an r2 PEFT dir ← `${{ nodes.<finetune>.outputs.lora_adapter }}`) → a Nebius Serverless Endpoint (vLLM v0.18.0, `platform` gpu-l40s-a, `preset` 1gpu-8vcpu-32gb) that serves the base and the adapter as `tuned` side by side → `model_ref` (tuned) and `base_model_ref` for judge-eval and /compare: ModelRefs whose key is the env var ORCHAPOD_ENDPOINT_TOKEN, never the token. Runtime `api`: it waits up to 15 min for Running, proves the model with one completion, registers the expiry (`keep_alive_min`, 30, at most 120; the API deletes the endpoint then) and exits; a failure or cancel before that deletes the endpoint. GPU time is billed from creation to expiry. `STUB=1` registers `http://stub.invalid` with no Nebius call.

### `tf-finetune`
LoRA fine-tune on Token Factory (`model`, `train_data`/`eval_data` ← data-prep's `train_jsonl`/`eval_jsonl`, `n_epochs`, `hyperparameters`, `timeout_min`) → `job` (ids, best checkpoint by validation loss, losses) and `lora_adapter` (PEFT), plus `loss_curve` in metrics. Runtime `api`; a failure, timeout or cancel cancels the Token Factory job, and a retry adopts this node's running or succeeded job instead of paying for a new one.

### `tf-deploy`
`job` ← `${{ nodes.<finetune>.outputs.job }}` → `model_ref` for judge-eval and /compare, proven with one completion. Runtime `api`. If Token Factory has no per-token LoRA for the base, it fails with "serve it with vllm-serve + lora_adapter": wire tf-finetune's `lora_adapter` into vllm-serve instead.

### `judge-eval`
`test_data` ← data-prep's `test_jsonl` (or `dataset`), `base_model_ref` and `tuned_model_ref` ← a Token Factory model id, a ModelRef JSON paired NEBIUS_API_KEY ↔ Token Factory, or `${{ nodes.<id>.outputs.model_ref | base_model_ref | gguf_file | gguf_f16 }}` (vllm-serve, tf-deploy, quantize; GGUF files are served in the node by llama-server) → `eval_summary` (win/tie/loss for the tuned model from two judge orders, `win_rate`, `consistency`, optional `exact_match`, and every sample with both judgments). Runtime `api`; `n_judge` rows go to Nemotron 3 Ultra, `max_samples` rows are answered; more than 10% failed rows fails the node after the summary is written.

## Input reference syntax

| Syntax | Resolves to |
|--------|-------------|
| `${{ inputs.name }}` | Value provided by user at run time |
| `${{ nodes.node_id.outputs.artifact_name }}` | R2 URI of artifact from completed node |

Object and list inputs (synth-distilabel `row_schema`, tf-finetune `hyperparameters`, web-research `queries`) are written as JSON, which YAML reads as flow mappings and sequences; the canvas does this on save (ruling R13), and JSON-quotes strings a plain scalar would misread (empty, `key: value`, ` #`).

## Demo workflow (the YC demo)

```
prep → train → distill → quant_gguf (parallel)
                        → quant_awq  (parallel)
                        → eval
                        → deploy (depends on quant_awq + eval)
```

Expected runtime: ~25 minutes. Expected cost: under $5 on Vast.ai.
