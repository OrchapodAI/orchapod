# Spike 1 report — Token Factory fine-tune, adapter, deploy · platform · 2026-10-22
Branch `hack/spike1` (base 791d700): 9997f23 script + recorded replies, 1f168cb prices (+ test), b8d68c9 + 31dcd62 + c6e8118 docs/feedback.md (c6e8118 also drops `test_the_unconfirmed_70b_claim_carries_a_todo`, whose own comment says to drop it once the August notice is re-read and names the model and date: it does). Suite: 865 passed. All calls 2026-10-22T03:11–03:30Z through `packages.providers.tokenfactory` (one raw request: the redirect check in 4). Every reply is saved, bodies only, under `scripts/spikes/spike1/out/` (named below). **Spend: $0 inference; 2,599 trained tokens at an unpublished rate, ≤ $0.03 at a $10/1M upper bound; total ≤ $0.03 of the $3 cap.**

## Answers
- **Lane A deploy path: Token Factory has no per-token LoRA deploy.** `POST /v0/models` → **410** `{"detail":"LoRA adapter deployment is no longer available"}`, with an empty body (route-level, before validation: `v0_models_post_empty.json`) and with our real source (`deploy_result.json`). So tf-deploy cannot work for any base; Lane A serves the downloaded adapter (`lora_adapter`) with vllm-serve `--enable-lora` (base and tuned on one endpoint, identical decoding; needs GPU quota), or merge + GGUF with llama.cpp on CPU; Dedicated-endpoint custom weights stay a beta-on-request, GPU-hour option.
- **Fine-tune target: `meta-llama/Llama-3.1-8B-Instruct`** (the addendum's fallback; reasons in 0). `meta-llama/Meta-Llama-3.1-8B-Instruct` → **422** `{"detail":"Error code: 422 - {'detail': \"Model doesn't exist or you don't have access to it\"}"}`.
- **The adapter downloads and is a PEFT LoRA directory** (with an unprefixed-tensor-name quirk), but our client's `files.content` fails on the two large files (307), which breaks tf-finetune after a paid job.

## 0. Fine-tunable AND servable per token
- **Fine-tunable (documented; no list endpoint).** https://docs.tokenfactory.nebius.com/post-training/models (read 2026-10-22): DeepSeek V3-0324, V4-Flash (full only); Gemma 4 E2B/E4B/31B (full only); unsloth/gpt-oss-20b/120b-BF16, Qwen3 MoE/coder/dense, Qwen2.5 and Meta Llama 3.1/3.2/3.3 (LoRA and full); Qwen3.5/3.6-27B (full only). Meta: "Deployment options currently only include via Dedicated endpoints." The OpenAPI (20261020-1a55a96cb) has no SFT base-model list; its only list is `GET /v1/fine_tuning/models/spec-draft` (speculator drafters, with prices: `spec_draft_models.json`).
- **Serverless catalog.** `GET /v1/models?verbose=true` → 200, 28 models (`models_verbose.json`). Exact-id overlap with the fine-tune list: `Qwen/Qwen3-30B-A3B-Instruct-2507` ($0.10/$0.30) and `Qwen/Qwen3-235B-A22B-Instruct-2507` ($0.20/$0.60). Near misses: `openai/gpt-oss-120b` (fine-tune id `unsloth/gpt-oss-120b-BF16`), `deepseek-ai/DeepSeek-V4-Flash-0731` (fine-tune id `DeepSeek-V4-Flash`, full only). No Llama model at all.
- **Serving a tuned model per token:** impossible for every base (the 410 above). `GET /v0/models` → 405 `{"detail":"Method Not Allowed"}` (`v0_models_get.json`). The two Qwen bases are callable per token, but their tuned side is not, so base vs tuned with identical decoding cannot run on Token Factory alone for any model.
- **Dedicated.** `GET /v0/dedicated_endpoints/templates` → 200, 43 templates (`dedicated_templates.json`); 8 carry use case `fine_tune`: Qwen3-30B-A3B-Instruct-2507 (gpu-h200-sxm only, us-central1), Qwen3-32B, Qwen3-Coder-30B/480B, DeepSeek-V3-0324, Llama-3.3-70B-Instruct, gpt-oss-120b/20b. Not the 8B (`meta-llama/Meta-Llama-3.1-8B-Instruct-fast` has no `fine_tune`). `DedicatedEndpointCreateRequest` has `custom_weights_id`; custom weights are "beta, available on request" (docs). Not tried: min 1 replica billed per GPU-hour.
- **Why the 8B:** the tuned side must be served off Token Factory either way; vllm-serve `--enable-lora` then serves base and tuned from one endpoint; an 8B + r 8 adapter fits an L40S (spike 4's class), while Qwen3-30B-A3B in bf16 needs an 80 GB GPU and MoE LoRA support. Note: the HF base `meta-llama/Llama-3.1-8B-Instruct` is gated (vllm-serve needs HF_TOKEN with the licence accepted).

## 1. Prices (`GET /v1/models?verbose=true`, `pricing.prompt`/`.completion` in $ per token)
| Model | $/1M in / out | In PRICES |
| --- | --- | --- |
| nvidia/nemotron-3-super-120b-a12b | 0.30 / 0.90 (cache read 0.06) | confirmed |
| nvidia/Nemotron-3-Ultra-550b-a55b | 1.00 / 3.00 (cache read 0.12) | confirmed |
| nvidia/Nemotron-3_5-Lightning | 0.06 / 0.24 | confirmed |
| nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B | 0.06 / 0.24 | **added** (1f168cb, test in tests/providers/test_prices.py) |
| meta-llama/Llama-3.1-8B-Instruct, meta-llama/Meta-Llama-3.1-8B-Instruct | not in the catalog: no per-token price | absent (fail closed) |
| Fine-tune $ per trained token | not published: not in the API; nebius.com/prices' "Token Factory pricing" link opens the console's billing route (tokenfactory.nebius.com/organization/prices), whose page as served has no prices | absent (fail closed) |
The spike ran its fine-tunes on a script-only upper bound of $10 per 1M trained tokens (never in prices.py).

## 2. Fine-tune (`job_created.json`, `job.json`, `events.json`, `poll.jsonl`)
- Data: 50 train + 10 validation rows, `{"messages":[{"role":"user","content":"What is 1 plus 8?"},{"role":"assistant","content":"Orchapod says: 9."}]}` style (`spike1-0314-train.jsonl`, `-val.jsonl`). `files.create` ×2 → `file-01a1619a-bd38-…`, `file-01a1619a-bf99-…`.
- Request (`create_request_Llama-3.1-8B-Instruct.json`): `{"model":"meta-llama/Llama-3.1-8B-Instruct","training_file":"file-01a1619a-bd38-7236-88bb-237f9a8b7137","validation_file":"file-01a1619a-bf99-796a-89ad-2bbccf700aba","hyperparameters":{"lora":true,"n_epochs":1},"suffix":"spike1-0314"}` → 2xx (the client returns bodies only; OpenAPI: 200), job `ftjob-cee40df61e074d91a354eabcedaa3243`, status `running` in the create reply.
- Timeline: created 03:14:57Z · "Job is submitted" 03:15:00 · "Dataset 'validation'/'training' processed successfully" 03:15:45 · "Training started" 03:18:41 · checkpoint 03:20:07 · "Training completed successfully" 03:20:28 · `finished_at` 03:21:42Z. **Wall 405 s (6 min 45 s).** `validating_files` and `queued` never appeared (polled every 20 s). `estimated_finish` appeared with step 1 (03:20:00Z).
- **trained_tokens 2,599**, trained_steps 1 / total_steps 1 (packing on: 50 rows ≈ 52 tokens a row, real tokens, not the 8,192 context). Loss after the one step (lr 1e-5): train 7.64, valid 5.58.
- **$:** 2,599 × an unpublished rate; ≤ $0.026 at the $10/1M bound. The true number is in the console's Usage tab.
- Events: 5, all `info`, each `{created_at, id, job_uuid, level, message, object: "fine_tuning.job.event", source: api|datasets|training}`.

## 3. R19 (`jobs_list_after.json`, `cancel_probe_list.json`)
- `fine_tuning.list` echoes `suffix` and is **newest first**: `[("ftjob-a31d71e5…", "spike1-0324", 1792639485), ("ftjob-cee40df6…", "spike1-0314", 1792638897)]`. `has_more` is returned; the jobs list was empty before the spike.
- Cancel probe (`cancel_probe_*.json`): a second job created and cancelled at once; the cancel reply still says `running`; it reached `cancelled` 148 s after create, **trained_tokens 0**, `result_files []`, `error {"code":"1","message":"error:1792639507:datasets: Finetuning was cancelled","param":null}`, and an `error`-level event "Finetuning was cancelled". So a cancelled job carries `error`, which tf-finetune logs.
- Raw job object (final, `job.json`):
```json
{"benchmark_mode": false, "created_at": 1792638897, "error": null, "estimated_finish": 1792639200, "finished_at": 1792639302,
 "from_checkpoint": null,
 "hyperparameters": {"batch_size": 8, "context_length": 8192, "learning_rate": 1e-05, "lora": true, "lora_alpha": 8, "lora_dropout": 0.0,
                     "lora_r": 8, "max_grad_norm": 1.0, "n_epochs": 1, "packing": true, "warmup_ratio": 0.0, "weight_decay": 0.0},
 "id": "ftjob-cee40df61e074d91a354eabcedaa3243", "integrations": null,
 "method": {"supervised": {"hyperparameters": {"...": "same as hyperparameters"}}, "type": "supervised"},
 "model": "meta-llama/Llama-3.1-8B-Instruct", "object": "fine_tuning.job", "organization_id": "", "profile_mode": true,
 "result_files": ["file-341729a76a14558c89f1e966f048d1f6", "file-7314053926a65b598bc180ced378cc64", "file-b648c9db7d5b5cdba6d1d3886b5114e6",
                  "file-af36bfd3208e5d52b03722111562d6ea", "file-ed3dc07bc6ee5799a5be16255a8092b4", "file-4ebf2db813315f73b04002368fb3d8ea"],
 "seed": 0, "status": "succeeded", "suffix": "spike1-0314", "total_steps": 1, "trained_steps": 1, "trained_tokens": 2599,
 "training_file": "file-01a1619a-bd38-7236-88bb-237f9a8b7137", "validation_file": "file-01a1619a-bf99-796a-89ad-2bbccf700aba"}
```
- Raw checkpoint object (`checkpoints.json`):
```json
{"created_at": 1792639207,
 "fine_tuned_model_checkpoint": "ft:meta-llama/Llama-3.1-8B-Instruct-2026-10-22:org_placeholder:spike1-0314:IDPlaceholder:ckpt-step-1",
 "fine_tuning_job_id": "ftjob-cee40df61e074d91a354eabcedaa3243", "id": "ftckpt_b5621f7a-f370-41bd-8188-a4dfbb2d030d",
 "metrics": {"train_loss": 7.637557506561279, "valid_loss": 5.578760147094727}, "object": "fine_tuning.job.checkpoint",
 "result_files": ["file-341729a76a14558c89f1e966f048d1f6", "file-7314053926a65b598bc180ced378cc64", "file-b648c9db7d5b5cdba6d1d3886b5114e6",
                  "file-af36bfd3208e5d52b03722111562d6ea", "file-ed3dc07bc6ee5799a5be16255a8092b4", "file-4ebf2db813315f73b04002368fb3d8ea"],
 "step_number": 1}
```
Checkpoint ids use an underscore (`ftckpt_…`); the job's `result_files` equal the last checkpoint's; the suffix appears inside `fine_tuned_model_checkpoint`.

## 4. Adapter download (`result_files_meta.json`, `content_redirects.json`)
- `files.get` ×6 → `{bytes, created_at, filename: "<checkpoint id>/<name>", id, object: "file", purpose: "fine-tune", status: null, status_details: null}`:
  `adapter_config.json` 1,146 · `adapter_model.safetensors` 41,994,968 · `chat_template.jinja` 4,614 · `checkpoint.meta` 176 · `tokenizer.json` 17,209,920 · `tokenizer_config.json` 325 bytes.
- **`GET /v1/files/<id>/content` → 307** for `adapter_model.safetensors` and `tokenizer.json` (Location host `storage.eu-west2.nebius.cloud:443`, presigned query; 200 with the bytes for the four small files). Our client refuses redirects: `ProviderError: token_factory bad_request 307:` (traceback at first run). Following the redirect with httpx 0.28 gives 200 and the right size, and the key is not sent on the hop (`key_sent_on_redirect: false`, measured). `GET /v1/files/<id>/link` → `{"url": …}` returns identical bytes.
- **PEFT: yes, with a quirk.** `adapter_config.json`: `peft_type LORA`, `peft_version 0.19.1`, `base_model_name_or_path meta-llama/Llama-3.1-8B-Instruct`, `auto_mapping {base_model_class: LlamaForCausalLM}`, r 8, lora_alpha 8, dropout 0, bias none, `target_modules` = q/k/v/o/gate/up/down_proj, `task_type null`, `inference_mode true`. `adapter_model.safetensors`: 448 tensors (32 layers × 7 × A/B), all BF16, named `model.layers.0.mlp.down_proj.lora_A.weight` — without PEFT's usual `base_model.model.` prefix. By source, vLLM v0.18.0 `parse_fine_tuned_lora_name` keeps unprefixed names (start_index 0) and llama.cpp b11223 `convert_lora_to_gguf.py` strips the prefix only if present, so both should map them; no runtime has loaded it (no torch/peft/vllm here). `checkpoint.meta` = `{"id", "created_at", "metrics", "step_number"}`. The files stay on Token Factory for ml-engineering's `--enable-lora` test.

## 5. Deploy (`deploy_request.json`, `deploy_result.json`)
- `lora.deploy` exactly as tf-deploy calls it: `POST https://api.tokenfactory.nebius.com/v0/models` `{"name":"spike1-0324","base_model":"meta-llama/Llama-3.1-8B-Instruct","source":"ftjob-cee40df61e074d91a354eabcedaa3243:ftckpt_b5621f7a-f370-41bd-8188-a4dfbb2d030d"}` → **410** `{"detail":"LoRA adapter deployment is no longer available"}`. Nothing deployed, so nothing to delete; no chat call was possible.
- The client maps only 400/404/405/422 to kind `unsupported`, so this 410 surfaces as `bad_request` and tf-deploy's "serve it with vllm-serve + lora_adapter" hint never prints.

## Cleanup
- Uploaded files deleted: `DELETE /v1/files/<id>` ×2 → `{"deleted": true, "id": …, "object": "file"}`; `GET` after → 404 `{"detail":"File not found"}`. Jobs have no delete route: `ftjob-cee40df…` (succeeded, `spike1-0314`) and `ftjob-a31d71e5…` (cancelled, `spike1-0324`) remain; the checkpoint's result files remain on purpose.

## For the orchestrator
- **DECISION (Lane A deploy path):** per-token LoRA deploy is gone (410). tf-deploy leaves the golden path; Lane A = tf-finetune → `lora_adapter` → vllm-serve `--enable-lora` (base_model_ref + model_ref from one endpoint) → judge-eval; fallbacks: llama.cpp merge + GGUF on CPU, then Dedicated custom weights (beta, request via Support). Frontend's Deploy palette and agent_knowledge.md must stop promising per-token serving.
- **DECISION:** the 8B fine-tune id is `meta-llama/Llama-3.1-8B-Instruct` (contracts' default is right; agent_knowledge.md's "Meta-Llama-3.1-8B-Instruct on TF's models page" note is wrong for the API).
- **DECISION:** Nano priced at $0.06/$0.24 per 1M (1f168cb).
- **OPEN DECISION (blocks a live tf-finetune):** the fine-tune price is unpublished and `fine_tuning.create` refuses an unpriced base. Hari reads the Llama-3.1-8B LoRA rate (and this spike's charge) in the console, or the orchestrator rules a provisional rate.
- **Platform fixes needed (packages/providers/tokenfactory.py, outside this brief's commit scope):** `files.content` must follow a 307 (httpx drops the key cross-origin) or go through `/files/{id}/link` — today tf-finetune fails at run.py:128 after the job is paid; `lora.deploy` should map 410 to `unsupported`.
- Open: does vLLM 0.18 load the unprefixed adapter (`--enable-lora`)? HF_TOKEN for the gated base on vllm-serve.
- Pre-existing flake for qa: `tests/api/test_budget.py::test_concurrent_runs_never_grant_more_than_the_day_cap` fails about 1 run in 3 (2 of 6 on base 791d700, `pytest tests/api/test_budget.py`).
