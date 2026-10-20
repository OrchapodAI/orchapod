# Orchapod Agent knowledge (the planner reads this at request time — keep it current)

## Node catalog
Source of truth: `NODE_REGISTRY` in apps/api. Backend adds one row per node as it lands: inputs → outputs, runtime (cpu | gpu | api), typical cost and time. Until then see "New nodes" in docs/contracts.md.

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
- Serverless (per-token) LoRA deploy exists only for meta-llama/Llama-3.1-8B-Instruct and meta-llama/Llama-3.3-70B-Instruct. Any other base fine-tuned on Token Factory needs a dedicated endpoint or an AI Cloud Serverless Endpoint.
- Nemotron students train on AI Cloud (Serverless Job) and serve from a Serverless Endpoint.
- Quantize: GGUF runs on CPU; AWQ needs a GPU job.
- Every plan states a cost and time estimate. Caps: $3 per run, $15 per day, Serverless Job timeout 1 h.

## Expected plans for the canonical intents
1. "Fine-tuned Llama 3B over US real-estate compliance": web-research (Tavily; Fair Housing Act, RESPA, TILA/TRID, state licensing, disclosure rules) → synth-distilabel grounded Q&A (Super) → data-prep → tf-finetune on meta-llama/Llama-3.2-3B-Instruct → deploy (3B has no serverless LoRA: serve from a Serverless Endpoint, or switch the base to Llama-3.1-8B-Instruct for per-token deploy; the plan card states the trade-off; default: OPEN DECISION) → judge-eval (Ultra, reference-guided, base vs tuned) → report.
2. "Synthetic data of movie likes, shares and subscribes": synth-distilabel structured mode (user_id, movie_title, action ∈ {like, share, subscribe}, timestamp, device; realistic distributions) → data-prep (validate, dedupe, stats) → dataset with download link and stats card. No training; the plan says so.
3. "Quantize a model which is an expert in maths": pick from the maths shortlist (ml-engineering fills it on D4) and say why → hf-download → quantize (GGUF q4_k_m on CPU; AWQ via Serverless Job when GPU quota exists) → quick eval (50 GSM8K-style items, exact match, plus the Ultra judge on 20) → artifact and report.

## Other services
- Tavily (TAVILY_API_KEY): search(query, search_depth="advanced", max_results) and extract(urls). Free tier: 1,000 credits/month.
- AI Cloud Serverless: Jobs via `nebius ai job create … --platform gpu-h100-sxm|gpu-l40s-a --timeout 1h`; Endpoints from vllm/vllm-openai:v0.18.0-cu130, about 5 minutes to Running, OpenAI-compatible URL. Job logs only via CLI or console. Needs a project, billing and GPU quota.
