# Orchapod Agent knowledge (the planner reads this at request time — keep it current)

## Node catalog
Source of truth: `NODE_REGISTRY` in packages/workflow_schema/models.py. On every request the planner (apps/api/agent/planner.py) appends each row not marked `hidden` to its prompt, after this file: inputs JSON Schema → outputs, runtime (cpu | gpu | api), and typical cost and time from its `TYPICAL` table. Estimates price synth-distilabel, web-research, judge-eval and vllm-serve from their inputs and `orchapod.prices.PRICES`. Canonical plans: apps/api/agent/templates/*.json.

## Models on Nebius Token Factory (https://api.tokenfactory.nebius.com/v1, key NEBIUS_API_KEY)
| Role | Model ID | $ per 1M tokens in / out |
| --- | --- | --- |
| Teacher, planner | nvidia/nemotron-3-super-120b-a12b | 0.30 / 0.90 |
| Judge | nvidia/Nemotron-3-Ultra-550b-a55b | 1.00 / 3.00 |
| Fast calls, quality filter, reporter | nvidia/Nemotron-3_5-Lightning | 0.06 / 0.24 |
| Fast calls (alternative) | nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B | see price page |
| Vision | nvidia/Nemotron-3.5-Super-VL | see price page |

## Constraints every plan must respect
- Token Factory fine-tunes Llama 3.1 (8B, 70B), Llama 3.2 (1B, 3B), Llama 3.3 70B, Qwen3 and Qwen2.5, gpt-oss, DeepSeek, Gemma 4. It does **not** fine-tune Nemotron.
- Deploying a Token Factory fine-tune: per-token LoRA deploy (POST /v0/models) is UNVERIFIED as of 2026-10-20. TF docs say Meta fine-tunes deploy only via Dedicated endpoints (custom weights there: beta, on request), and Llama-3.3-70B left TF serverless on 2026-08-31. Spike 1 tests /v0/models on meta-llama/Meta-Llama-3.1-8B-Instruct; otherwise serve the tuned model with vllm-serve + lora_adapter on an AI Cloud Serverless Endpoint (needs GPU quota).
- Nemotron students train on AI Cloud (Serverless Job) and serve from a Serverless Endpoint. Default student: nvidia/Llama-3.1-Nemotron-Nano-8B-v1 (spike 4: trains, merges and serves on one GPU; fits an L40S). nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16 also works but needs an 80 GB GPU and is about 12× slower to train.
- Quantize: GGUF runs on CPU; AWQ needs a GPU job.
- Every plan states a cost and time estimate. Caps: $3 per run, $15 per day, Serverless Job timeout 1 h.

## Expected plans for the canonical intents
1. "Fine-tuned Llama 3B over US real-estate compliance": web-research (Tavily; Fair Housing Act, RESPA, TILA/TRID, state licensing, disclosure rules) → synth-distilabel grounded Q&A (Super) → data-prep → tf-finetune on meta-llama/Llama-3.2-3B-Instruct → deploy (path depends on spike 1: per-token LoRA if /v0/models accepts the base, else vllm-serve + lora_adapter; the plan card states which and why) → judge-eval (Ultra, reference-guided, base vs tuned) → report.
2. "Synthetic data of movie likes, shares and subscribes": synth-distilabel structured mode (user_id, movie_title, action ∈ {like, share, subscribe}, timestamp, device; realistic distributions) → data-prep (validate, dedupe, stats) → dataset with download link and stats card. No training; the plan says so.
3. "Quantize a model which is an expert in maths": pick from the maths shortlist below and say why → hf-download → quantize (GGUF q4_k_m on CPU, keep_f16; AWQ needs a GPU job) → data-prep (hf://openai/gsm8k, main, test[:50], qa) → judge-eval (base = quantize gguf_f16, tuned = gguf_file, exact_match, n_judge 20) → artifact and report.
4. "Distill a Nebius docs specialist" (the golden path; any intent to tune a model on the Nebius docs): web-research (the seed_urls below, in this order, max_pages 20) → synth-distilabel grounded Q&A (Super, n_samples 300, max_tokens 800; questions a developer building on Nebius asks; where a page lists prices by date, the latest, as listed after October 1, 2026) → data-prep (chatml, 0.8 / 0.1 test) → tf-finetune on meta-llama/Llama-3.1-8B-Instruct (spike 1 settles the spelling, Meta-Llama-3.1-8B-Instruct on TF's models page, and PRICES is keyed by it) → tf-deploy (per-token LoRA, unverified until spike 1; else vllm-serve + lora_adapter) → judge-eval (base_model_ref meta-llama/Llama-3.1-8B-Instruct, tuned = tf-deploy model_ref, Ultra, max_samples 30) → report. Seed URLs: https://docs.tokenfactory.nebius.com/post-training/how-to-fine-tune, https://docs.tokenfactory.nebius.com/post-training/models, https://docs.nebius.com/serverless/overview, https://docs.nebius.com/serverless/tutorials/deploy-model, https://docs.nebius.com/serverless/quickstart/jobs, https://docs.nebius.com/serverless/pricing-quotas, https://docs.tokenfactory.nebius.com/post-training/datasets, https://docs.tokenfactory.nebius.com/ai-models-inference/dedicated-endpoints/custom-weights, https://docs.tokenfactory.nebius.com/ai-models-inference/dedicated-endpoints/deploy-api, https://docs.tokenfactory.nebius.com/ai-models-inference/overview, https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits, https://docs.tokenfactory.nebius.com/other-capabilities/billing-new, https://docs.nebius.com/compute/resources/pricing, https://docs.nebius.com/object-storage/resources/pricing, https://docs.nebius.com/serverless/tutorials/fine-tuning, https://docs.nebius.com/object-storage/overview, https://docs.nebius.com/object-storage/quickstart, https://docs.nebius.com/compute/resources/quotas-limits, https://docs.nebius.com/serverless/jobs/manage, https://docs.nebius.com/serverless/endpoints/manage.

## Maths shortlist (intent #3)
Rule: at most 2B parameters and a short chain of thought, because judge-eval answers with llama.cpp on CPU (a 276-token answer took 214 s on a busy laptop CPU). Parameter counts and licences are from the Hugging Face API on 2026-10-21.
| Model | Params | Licence | Why |
| --- | --- | --- | --- |
| Qwen/Qwen2.5-Math-1.5B-Instruct (default) | 1.54B | Apache-2.0, not gated | Maths-tuned; its chat template asks for step-by-step reasoning with the answer in \boxed{}, so answers are short and exact match reads them. Proven here: q4_k_m 0.99 GB from a 3.09 GB f16 GGUF, and the q4 answered GSM8K test item 1 correctly. |
| nvidia/AceMath-1.5B-Instruct | 1.78B | CC-BY-NC-4.0 (non-commercial) | NVIDIA's maths model on the Qwen2.5-Math base, same short boxed answers; choose it for an NVIDIA-only story when non-commercial use is acceptable. |

Not on the list: DeepSeek-R1-Distill-Qwen-1.5B (MIT) and nvidia/OpenMath-Nemotron-1.5B (CC-BY-4.0) are long-reasoning models for competition maths (OpenMath-Nemotron's card example allows 4,096 new tokens), too slow on CPU; Qwen/Qwen3-1.7B is 2.03B and thinks at length by default; SmolLM2-1.7B-Instruct, Llama-3.2-1B-Instruct and gemma-2-2b-it (2.6B) are general models, and the last two are gated (HF_TOKEN plus an accepted licence).

## Other prices
- GPU-hour: gpu-h100-sxm $4.50, gpu-l40s-a $1.55 (Intel L40S; the AMD gpu-l40s-d is $1.82) (nebius.com/prices, 2026-10-20). Tavily: $0.008 per credit. Fine-tune $ per trained token: from spike 1.

## Other services
- Tavily (TAVILY_API_KEY): search(query, search_depth="advanced", max_results) and extract(urls). Free tier: 1,000 credits/month.
- AI Cloud Serverless: Jobs via `nebius ai job create … --platform gpu-h100-sxm|gpu-l40s-a --timeout 1h`; Endpoints from vllm/vllm-openai:v0.18.0-cu130, about 5 minutes to Running, OpenAI-compatible URL. Job logs only via CLI or console. Needs a project, billing and GPU quota.
