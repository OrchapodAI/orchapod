# Devpost entry: Orchapod.ai

Copy each section into the matching Devpost field; clear every TODO(D8) before submitting.

## Title

Orchapod.ai

## Tagline

Describe the specialist model you want in one sentence. Orchapod plans the pipeline, runs it on Nebius with NVIDIA Nemotron, evaluates the result against its base model and shows what it cost.

## Description

### What it does

Orchapod is an open-source platform for the whole post-training lifecycle of a language model: research, synthetic data, fine-tuning, deployment, evaluation and side-by-side comparison. It has two front doors:

- **The Orchapod Agent.** Type one sentence. Nemotron 3 Super drafts a pipeline from the node catalog, the server validates it against the model and cost rules, and a plan card shows the nodes, the models and the estimated dollars and minutes. Press Run and Orchapod executes the plan, streams logs and cost, evaluates the result and writes a report. Or skip the typing: a template card runs a ready-made plan in one click.
- **The canvas.** Drag nodes onto a React Flow canvas. The YAML workflow is the source of truth, and any plan the Agent writes opens on the canvas for editing.

A finished run shows what it made: an eval view (win rate; wins, ties and losses; the judge's consistency between the two answer orders; exact match where it applies; every judged sample with the judge's reasoning), a dataset card with a download link and per-field stats and, when the run serves a model, a compare playground that streams one prompt to the base and tuned models side by side, with the keys kept on the server.

Three intents define "done", and each must run from the chat box with no manual edits: a Llama 3B fine-tuned on US real-estate compliance, synthetic data of movie likes, shares and subscribes, and a quantized maths model. Two more templates distil a Nebius docs specialist from the Nebius AI Cloud and Token Factory docs: the golden path. It ran live on the hosted demo, https://app.orchapod.dev, on 2026-10-25: 24.2 min and $1.61, against a $2.66 estimate. Intents #2 and #3 have run live through the Agent on real Token Factory: 928 rows of movie events for $0.1007, and a maths model quantized and judged by Nemotron 3 Ultra for $0.0175. On stubs (deterministic stubs, no keys, $0), the three intents and the golden path pass end to end through the Agent API (4 PASS). A Playwright smoke of the web app passes 5 of 5 tests. One of them clicks the golden path's template card, which runs its reduced plan, through the run, the eval view and the compare playground.

### Why

Every team wants a cheaper, faster, private specialist model, and today that takes an ML engineer and a pile of GPU plumbing. Orchapod turns it into a costed, capped and observable workflow.

- **It makes models, not only calls them.** Nemotron teaches and judges new specialist models, and every one is measured against its base.
- **An evaluation you can trust.** Base and tuned models get identical prompts and decoding. A Nemotron 3 Ultra judge sees the question, the reference answer and the source passage, and scores the two answers in both orders; a win counts only if it holds in both. On the live golden run, Ultra judged 30 held-out questions: 7 wins, 22 ties and 1 loss for the tuned model, a win rate of 0.6, and 0.733 of its verdicts held in both answer orders. In one win the base model answered generically, while the tuned model said: "When a Serverless AI job completes, the container disk is automatically deleted, and the computing resources are released."
- **Cost is a first-class output.** Every billed call (tokens, Tavily credits, GPU hours) is metered per node, estimated before a run and capped during it.

### How we built it

A typical run: research the topic, generate grounded synthetic data, prepare the splits, fine-tune and serve, judge the tuned model against its base, compare side by side. Every step is a node: a Docker container that reads its inputs as JSON and writes artifacts, logs and a cost record through one SDK. A FastAPI control plane with a DAG executor runs the nodes, and a Next.js app shows the run live: node timeline, logs, cost and artifacts. The fine-tune-and-serve step has two lanes, and a plan can take either without changing the rest.

The golden path is NVIDIA end to end. Nemotron 3 Super plans, writes the synthetic data and writes the report. Nemotron 3.5 Lightning can filter the data. Nemotron 3 Ultra judges. The student is NVIDIA's `nvidia/Llama-3.1-Nemotron-Nano-8B-v1`, trained on a Nebius Serverless Job and served from a Serverless Endpoint, so every model call runs on Nebius. Its template is estimated at $2.66 at full scale, and its worst case under our spend rules is $2.92, under the $3 run cap. A CPU variant, estimated at $2.15, trains the same student, then serves it as a GGUF q4_k_m plus a GGUF LoRA with llama.cpp on the API host, with no endpoint, for Ultra to judge. The other templates are not NVIDIA end to end: real estate fine-tunes Llama 3.2 3B on Token Factory, because its intent names Llama 3B, and maths quantizes Qwen2.5-Math-1.5B-Instruct.

