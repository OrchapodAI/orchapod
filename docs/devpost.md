# Devpost entry: Orchapod.ai

Copy each section into the matching Devpost field; clear every TODO(D8) before submitting.

## Title

Orchapod.ai

## Tagline

Describe the specialist model you want in one sentence. Orchapod plans the pipeline, runs it on Nebius with NVIDIA Nemotron, evaluates the result against its base model and shows what it cost.

## Description

### What it does

Orchapod is an open-source platform for the whole post-training lifecycle of a language model: research, synthetic data, fine-tuning, deployment, evaluation and side-by-side comparison. It has two front doors:

- **The Orchapod Agent.** Type one sentence. Nemotron 3 Super drafts a pipeline from the node catalog, the server validates it against the model and cost rules, and a plan card shows the nodes, the models and the estimated dollars and minutes. Press Run and Orchapod executes the plan, streams logs and cost, evaluates the result and writes a report.
- **The canvas.** Drag nodes onto a React Flow canvas. The YAML workflow is the source of truth, and any plan the Agent writes opens on the canvas for editing.

Three intents define "done", and each must run from the chat box with no manual edits: a Llama 3B fine-tuned on US real-estate compliance, synthetic data of movie likes, shares and subscribes, and a quantized maths model. TODO(D8): which of the three have run end to end, with run ids and costs.

### Why

Every team wants a cheaper, faster, private specialist model, and today that takes an ML engineer and a pile of GPU plumbing. Orchapod turns it into a costed, capped and observable workflow.

- **It makes models, not only calls them.** Nemotron teaches and judges new specialist models, and every one is measured against its base.
- **An evaluation you can trust.** Base and tuned models get identical prompts and decoding. A Nemotron 3 Ultra judge sees the question, the reference answer and the source passage, and scores the two answers in both orders; a win counts only if it holds in both. TODO(D8): `judge-eval` is not built yet; the win rate and the judge's agreement between the two orders come from the golden run.
- **Cost is a first-class output.** Every billed call (tokens, Tavily credits, GPU hours) is metered per node, estimated before a run and capped during it.

### How we built it

A typical run: research the topic, generate grounded synthetic data, prepare the splits, fine-tune and serve, judge the tuned model against its base, compare side by side. Every step is a node: a Docker container that reads its inputs as JSON and writes artifacts, logs and a cost record through one SDK. A FastAPI control plane with a DAG executor runs the nodes, and a Next.js app shows the run live: node timeline, logs, cost and artifacts. The fine-tune-and-serve step has two lanes, and a plan can take either without changing the rest. Where each sponsor piece is used:

- **NVIDIA Nemotron on Nebius Token Factory.** A run planned from a sentence starts with a Nemotron call (the plan), a run started from a template skips it, and every run ends with one (the report). Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`) plans the pipeline and teaches, writing the synthetic data. Nemotron 3 Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`) judges base against tuned. Nemotron 3.5 Lightning (`nvidia/Nemotron-3_5-Lightning`) filters data quality and writes the run report. All calls go to `https://api.tokenfactory.nebius.com/v1` through one client that prices every call and refuses to send our key to any other host. TODO(D8): no live call has been made yet (the key is not set); replace this with the golden run's calls and cost.
- **Nebius Token Factory fine-tuning (Lane A).** `tf-finetune` runs a LoRA fine-tune of a Llama model and keeps the checkpoint with the lowest validation loss. Token Factory does not fine-tune Nemotron, so Nemotron teaches and judges the Llama model instead. TODO(D8): spike 1 decides how it is served, as a per-token LoRA model on Token Factory or with `vllm-serve` and the adapter.
- **Nebius AI Cloud Serverless Jobs (Lane B).** `unsloth-train` runs as a Job with a 1-hour timeout and trains a 16-bit LoRA on a Nemotron student, `nvidia/Llama-3.1-Nemotron-Nano-8B-v1`. TODO(D8): GPU quota, and the first Job on Nebius.
- **Nebius AI Cloud Serverless Endpoints (Lane B).** `vllm-serve` creates an endpoint that serves the tuned model with vLLM behind a bearer token. It registers an expiry (30 minutes by default) and the control plane deletes the endpoint then, so an endpoint never exists without an expiry. TODO(D8): the first endpoint on Nebius, and whether vLLM loads the adapter next to the base model.
- **Nebius Object Storage.** An S3-compatible bucket holds datasets, checkpoints and artifacts (MinIO locally). TODO(D8): so far only MinIO has been used; the first run against Nebius Object Storage.
- **Tavily.** `web-research` calls Tavily Search and Extract and splits the pages into passages with their source URLs, metering credits per call. The passages ground the synthetic Q&A, so every grounded answer carries its source URL. TODO(D8): credits used by the golden run.

## Built with

Nebius Token Factory, Nebius AI Cloud, NVIDIA Nemotron, Tavily, vLLM, Unsloth, llama.cpp, Hugging Face, Python, FastAPI, SQLModel, PostgreSQL, Redis, MinIO, Docker, TypeScript, Next.js, React, React Flow, Tailwind CSS

## Track

Best Apps and Agents

## Links

- Demo, free to use and unrestricted until Dec 15, 2026: TODO(D8) the hosted URL, checked logged out.
- Video, public on YouTube, under 3 minutes, no unlicensed music or third-party marks: TODO(D8) the URL.
- Repository, public with the MIT license: TODO(D8) https://github.com/bangadpurva/orchapod.ai, checked logged out once it is public at the freeze (G3). The default branch is main, which holds the code from before the hackathon, so link the NebiusHackathon branch or switch the default before submitting.
- Feedback: `docs/feedback.md`. TODO(D8): paste it into the Devpost field and link it on GitHub.

## What changed during the submission period

Orchapod predates the submission period (Aug 26 – Oct 30, 2026): its first commit is May 4, 2026 (367c605), and `git log --before=2026-08-26` lists everything that existed before. That includes the React Flow canvas and YAML workflow format, the FastAPI control plane and DAG executor, the node SDK, the data-prep, hf-download, unsloth-train, distill-sft, quantize, lm-eval and vllm-serve nodes, run pages with live logs, a Try-it chat with an endpoint countdown, and a Vast.ai GPU provider that is not on the demo path.

During the period (the dated list is `CHANGELOG.md`):

- Oct 2 to 8: the first Nebius × NVIDIA integration: a Token Factory service, a Nebius provider, the Nemotron 3 Super teacher node (`synth-distilabel`), Token Factory model ids verified against the live catalog, executor fixes (database commits, `NEBIUS_API_KEY` forwarding, the container SDK) that let a CPU workflow run end to end, and quick-start docs.
- Oct 20: repo clean-up (a committed SQLite database, compiled Python files and a stray worktree copy removed; one workflow-schema package instead of two); a green `make check`, with CI running lint and the unit tests on every push; interface contracts v1 (`docs/contracts.md`) and the Agent's knowledge base (`docs/agent_knowledge.md`).
- TODO(D8): replace this list with the final CHANGELOG entries (Tavily research, grounded and structured synthetic data, Token Factory fine-tuning and deploy, Nebius Serverless, judge-eval, the Agent, the budget guard).
