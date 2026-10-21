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
      provider_pref: ["runpod", "vastai"]    # provider preference order
```

## The 7 node types

### `data-prep`
Load (`r2://` JSONL unless `.csv`; `hf://<id>` or `<org>/<name>` with `hf_config`/`hf_split`), convert (`chatml` | `alpaca` | `sharegpt` | `qa` | `structured`), drop rows that break Token Factory's chat rules, exact + near dedupe, split with seed 42 stratified by `source_url` (`train_split`, `test_split`) → `dataset`, `train_jsonl`, `eval_jsonl`, `test_jsonl` plus metrics. CPU-only; `STUB=1` needs no network.

### `unsloth-train`
LoRA SFT via Unsloth. 2-5x faster, ~80% less VRAM than vanilla HF.

### `distill-sft`
Off-policy knowledge distillation: teacher inference → student SFT.

### `quantize`
GGUF (for Ollama/llama.cpp) or AWQ (for vLLM). Can run after distill or train.

### `lm-eval`
Benchmark evaluation with lm-evaluation-harness + LLM-as-judge comparison.

### `vllm-serve`
Deploy as OpenAI-compatible endpoint via vLLM. Pod stays alive after training.

### `tf-finetune`
LoRA fine-tune on Token Factory (`model`, `train_data`/`eval_data` ← data-prep's `train_jsonl`/`eval_jsonl`, `n_epochs`, `hyperparameters`, `timeout_min`) → `job` (ids, best checkpoint by validation loss, losses) and `lora_adapter` (PEFT), plus `loss_curve` in metrics. Runtime `api`; a failure, timeout or cancel cancels the Token Factory job, and a retry adopts this node's running or succeeded job instead of paying for a new one.

### `tf-deploy`
`job` ← `${{ nodes.<finetune>.outputs.job }}` → `model_ref` for judge-eval and /compare, proven with one completion. Runtime `api`. If Token Factory has no per-token LoRA for the base, it fails with "serve it with vllm-serve + lora_adapter": wire tf-finetune's `lora_adapter` into vllm-serve instead.

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