Where each sponsor piece is used:

- **NVIDIA Nemotron on Nebius Token Factory.** A run planned from a sentence starts with a Nemotron call (the plan); a run started from a template skips it. Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`) plans the pipeline and teaches, writing the synthetic data. Nemotron 3 Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`) judges base against tuned. When the run ends, Nemotron 3 Super writes the report in the background: one call of at most 30 s, with thinking off, or a deterministic template when `STUB=1` is set or that call fails. Spike 2 measured about 2 s per report on Super, against 16–110 s on Lightning. Nemotron 3.5 Lightning (`nvidia/Nemotron-3_5-Lightning`) can filter data quality, scoring each row 1 to 5 and dropping rows under 3 (opt-in `quality_filter`; no template enables it yet). All calls go to `https://api.tokenfactory.nebius.com/v1` through one client that prices every call and refuses to send our key to any other host. On the golden run, Super wrote 300 grounded Q&A rows in 2.1 min for $0.0295, and Ultra judged 30 pairs in 85 s for $0.0802. Super also planned intents #2 and #3 live and wrote their reports (runs 84e57f84 and 59786797).
- **Nebius Token Factory fine-tuning (Lane A).** `tf-finetune` runs a LoRA fine-tune of a Llama model and keeps the checkpoint with the lowest validation loss. Token Factory does not fine-tune Nemotron, so Nemotron teaches and judges the Llama model instead; the real-estate template takes this lane. Spike 1 fine-tuned 50 rows on `meta-llama/Llama-3.1-8B-Instruct` live, in 6 min 45 s. Per-token LoRA deploy is retired (`POST /v0/models` answers 410), so `vllm-serve` serves the adapter beside its base on a Serverless Endpoint. Token Factory does not publish its price per trained token, so the client refuses to start a fine-tune until the rate is known.
- **Nebius AI Cloud Serverless Jobs (Lane B).** `unsloth-train` runs as a Job on an H100 with a 1-hour timeout. Unsloth trains a 16-bit LoRA on NVIDIA's student, `nvidia/Llama-3.1-Nemotron-Nano-8B-v1`, which a spike on a rented A100 outside Nebius chose: 60 steps took 62.5 s at a 15.9 GiB peak, and the merged model served from vLLM. The docs templates skip the 16 GB merged copy (`merge: false`). Nodes on a Job report to a public https control URL, so the golden run ran from the hosted API. Its Job took 11.2 min for $0.8408, about 6 of them pulling the image from a Nebius Container Registry in the same project, with no credentials. It ran 60 of 60 steps; the loss fell from 7.75 to 1.68, and the validation loss was 1.63.
- **Nebius AI Cloud Serverless Endpoints (Lane B).** `vllm-serve` creates one L40S endpoint that serves the base model and the adapter side by side with vLLM behind a bearer token, so Nemotron 3 Ultra judges the tuned student pairwise against its base. It registers an expiry (15 minutes in the docs template, 30 by default), at which the control plane deletes it; no live deletion is on record yet. On the golden run vLLM loaded the adapter next to the base model (`--enable-lora`), and the serve step took 9.3 min for $0.6276, its 15-minute keep-alive included.
- **Nebius Object Storage.** An S3-compatible bucket holds datasets, checkpoints and artifacts (MinIO locally). The hosted app's bucket is in eu-north1, beside the GPUs.
- **Tavily.** `web-research` calls Tavily Search and Extract and splits the pages into passages with their source URLs, metering credits per call. The passages ground the synthetic Q&A, so every grounded answer carries its source URL. On the golden run it read 20 Nebius docs pages in 3 s for $0.032 (4 credits).

Beyond the sponsor pieces:

