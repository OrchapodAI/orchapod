# Orchapod.ai

> Describe the specialist model you want in one sentence. Orchapod plans the pipeline, runs it on Nebius with NVIDIA Nemotron, evaluates the result against its base model and shows what it cost.

[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An entry in the **Nebius × NVIDIA Global AI Hackathon**, track **Best Apps and Agents**. It runs on **Nebius Token Factory** and **Nebius AI Cloud**, calls **NVIDIA Nemotron** models at runtime and uses **Tavily** for web research.

- TODO(D8): links to the hosted demo, the 3-minute video and the Devpost entry, each checked logged out.
- TODO(D8): delete this note. On 2026-10-20 the build is at day 1: sections marked TODO(D8) wait for evidence from real runs (run ids, costs, win rates, screenshots) and claim nothing yet.

## What it is

Orchapod is an open-source platform for the whole post-training lifecycle of a language model: research, synthetic data, fine-tuning, deployment, evaluation and side-by-side comparison. It has two front doors:

- **The Orchapod Agent** (`/agent`). Type one sentence. Nemotron 3 Super drafts a pipeline from the node catalog, the server validates it against the model and cost rules, and a plan card shows the nodes, the models and the estimated dollars and minutes. Press Run and Orchapod executes the plan, streams logs and cost, evaluates the result and writes a report.
- **The canvas.** Drag nodes onto a React Flow canvas. The YAML workflow is the source of truth, and any plan the Agent writes opens on the canvas for editing.

Three intents define "done"; each must run from the chat box with no manual edits. TODO(D8): which intents have run end to end.

| Intent | What the Agent plans |
| --- | --- |
| "Create a fine-tuned Llama 3B over all the real estate compliance in USA." | web-research → synth-distilabel (grounded Q&A) → data-prep → tf-finetune (Llama 3.2 3B) → deploy → judge-eval (base vs tuned) → report |
| "Create synthetic data of movie likes, shares and subscribes." | synth-distilabel (structured rows) → data-prep (validate, dedupe, stats) → dataset with a download link. No training, and the plan says so |
| "Quantize a model which is an expert in maths." | hf-download → quantize (GGUF q4_k_m on CPU) → quick eval (50 GSM8K items by exact match, 20 judged by Nemotron Ultra) → artifact and report |

## Why

Every team wants a cheaper, faster, private specialist model. Today that takes an ML engineer and a pile of GPU plumbing. Orchapod turns it into a costed, capped and observable workflow.

- **A cascade of NVIDIA models.** Nemotron 3 Ultra judges, Nemotron 3 Super teaches and plans, Nemotron 3.5 Lightning does the cheap calls, and a small model serves. The Nemotron models share one OpenAI-compatible endpoint and one key.
- **It makes models, not only calls them.** Nemotron teaches and judges new specialist models, and every one is measured against its base.
- **An evaluation you can trust.** Base and tuned models get identical prompts and decoding. A Nemotron Ultra judge sees the question, the reference answer and the source passage, and scores the two answers in both orders; a win counts only if it holds in both. Fine-tuning moves style, format and vocabulary more than it injects facts, so answers are short and sourced. TODO(D8): no win rate has been measured yet; it and the judge's agreement between the two orders come from the golden run.
- **Cost is a first-class output.** Every billed call (tokens, Tavily credits, GPU hours) is metered per node, estimated before a run and capped during it.

## How it works

A typical run: research the topic, generate grounded synthetic data, prepare the splits, fine-tune and serve, judge the tuned model against its base, compare side by side. The fine-tune-and-serve step has two lanes, and a plan can take either without changing the rest:

- **Lane A** fine-tunes on Token Factory. TODO(D8): spike 1 decides serving — a per-token LoRA model (no GPU quota) or `vllm-serve` with the adapter (needs GPU quota).
- **Lane B** trains a Nemotron student on a Nebius Serverless Job and serves it from a Serverless Endpoint.

| Node | Runtime | What it does | Calls |
| --- | --- | --- | --- |
| `web-research` | cpu | queries or seed URLs → deduplicated passages with source URLs | Tavily Search and Extract |
| `synth-distilabel` | cpu | synthetic data: self-instruct, evol-instruct, magpie, grounded Q&A from passages, or rows that match a JSON Schema | Nemotron 3 Super |
| `data-prep` | cpu | validate, exact and near dedupe, optional quality filter, deterministic train / eval / test split | Nemotron 3.5 Lightning (filter) |
| `tf-finetune` | api | LoRA fine-tune, best checkpoint by validation loss, loss curve | Token Factory fine-tuning |
| `tf-deploy` | api | deploy the adapter as a per-token LoRA model if Token Factory accepts the base (TODO(D8): spike 1), then prove it with one completion | Token Factory |
| `unsloth-train` | gpu | 16-bit LoRA with Unsloth on a Nemotron student, resumable checkpoints | Nebius Serverless Job |
| `vllm-serve` | api | auto-expiring vLLM endpoint serving the base model and the adapter (TODO(D8): spike 4 confirms vLLM loads the adapter) | Nebius Serverless Endpoint |
| `judge-eval` | api | base vs tuned on held-out questions, reference-guided, both answer orders | Nemotron 3 Ultra |
| `hf-download` | cpu | Hugging Face model download with SHA-256 verification | Hugging Face Hub |
| `quantize` | cpu | GGUF q4_k_m, q5_k_m or q8_0 on CPU (AWQ needs a GPU job) | llama.cpp |

`cpu` and `api` nodes run as local containers (`api` nodes only call remote services); `gpu` nodes run as Nebius Serverless Jobs. `distill-sft` and `lm-eval` also exist but are off the demo path. TODO(D8): re-check this table against `NODE_REGISTRY` once the last node lands.

Under the hood:

- **Control plane** (`apps/api`): FastAPI and SQLModel on Postgres, Redis pub/sub feeding a WebSocket for live events, a DAG executor, the budget guard and the Agent (planner, validator, reporter).
- **One container per node** (`containers/<node>/`). The executor passes a node its inputs as JSON in `ORCHAPOD_NODE_INPUTS`; the node writes outputs through the SDK to S3-compatible storage at `r2://<bucket>/runs/<run_id>/<node_id>/<name>` and exits 0 or non-zero. The node contract is [docs/NODE_CONTRACT.md](docs/NODE_CONTRACT.md), and every interface is pinned in [docs/contracts.md](docs/contracts.md).
- **Metering.** The node SDK (`packages/sdk-py`) records each billed call and writes `cost_json` and `metrics_json` per node; the run page rolls them up.
- **Providers** (`packages/providers`): one retrying client per service (Token Factory, Tavily, Nebius Serverless) and a LocalDocker provider for CPU and API nodes. `STUB=1` replaces every external call with a deterministic stub.
- **Web** (`apps/web`): Next.js 15, React 19 and React Flow; the run page shows the node timeline, live logs, cost and artifacts.

## How we use Nemotron, Token Factory, Nebius AI Cloud and Tavily

### Nemotron on Nebius Token Factory

A run planned from a sentence starts with a Nemotron call (the plan), a run started from a template skips it, and a finished run ends with one (the report, which Nemotron 3.5 Lightning writes, or a deterministic template when `STUB=1` is set or that call fails); the nodes between them make their own. All calls go to `https://api.tokenfactory.nebius.com/v1` (OpenAI-compatible, key `NEBIUS_API_KEY`) through one client that retries, prices every call from a single table, refuses to send our key to any other host and honours `STUB=1`.

| Role | Model id | Where |
| --- | --- | --- |
| Planner | `nvidia/nemotron-3-super-120b-a12b` | Orchapod Agent: guided-JSON plan from the node catalog, up to two repair rounds |
| Teacher | `nvidia/nemotron-3-super-120b-a12b` | `synth-distilabel`: grounded Q&A, structured rows, self-instruct, evol-instruct, magpie |
| Judge | `nvidia/Nemotron-3-Ultra-550b-a55b` | `judge-eval`: base vs tuned, reference-guided, both answer orders |
| Quality filter | `nvidia/Nemotron-3_5-Lightning` | `data-prep`: optional, scores each row 1 to 5 and drops rows below 3 |
| Reporter | `nvidia/Nemotron-3_5-Lightning` | Orchapod Agent: writes the run report (what ran, metrics, cost against the estimate) |

No other model provider is called on this path. TODO(D8): confirm after the legacy Anthropic and OpenAI code paths are removed (wave 2).

### Token Factory fine-tuning (Lane A)

`tf-finetune` uploads the train and validation files, creates a LoRA job, polls it, keeps the checkpoint with the lowest validation loss and saves the adapter and the loss curve. `tf-deploy` deploys that checkpoint as a per-token LoRA model if Token Factory accepts the base (TODO(D8): spike 1), then sends one proving completion. Token Factory fine-tunes Llama, Qwen, gpt-oss, DeepSeek and Gemma models but not Nemotron, so Lane A tunes a Llama model (3.2 3B or 3.1 8B) that Nemotron teaches and judges.

TODO(D8): spike 1 decides the deploy path (per-token LoRA through `POST /v0/models`, or `vllm-serve` with the adapter on a Serverless Endpoint). State the answer and the exact base model id here.

### Nebius AI Cloud (Lane B)

- **Serverless Jobs.** `unsloth-train` runs as a Job on `gpu-h100-sxm` with a 1-hour timeout: a 16-bit LoRA on `nvidia/Llama-3.1-Nemotron-Nano-8B-v1` (TODO(D8): confirm the student after spike 4). Logs and artifacts flow back through the SDK, so `ORCHAPOD_CONTROL_URL` must be a public https URL.
- **Serverless Endpoints.** `vllm-serve` creates an Endpoint (`vllm/vllm-openai:v0.18.0-cu130`, default `gpu-l40s-a`, bearer-token auth) that serves the base model and the adapter side by side (TODO(D8): spike 4 confirms vLLM loads the adapter). It registers an expiry (30 minutes by default) and the control plane deletes the endpoint then; an endpoint never exists without one.
- **Object Storage.** Datasets, checkpoints and artifacts live in an S3-compatible bucket: `https://storage.eu-north1.nebius.cloud` on Nebius, MinIO locally. The `ORCHAPOD_R2_*` variables and the `r2://` scheme keep their historical names.
- TODO(D8): GPU quota, the Job and Endpoint ids of the golden run, console screenshots.

### Tavily

`web-research` calls Tavily Search (advanced depth, with raw content) and Extract, splits the pages into passages of 200 to 2,000 characters with their source URLs, and meters credits at $0.008 each. The passages ground the synthetic Q&A, so every grounded answer carries its source URL. TODO(D8): credits used by the golden run.

## Setup

You need Docker with the compose plugin, Python 3.12, Node 22 with pnpm, a [Nebius Token Factory](https://tokenfactory.nebius.com) API key and a [Tavily](https://tavily.com) API key (free tier: 1,000 credits a month).

```bash
git clone -b NebiusHackathon https://github.com/bangadpurva/orchapod.ai.git
cd orchapod.ai
cp .env.example .env            # set NEBIUS_API_KEY and TAVILY_API_KEY; the rest is preset for the local stack
make up                         # Postgres, Redis and MinIO

python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt -r apps/api/requirements.txt
make check                      # ruff + unit tests + web tests; no keys, no spend
```

On pnpm 9, run `make check PNPM=pnpm`. `make check E2E=1` adds `scripts/e2e_demo.py --stub`, an end-to-end run of the synthetic-data intent through the API (its own API with `STUB=1`, a throwaway database and no key: $0); it needs Docker and `make up`, rebuilds and retags the local `orchapod/<node>:dev` images, and is meant for the integration branch, not for every edit. Its recorded run (`hackathon/LOG.md`, 2026-10-21T01:49Z): on NebiusHackathon @ 1c0b746, run 9214965e succeeded in 4 s at $0, and the dataset's download link served 500 rows.

Then create the artifact bucket once and start the API and the web app (two terminals):

```bash
python - <<'PY'
import boto3
boto3.client("s3", endpoint_url="http://localhost:9000", region_name="us-east-1",
             aws_access_key_id="orchapod", aws_secret_access_key="orchapod_dev").create_bucket(Bucket="orchapod-artifacts")
PY

# terminal 1: the API on :8001 (docs at http://localhost:8001/docs)
set -a; . ./.env; set +a
PYTHONPATH=apps:packages/sdk-py uvicorn api.main:app --port 8001

# terminal 2: the web app on :3000
cd apps/web && pnpm install
NEXT_PUBLIC_API_URL=http://localhost:8001 NEXT_PUBLIC_WS_URL=ws://localhost:8001 pnpm dev
```

Open http://localhost:3000. `make down` stops Postgres, Redis and MinIO. `pnpm test` (in apps/web) runs the web unit tests.

**Node images.** A node runs from `orchapod/<node>:dev` when that image exists locally; otherwise Docker pulls `ghcr.io/bangadpurva/<node>:latest`, which CI publishes (forks set `ORCHAPOD_IMAGE_PREFIX`). Build one yourself with the repo root as context, for example `docker build -t orchapod/data-prep:dev -f containers/data-prep/Dockerfile .`. TODO(D8): verify a logged-out `docker pull` of every image; the GHCR packages must be public.

**GPU nodes (Lane B)** also need a Nebius AI Cloud project with billing and GPU quota; `.env.example` lists the Nebius variables to set and where to get each one.

## Run the demo

- **Hosted.** TODO(D8): the URL of the hosted app, which is to ship a real, pre-completed golden run (artifacts, logs, verdicts) and a guarded "Run it yourself" button that launches the pipeline at reduced scale under a per-run spend cap. Neither the app nor the golden run exists yet.
- **Locally, from the Agent.** Open http://localhost:3000/agent and paste one of the three intents above, or press Run on one of the template cards (`GET /agent/templates`) to start its ready-made plan in one click. Read the plan card: nodes, models, estimated cost and minutes, warnings. Run stays disabled while the plan has errors, and Edit opens the plan on the canvas. Press Run to follow the live run view (node timeline, logs, cost meter). A run that succeeds opens its result: the eval view (win rate, wins, ties and losses, consistency, exact match, and every judged sample with the judge's reasoning in both answer orders), the dataset card (download link and per-field stats), and a compare tab that streams one prompt to the run's base and tuned models side by side through `POST /compare`, with the keys kept on the server. When the run ends, the report card shows what ran, the metrics, the cost against the estimate and how to use the result.
- **Run page.** `/runs/{id}` (also embedded on `/agent`) shows per-node status, cost and errors from `GET /runs/{id}/summary`, updates the cost meter live, shows a failed node's error verbatim and offers **Retry node** while the run is failed or cancelled.
- **Headless.** `make agent-e2e INTENT="Create synthetic data of movie likes, shares and subscribes."` runs one intent through the Agent, capped at $3. `make e2e` runs the real golden pipeline under the same cap, and `make demo` seeds the golden run for the hosted app. TODO(D8): `scripts/e2e_demo.py` has only `--stub` so far, so `make e2e` fails until its real run is written, and the scripts behind `make agent-e2e` and `make demo` are still being written.
- **Without keys.** Start the API with `STUB=1` to run the same flow on deterministic stubs: no network beyond your local stack, and $0. `make check E2E=1` does this for the synthetic-data intent and checks the dataset it downloads (see Setup).

### Results

TODO(D8): golden run id, wall time and cost; base-vs-tuned win rate and judge agreement over N held-out questions; one judged example; screenshots of the plan card, run view, eval view and playground (the full list is in `docs/video-script.md`); the video link.

## Costs and caps

| Cap | Default | Setting |
| --- | --- | --- |
| Per run | $3 | `ORCHAPOD_MAX_RUN_USD` |
| Per UTC day | $15 | `ORCHAPOD_MAX_DAY_USD` |
| Serverless Job timeout | 1 hour | fixed |
| Node backstop timeout | 5,400 s | `ORCHAPOD_NODE_TIMEOUT_S` |
| Endpoint keep-alive | 30 min, at most 120 | `keep_alive_min` on `vllm-serve` |
| Kill switch | off | `ORCHAPOD_KILL_SWITCH=1` |
| Anonymous visitors | caps × 0.1 | `ORCHAPOD_ANON_SCALE` |

The guard checks the estimate when a plan is validated (an estimate above the remaining budget is a plan error), at start and retry (HTTP 402), at every node boundary, and inside each node, where `ORCHAPOD_MAX_COST_USD` aborts the node once spend passes it. A model with no price in the table fails before the request is sent. TODO(D8): no real run has hit a cap yet; record one.

| Item | Price (2026-10-20) |
| --- | --- |
| Nemotron 3 Super, per 1M tokens in / out | $0.30 / $0.90 |
| Nemotron 3 Ultra, per 1M tokens in / out | $1.00 / $3.00 |
| Nemotron 3.5 Lightning, per 1M tokens in / out | $0.06 / $0.24 |
| Tavily, per credit | $0.008 |
| `gpu-h100-sxm`, per hour | $4.50 |
| `gpu-l40s-a`, per hour | $1.82 |

These are design budgets, not measurements: a Lane A run under $2 and a Lane B run of about $2.8 (at most 25 minutes of H100 plus 30 minutes of L40S). TODO(D8): measured time and cost per run, the Token Factory fine-tuning price per trained token (from spike 1), and the `gpu-l40s-a` rate, which needs re-checking against nebius.com/prices (the table uses $1.82).

## What changed during the submission period

The submission period is Aug 26 – Oct 30, 2026. Orchapod predates it: its git history starts in May 2026, and everything that existed before the period is what `git log --before=2026-08-26` shows. That includes the React Flow canvas and YAML workflow format, the FastAPI control plane and DAG executor, the node SDK, the data-prep, hf-download, unsloth-train, distill-sft, quantize, lm-eval and vllm-serve nodes, run pages with live logs, Try-it chat and an endpoint countdown, and a Vast.ai GPU provider that is not on the demo path.

During the period (the dated list is [CHANGELOG.md](CHANGELOG.md)):

- Oct 2–8: first Nebius × NVIDIA integration: a Token Factory service, a Nebius provider, the Nemotron 3 Super teacher node (`synth-distilabel`), Token Factory model ids verified against the live catalog, and the executor fixes that let a CPU workflow run end to end.
- Oct 20: repo clean-up; `make up` and `make check` (TODO(D8): `make e2e`, `make agent-e2e` and `make demo` are in the Makefile; `scripts/e2e_demo.py` has only `--stub` so far, and the other scripts are still being written); a green `make check` with CI running lint and unit tests on every push; interface contracts v1 ([docs/contracts.md](docs/contracts.md)) and the Agent's knowledge base ([docs/agent_knowledge.md](docs/agent_knowledge.md)).
- TODO(D8): replace this list with the final CHANGELOG entries (Tavily research, grounded and structured synthetic data, Token Factory fine-tuning and deploy, Nebius Serverless, judge-eval, the Agent, the budget guard).

## License

[MIT](LICENSE). Open source, free to use and self-host.
