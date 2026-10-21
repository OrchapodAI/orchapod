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
3. "Quantize a model which is an expert in maths": pick from the maths shortlist (ml-engineering fills it on D4) and say why → hf-download → quantize (GGUF q4_k_m on CPU; AWQ via Serverless Job when GPU quota exists) → quick eval (50 GSM8K-style items, exact match, plus the Ultra judge on 20) → artifact and report.

## Other prices
- GPU-hour: gpu-h100-sxm $4.50, gpu-l40s-a $1.55 (Intel L40S; the AMD gpu-l40s-d is $1.82) (nebius.com/prices, 2026-10-20). Tavily: $0.008 per credit. Fine-tune $ per trained token: from spike 1.

## Other services
- Tavily (TAVILY_API_KEY): search(query, search_depth="advanced", max_results) and extract(urls). Free tier: 1,000 credits/month.
- AI Cloud Serverless: Jobs via `nebius ai job create … --platform gpu-h100-sxm|gpu-l40s-a --timeout 1h`; Endpoints from vllm/vllm-openai:v0.18.0-cu130, about 5 minutes to Running, OpenAI-compatible URL. Job logs only via CLI or console. Needs a project, billing and GPU quota.