- **Quantization on a CPU (intent #3).** `quantize` turns Qwen2.5-Math-1.5B-Instruct into a 0.99 GB GGUF q4_k_m with llama.cpp, keeping the 3.09 GB f16 GGUF as the baseline, and `judge-eval` serves both files locally with llama.cpp's server. Measured on an M1 Pro Mac, a busy host, with no key: both answered the template's 50 GSM8K test questions in 18 min 01 s in all, with exact match 0.78 for f16 and 0.84 for q4_k_m, a gap of 3 questions that is within noise at n = 50. An earlier run on the same Mac had exposed llama.cpp's fp16 CPU kernels garbling the f16 answers on Apple silicon; the evaluation image now drops those kernels, and the timed run used it. Live through the Agent (run 59786797, $0.0175 in all), Super's plan downloaded a 3.1 GB maths model and quantized it to q4_k_m (0.99 GB) in 75 s on CPU. Nemotron 3 Ultra judged q4_k_m against f16 on 5 questions: 1 win, 4 ties, 0 losses, consistency 1.0. Exact match was 0.8 against 0.6, a gap of one question. Five questions is a smoke-scale sample.
- **Guards for a public demo.** Per-visitor rate limits, an origin allow-list, deep health checks and a kill switch; visitors run at a tenth of the caps, cannot start a node that rents a GPU and cannot change a workflow that has runs; secret-looking inputs are dropped before anything is stored. The hosted demo runs at https://app.orchapod.dev on one Nebius VM in eu-west1, with Docker Compose and Caddy for HTTPS.

## Built with

Nebius Token Factory, Nebius AI Cloud, NVIDIA Nemotron, Tavily, vLLM, Unsloth, llama.cpp, Hugging Face, Python, FastAPI, SQLModel, PostgreSQL, Redis, MinIO, Docker, Caddy, TypeScript, Next.js, React, React Flow, Tailwind CSS, Playwright

## Track

Best Apps and Agents

## Links

- Demo, free to use and unrestricted until Dec 15, 2026: https://app.orchapod.dev (API: https://api.orchapod.dev). TODO(D8): check it logged out before submitting.
- Video, public on YouTube, under 3 minutes, no unlicensed music or third-party marks: TODO(D8) the URL.
- Repository, public with the MIT license: TODO(G3) https://github.com/bangadpurva/orchapod.ai goes public at the freeze; TODO(D8) then check it logged out. The default branch is main, which holds the code from before the hackathon, so link the NebiusHackathon branch or switch the default before submitting.
- Feedback: `docs/feedback.md`. TODO(D8): paste it into the Devpost field and link it on GitHub.

## What changed during the submission period

Orchapod predates the submission period (Aug 26 – Oct 30, 2026): its first commit is May 4, 2026 (367c605), and `git log --before=2026-08-26` lists everything that existed before. That includes the React Flow canvas and YAML workflow format, the FastAPI control plane and DAG executor, the node SDK, the data-prep, hf-download, unsloth-train, distill-sft, quantize, lm-eval and vllm-serve nodes, run pages with live logs, a Try-it chat with an endpoint countdown, and a Vast.ai GPU provider that is not on the demo path.

During the period (the dated list is `CHANGELOG.md`):

- Oct 2 to 8: the first Nebius × NVIDIA integration: a Token Factory service, a Nebius provider, the Nemotron 3 Super teacher node (`synth-distilabel`), Token Factory model ids verified against the live catalog, executor fixes (database commits, `NEBIUS_API_KEY` forwarding, the container SDK) that let a CPU workflow run end to end, and quick-start docs.
- Oct 20: the Orchapod Agent (one sentence in, a validated Nemotron plan with cost and time estimates out; runs monitored and reported; spend caps per run and per day); Tavily web research, grounded and structured synthetic data, and Token Factory fine-tune and deploy nodes (the deploy node was retired after spike 1); one Token Factory client and one Tavily client; a run engine with retry, cancel, restart recovery and cost roll-up; the Agent page and a run page with a live cost meter; the Lane B student chosen by experiment; repo clean-up, interface contracts v1 (`docs/contracts.md`), the Agent's knowledge base (`docs/agent_knowledge.md`) and a green `make check` in CI.
- Oct 21: the evaluation (Nemotron 3 Ultra judges base against tuned in both orders) and its eval view; intent #3's CPU quantization with an f16 baseline, plus a fix for llama.cpp garbling f16 answers on Apple silicon; the compare playground; four one-click templates with reduced "Run it yourself" versions; the data-prep quality filter; the Serverless Endpoint serving node and the GPU training container; public-demo hardening (rate limits, an origin allow-list, deep health checks, GPU nodes for the admin only, secret-looking inputs never stored); hosting files for one VM, not deployed yet; stub end-to-end tests of the three intents, a browser smoke test that runs a template card on stubs through to the eval view and the compare playground, and failure drills.
- TODO(D8): bring this list up to date with `CHANGELOG.md` at the freeze.
