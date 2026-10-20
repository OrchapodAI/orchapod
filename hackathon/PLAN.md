# Orchapod × Nebius AI Hackathon Plan

Oct 20, 2026 · @Hari

## Hackathon brief

Submissions close **Friday, October 30, 2026 at 10:00 AM PDT (1:00 PM EDT)** — 10 days from today. Judging runs Dec 1–15 and winners are announced around Jan 11, 2027, so the hosted demo must stay testable for seven weeks after submission ([rules](https://nebiusglobalaihackathon.devpost.com/rules), [schedule](https://nebiusglobalaihackathon.devpost.com/details/dates)).

**Stage one is pass/fail.** A project is only scored if it runs on Nebius Token Factory or Nebius AI Cloud and uses at least one NVIDIA open model. A runtime call to a Nemotron model on Token Factory satisfies this; the web frontend can be hosted anywhere; calling Nemotron through Hugging Face or OpenRouter does not count ([FAQ](https://nebiusglobalaihackathon.devpost.com/details/faqs)).

**Stage two scores four equally weighted criteria**, with ties broken in this order:

1. Technological Implementation — how well it is built and how it uses Token Factory / AI Cloud and Nemotron.
2. Design — a complete product experience, not a proof of concept.
3. Potential Impact — a real problem for a real audience.
4. Quality of the Idea — creative, non-obvious use of Nebius and NVIDIA technology.

**What the submission must contain** ([rules](https://nebiusglobalaihackathon.devpost.com/rules)):

| Item | Requirement |
| --- | --- |
| Track | One of four; we target **Best Apps and Agents** ("apps or agents people would use, ideally powered by Nemotron"; Nemotron 3 Ultra for heavy reasoning, Nano/Super for fast calls; Serverless Endpoints and Jobs encouraged but optional) |
| Demo | A working demo URL, hosted app, or test build, free to use and unrestricted until Dec 15 |
| Description | Text explaining what it does, why, and how it works |
| Repository | Public GitHub/GitLab/Bitbucket with an OSS license file (MIT/Apache-2.0) and a README with setup steps that highlights how Nemotron, Token Factory, and other Nebius services are used |
| Video | Public YouTube, under 3 minutes, no unlicensed music or third-party marks |
| Feedback | Written feedback on Token Factory, AI Cloud, and the NVIDIA models used (also a $100 + swag bonus award for 10 entrants) |
| Pre-existing project | A written explanation of what was significantly updated during the submission period (Aug 26 – Oct 30) — Orchapod predates it, so this is mandatory |
| Language | English |

**Prizes** ([overview](https://nebiusglobalaihackathon.devpost.com/)): Grand $20,000 · 2nd $10,000 · 3rd $6,000 · each track winner an NVIDIA Jetson Orin Nano · Best Use of Tavily $3,000 (requires a functional runtime call to the Tavily API) · Most Valuable Feedback $100 + swag (10). A project can win one overall or track award plus one bonus award. The $500 City Winner awards required attending a Builders & Brews event; the last one (LA) was Oct 13, so that bonus is off the table. Team size is unlimited; 24,979 participants are registered.

**Credits available now** ([resources](https://nebiusglobalaihackathon.devpost.com/resources), [Builders Program](https://dev.nebius.com/builders)): $25 Token Factory credit via the promo form with code `NEBIUS-DEVPOST-GLOBAL26`, another $25 Token Factory credit plus $25 Tavily credit by joining the Nebius Builders Program. No AI Cloud (GPU) credit is published — GPU time is out of pocket and needs an AI Cloud project with billing and GPU quota, which we do not have yet.

**Sponsor stack facts that shape the build** (verified today):

| Capability | What we verified | Why it matters |
| --- | --- | --- |
| Token Factory inference | OpenAI-compatible at `https://api.tokenfactory.nebius.com/v1`. Nemotron models: `nvidia/nemotron-3-super-120b-a12b` ($0.30/$0.90 per 1M in/out), `nvidia/Nemotron-3-Ultra-550b-a55b` ($1/$3), `nvidia/Nemotron-3_5-Lightning` ($0.06/$0.24), `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` ([Nebius](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference), [cookbook](https://github.com/nebius/token-factory-cookbook)) | Teacher (Super), judge (Ultra), and fast calls (Lightning/Nano) all on one key we already have |
| Token Factory fine-tuning | `files.create` → `fine_tuning.jobs.create(... lora: True)` → checkpoints → `POST /v0/models` deploys a **serverless LoRA adapter billed per token**. Serverless LoRA deploy is supported for `meta-llama/Llama-3.1-8B-Instruct` and `meta-llama/Llama-3.3-70B-Instruct`; Nemotron models are **not** fine-tunable on Token Factory ([models](https://docs.tokenfactory.nebius.com/post-training/models), [deploy](https://docs.tokenfactory.nebius.com/fine-tuning/deploy-custom-model)) | Gives a fully serverless train → deploy path that needs no GPU quota: our fallback lane and the always-on judge demo |
| Nebius Serverless AI Jobs | `POST https://api.nebius.cloud/ai/v1/jobs` (or `nebius ai job create`) with a container image, `platform` `gpu-h100-sxm` / `gpu-l40s-d`, `preset`, `--env-secret`, `--volume s3://bucket:/path:rw`, 1h–168h timeout; logs only via CLI/console ([quickstart](https://docs.nebius.com/serverless/quickstart/jobs), [reference](https://docs.nebius.com/cli/reference/ai/job/create)) | Replaces hand-rolled H100 VM provisioning for the Nemotron training node |
| Nebius Serverless AI Endpoints | `nebius ai endpoint create --image vllm/vllm-openai:v0.18.0-cu130 --public --container-port 8000 --auth token`; about 5 minutes to `Running`; OpenAI-compatible URL ([tutorial](https://docs.nebius.com/serverless/tutorials/deploy-model)) | Serves the fine-tuned Nemotron student as a live endpoint |
| Unsloth + Nemotron 3 Nano | 16-bit LoRA of Nemotron 3 Nano 30B-A3B needs about 60 GB VRAM (1×H100); router layer stays frozen; keep ≥75% reasoning examples ([Unsloth](https://unsloth.ai/docs/models/nemotron-3)) | The student model for the headline lane fits one GPU |
| Tavily | Search + Extract API; free plan 1,000 credits/month plus the $25 Builders credit | One research node makes us eligible for the $3,000 bonus |

## Where orchapod.ai stands today

The `NebiusHackathon` branch is the superset to build on: it contains everything on `main` (the May codebase) plus five hackathon commits from Oct 2–8 by Purva, and it already runs a real Nemotron synthetic-data node through Token Factory. What it does not have is any working GPU path: the Nebius provider targets a legacy Compute API and has never provisioned a machine, so training, serving, and evaluation have never run end to end. The repo was created on May 7, 2026, so the pre-existing-project rule applies.

| Component | State | Evidence in the branch | What the plan does with it |
| --- | --- | --- | --- |
| Control plane and executor (`apps/api`) | Works | FastAPI + SQLModel + Alembic; sequential DAG executor (`executor/run_workflow.py`) that provisions a container per node, streams logs over WebSocket, resolves `${{ nodes.x.outputs.y }}` refs; cost-estimate modal and `run_cost` events; cancel; `/internal/log`, `/internal/artifact`, `/internal/progress`, `/internal/ttl` webhooks | Keep. Add long-polling node support, retry-node, budget guard, a public control URL so containers on Nebius can call the webhooks |
| Node SDK (`packages/sdk-py`) | Works | `io.read_inputs / write_output / download_input` over an S3-compatible bucket (`r2://orchapod-artifacts/runs/{run}/{node}/{name}`), `log.*` posts every line to the control plane, `checkpoint.*` | Keep as the contract for every new node; add `cost.json` and `metrics.json` conventions |
| Local Docker provider | Works | `providers/local_docker.py` runs CPU nodes from locally built `orchapod/<node>:dev` images; verified by the Oct 8 run (10 rows, 55 s, $0.0039) | Keep for all Lane A nodes |
| Synth Data node (`containers/synth-distilabel`) | Works, ungrounded | Self-instruct, evol-instruct, magpie against `nvidia/nemotron-3-super-120b-a12b`; token and dollar accounting; stub mode | Add the grounded mode (passage → Q&A); fix the stale price table ($0.18/$0.60 should be $0.30/$0.90) |
| Data Prep, HF Download | Work (CPU) | ChatML conversion, train/eval split, stats; HF model download with SHA256 | Add near-dedupe, quality filter, test split |
| Unsloth Train (`containers/unsloth-train`) | New API node; the existing vllm-serve container (Cloudflare tunnel) becomes the fallback | 4-bit QLoRA via Unsloth + TRL, checkpoint upload, merged 16-bit export; default model still `Qwen/Qwen3-4B-Instruct`, README says Nemotron Mini 4B | Lane B: run as a Serverless Job, switch to 16-bit LoRA for the chosen Nemotron student, read and write the mounted bucket |
| vLLM Serve (`containers/vllm-serve`) | Written, never run | Starts vLLM, opens a Cloudflare quick tunnel for a public URL, registers a TTL | Lane B: replace with a node that creates a Serverless Endpoint (managed HTTPS URL and bearer token already provided); keep the container only as a fallback |
| LM-Eval (`containers/lm-eval`) | Written, never run; GPU-heavy | Runs lm-evaluation-harness (hellaswag, mmlu\_stem, gsm8k) by spinning up vLLM per model, then an absolute 1–5 Nemotron Ultra judge on 100 prompts | Keep as optional. The demo needs a new CPU judge node: pairwise, reference-guided, base vs tuned over the API |
| Nebius provider (`providers/nebius.py`) | Does not work | Calls `compute.api.eu-north1.nebius.cloud/compute/v1/instances` with `folderId`/`zoneId` (legacy API shape), reads logs from a guessed serial-port endpoint, and `wait()` only returns when the VM stops, which the startup script never does | Replace with a Serverless Jobs + Endpoints client against `api.nebius.cloud/ai/v1` |
| Token Factory service (`services/nebius_token_factory.py`) | Works | chat, streaming chat, a `judge_response` helper; model IDs verified Oct 8 and still live today; base URL is the legacy `api.studio.nebius.ai/v1` | Move to `api.tokenfactory.nebius.com/v1`; add files, fine-tuning jobs, checkpoints, and `/v0/models` LoRA deploy |
| Prompt-to-workflow builder (`agent/workflow_builder.py`, `/workflows/from-prompt`, the "AI prompt" tab on New Workflow) | Works, on Claude | Anthropic tool-use loop with `list_node_types` and `validate_workflow`; system prompt still names Qwen defaults and six old node types | Re-point to Nemotron 3 Super on Token Factory with JSON-schema output; this is the Copilot, mostly already built |
| Frontend (`apps/web`) | Works | React Flow canvas with YAML sync, palette of 12 node types, run page with node timeline, live logs, loss chart, artifacts, endpoint countdown, Try-it chat; models, endpoints, artifacts, registry pages; Nemotron quick-pick chips on Inference | Keep. Hide the four palette nodes that have no container (hf-import, file-upload, s3-import, auto-label-cleanlab); add templates, eval view, compare playground |
| Tests and CI | Partial | 9 test modules (API, containers, providers, schema); CI runs pytest, type-checks and builds the web app, builds 7 container images to GHCR (synth-distilabel is missing from the matrix) | Extend; make CI the merge gate |
| Docs | Partial | `docs/NODE_CONTRACT.md`, `docs/WORKFLOW_SPEC.md` (still describes the YC-era 7 nodes and Vast.ai), README with hackathon framing | Rewrite README; keep the node contract |

**Mismatches to fix on day 1** (each is a 15-minute item, and several would fail the stage-one review if a judge tried to run the repo):

- Executor pulls `ghcr.io/orchapod/<node>:latest`, CI pushes `ghcr.io/bangadpurva/<node>`, and the local provider looks for `orchapod/<node>:dev`. One `ORCHAPOD_IMAGE_PREFIX` setting, and public GHCR packages so Serverless Jobs can pull them.
- Legacy Token Factory URL in four files (provider, service, synth node, lm-eval); README still sends users to `studio.nebius.ai` for keys.
- README inconsistencies: clone URL points at `bangadpurva/orchapod` (no `.ai`), model names drift between "Super 49B", "Super 120B", "Ultra 253B" and the real IDs; `docker-compose.dev.yml` defaults the judge to `nvidia/Llama-3.1-Nemotron-Ultra-253B-v1`.
- Two copies of the workflow schema (`packages/workflow-schema/models.py` and `packages/workflow_schema/models.py`) that have drifted; keep the importable one.
- Committed junk: `apps/api/orchapod_dev.db`, `__pycache__/*.pyc`, a stray `.claire/worktrees/` directory, `Jira.csv` at the root (move to `docs/`).
- `.env` is git-ignored and no key patterns appear in the current tree, but run a history scan before the repo goes public.

**Branching:** build on `NebiusHackathon`, not on a fresh folder. Create the integration branch from it and the agent worktrees from that; `main` stays untouched, which satisfies the "don't touch the old work" constraint while keeping the 140-file codebase of working control plane, SDK, nodes, and UI that a rewrite would have to recreate.

## Winning strategy

Position Orchapod as **the open-source visual post-training factory for Nemotron**: drag a pipeline from raw web docs to a deployed, evaluated specialist model, with Nemotron 3 Ultra and Super doing the expensive thinking (teacher, judge) and a small model doing the cheap serving. Most of the 25,000 entrants will ship chatbots and agents that *call* Nemotron; almost none will ship a product that *produces* new Nemotron-powered models on Nebius. That contrast is the pitch, and it maps cleanly onto all four criteria.

| Criterion | What judges will look for | What we show | What we must avoid |
| --- | --- | --- | --- |
| Technological Implementation | Real, non-trivial use of Token Factory / AI Cloud and Nemotron | One pipeline that touches five Nebius surfaces: Token Factory inference (3 Nemotron tiers in distinct roles), Token Factory fine-tuning + serverless LoRA deploy, AI Cloud Serverless Jobs (training) and Endpoints (vLLM serving), Object Storage for artifacts. Per-node token and dollar accounting, live logs from remote jobs, resumable DAG | Stubbed nodes, mocked runs, or a "coming soon" GPU path in the video |
| Design | A complete product, not a proof of concept | A template gallery ("Distill a docs specialist"), one-click golden run, run page with live logs and cost, an eval view with base-vs-tuned win rate and sample judgments, a side-by-side playground. Judges reach a result in under 3 minutes without reading docs | Empty states, dead buttons, a raw JSON wall, anything that needs a terminal |
| Potential Impact | A real problem for a real audience, stated with numbers | "Every team wants a cheaper, faster, private specialist model; today that takes an ML engineer and GPU plumbing. Orchapod makes it a 20-minute, under-$5 workflow." Audience: app developers and small teams; the story matches Nebius's open-model economics and NVIDIA's own Nemotron-as-teacher-and-judge framing | Vague "MLOps platform" language; claims we cannot back with a run |
| Quality of the Idea | Creative, non-obvious use of the sponsor stack | The Nemotron cascade (Ultra judges, Super teaches, Nano/Lightning executes); Token Factory's fine-tune and LoRA APIs used as drag-and-drop primitives; a Nemotron Copilot that writes the pipeline from one sentence | Looking like a generic workflow builder with an LLM node bolted on |

**Three deliberate bets**

1. **Two lanes, one story.** Lane A (all Token Factory, no GPU quota needed) is P0 and becomes the always-on judge demo. Lane B (Nemotron 3 Nano fine-tuned on an AI Cloud Serverless Job and served from a Serverless Endpoint) is the headline if GPU quota lands by Oct 25; if it does not, Lane A alone is still a complete, scorable product. We never block the demo on a quota request we don't control.
2. **Depth over breadth.** Seven nodes that work flawlessly beat twenty that mostly work. Every node in the demo must run for real, log live, report cost, and recover from one failure.
3. **Collect the bonuses that cost a day or less.** A Tavily research node qualifies us for Best Use of Tavily ($3,000; Tavily staff are on the judging panel). Honest, specific Token Factory feedback (we will have plenty from wiring the fine-tuning and Serverless APIs) targets the $100 + swag award and earns goodwill with the Nebius judges.

**Track:** Best Apps and Agents, as you chose. It is the safest fit for the stage-one check and the Copilot feature makes the "agents" half literal. Coding and Agentic Engineering would require reframing Orchapod as a tool that writes and tests code, which it is not; the overall cash awards are cross-track anyway.

**Pre-existing project rule:** Orchapod predates Aug 26, so the submission must explain what changed during the period. The repo's first commit is May 7, 2026; the hackathon branch (five commits, Oct 2–8) already adds the Nemotron synth node, the Token Factory service, and a Nebius provider; this plan adds the fine-tune, deploy, eval, Tavily, Serverless, and Copilot work, which is more than enough. Keep a dated CHANGELOG from day one so the write-up is a copy-paste.

## The target end-to-end demo

The demo is one template run, **"Distill a docs specialist"**: seed URLs go in, and about 20 minutes and under $5 later a fine-tuned small model is deployed, judged against its base model by Nemotron 3 Ultra, and chattable side by side. The video shows it live; the hosted app ships with that run pre-completed (real artifacts, logs, and verdicts) plus a guarded "Run it yourself" button.

The default seed is the Nebius AI Cloud and Token Factory documentation. Judges are Nebius, NVIDIA, and Tavily staff, so they can verify answers, and the base model's ignorance of Nebius specifics makes the before/after visible. The template accepts any seed URLs, so the product stays general. Fine-tuning moves style, format, and domain vocabulary far more than it injects facts, so the judge grades **reference-guided** (the source passage is given to the judge) and the dataset keeps answers short and sourced; that is what makes the win rate honest and the demo convincing.

```
1 Web Research (Tavily)  →  2 Synth Data (Nemotron 3 Super, Token Factory)  →  3 Data Prep
        │
        ├── Lane A (Token Factory only, P0): 4a Fine-tune (TF LoRA, Llama-3.1-8B-Instruct) → 5a Deploy adapter (TF serverless LoRA, per token)
        └── Lane B (AI Cloud GPU, P1):      4b Train (Serverless Job, H100, Unsloth)        → 5b Serve (Serverless Endpoint, vLLM)
        │
6 Evaluate (Nemotron 3 Ultra judge, pairwise, reference-guided → win rate)  →  7 Playground (base vs tuned, side by side)
```

Nodes 1–3 and 6–7 are shared; only the training and serving pair differs by lane, so a run can take either lane without touching the rest of the graph.

| # | Node | Runs on | In → Out | State in the branch | Lane |
| --- | --- | --- | --- | --- | --- |
| 1 | Web Research (Tavily) | Tavily Search + Extract | seed URLs or query → `corpus.jsonl` of passages with source URLs | New | A + B |
| 2 | Synth Data (Nemotron 3 Super 120B) | Token Factory | corpus → grounded Q&A pairs in OpenAI `messages` JSONL, with token and dollar cost | Works today (magpie + evol-instruct, ungrounded); add a grounded mode | A + B |
| 3 | Data Prep | Local CPU container | dedupe, optional Nemotron 3.5 Lightning quality filter, train/val/test split | Exists; harden and add the test split | A + B |
| 4a | Fine-tune (Token Factory LoRA) | Token Factory fine-tuning API on `meta-llama/Llama-3.1-8B-Instruct` | train + val files → job, checkpoints, loss curve | New | A |
| 5a | Deploy adapter (Token Factory serverless LoRA) | `POST /v0/models` | best checkpoint → active model name, billed per token | New | A |
| 4b | Train (Nebius Serverless Job) | AI Cloud `gpu-h100-sxm`, Unsloth 16-bit LoRA on nvidia/Llama-3.1-Nemotron-Nano-8B-v1 (dense, 16 GB merged); Nemotron 3 Nano 30B-A3B only if the D1 spike proves merge and serve | train + val → adapter and merged weights in Object Storage | Container written (4-bit QLoRA, Qwen default), never run; the VM provider it targets does not work | B |
| 5b | Serve (Nebius Serverless Endpoint) | AI Cloud, vLLM image | merged weights → OpenAI-compatible URL with bearer token | Written, never run | B |
| 6 | Evaluate (Nemotron 3 Ultra judge) | Token Factory | test set + answers from base and tuned → win rate, per-sample verdicts | New; the existing lm-eval node is a GPU benchmark container with an absolute 1–5 judge, kept as optional | A + B |
| 7 | Playground (compare) | The app | tuned vs base, same prompt, side by side | Exists; add the side-by-side | A + B |

**Real versus mocked.** Everything in the video is a real run. In the hosted app the golden run is real but pre-completed; "Run it yourself" launches Lane A at reduced scale (about 40 synthetic rows, 1 epoch) with a per-run spend cap and a daily cap on our key. The Lane A adapter stays live through Dec 15 because serverless LoRA is billed per token. The Lane B endpoint costs GPU-hours while up, so it is either woken on demand by a "Wake endpoint" button (about 5 minutes) or scheduled for the Dec 1–15 judging window; its training logs, loss curve, and eval verdicts are persisted either way.

**Cost per demo run (estimates, confirm on day 1):** Tavily about 15 credits (free tier); synthetic data about 300 pairs ≈ 0.4M output tokens on Super ≈ $0.40; judging 60 held-out questions × 2 models on Ultra ≈ $0.50; Token Factory LoRA fine-tune of about 0.5M training tokens, priced per token (rate on the Token Factory prices page); Lane B adds roughly 30 H100-minutes for training plus an L40S endpoint by the hour. Lane A stays under $2; Lane A + B under $5 at demo scale.

**The 3-minute video, beat by beat:** the problem in one sentence (0:00–0:15) → type one sentence into the Nemotron Copilot and watch the seven-node pipeline appear, or pick the template (0:15–0:40) → press Run; time-lapse of live logs with the cost meter ticking (0:40–1:25) → eval view: win rate and one judged example (1:25–1:55) → playground: the same Nebius question to base and tuned (1:55–2:25) → the Serverless Job and Endpoint in the Nebius console (2:25–2:45) → open source, repo, one line on what is next (2:45–3:00).

## Agent team and task list

The build runs as **seven Claude Code agents with fixed roles**, each owning a directory and a branch, coordinated by you as lead. Half a day of shared contracts comes first; after that the agents work in parallel, the QA agent gates every merge, and a real end-to-end run of the golden path is the only definition of progress. Days are numbered from today: D0 = Tue Oct 20 through D9 = Thu Oct 29; the deadline is Fri Oct 30, 10:00 AM PDT.

| Agent | Owns | Mission | Done when |
| --- | --- | --- | --- |
| A0 Lead (you + a planner agent) | this doc, `CHANGELOG.md`, merges, accounts | Keep the golden path green and make the lane-B go/no-go call | Submission accepted on Devpost with every link working logged-out |
| A1 Platform & Nebius | `packages/providers/`, config, hosting | Thin, tested clients for Token Factory inference + fine-tuning + LoRA deploy, Tavily, Serverless Jobs/Endpoints, Object Storage | A 50-row fine-tune → deploy → chat spike passes on D1; hosted demo is up on D6 |
| A2 Pipeline nodes | `containers/`, node registry, SDK | The seven demo nodes, each real, logging, costed, and stub-able | Every node runs in the golden path with artifacts and `cost.json` |
| A3 Executor & backend | `apps/api/` executor, routes, DB | Long-running nodes, remote logs, lineage, budget guard, templates, compare API | Golden run completes headless via API and survives one injected failure |
| A4 Frontend | `apps/web/` | Template gallery, run page, eval view, compare playground, Copilot box, polish | A judge reaches the eval view in under 3 minutes without help |
| A5 Training (Lane B) | `containers/train-unsloth/`, `containers/vllm-serve/` | Nemotron 3 Nano LoRA on a Serverless Job, served from a Serverless Endpoint | Tuned Nemotron answers a Nebius question from the endpoint; eval compares it with base |
| A6 QA & verification | `tests/`, `scripts/e2e_demo.py`, CI | Prove it works: contract tests, nightly real e2e, UI smoke, failure drills, fresh-clone test, rehearsals | Three clean rehearsals on the hosted app on D8 |
| A7 Submission & DevRel | `README.md`, `docs/`, Devpost, video | README that passes the stage-one check on its own, the 3-minute video, the feedback write-up | Everything uploaded by D9, 6 PM ET |

```
Oct 20–21  P0 Contracts & access
Oct 22–24  P1 Lane A end to end            ◆ G1 Oct 24: Lane A golden path green from the UI
Oct 25–27  P2 Lane B + Copilot + hosting    ◆ G2 Oct 25: GPU quota call   ◆ G3 Oct 27 (evening): feature freeze, hosted demo live
Oct 27–29  P3 QA, docs, video               ◆ G4 Oct 29, 6 PM ET: submitted   ║ Deadline Oct 30, 10:00 AM PDT
```

Phases overlap on purpose: QA and docs start the evening Lane B work stops, and the last 19 hours before the deadline are deliberately empty.

**Gates:** G1 Oct 24, 2026 Lane A golden path green from the UI, under $3 and under 25 minutes · G2 Oct 25, 2026 GPU quota granted? Lane B is in, otherwise it becomes video-only stretch · G3 Oct 27, 2026 evening feature freeze, hosted demo live · G4 Oct 29, 2026 submitted by 6 PM ET, a 19-hour buffer.

**How the agents work together**

- Contracts first (D1): `docs/contracts.md` fixes node inputs and outputs, artifact names, provider interfaces, and the run state machine. No parallel coding until it is merged; everything after is a PR against it.
- One branch per agent (`hack/a1-platform`, `hack/a2-nodes`, …) off `NebiusHackathon`, which stays the integration branch; the lead merges twice a day; CI must be green. Give each agent its brief as the role row above plus its task list below, and nothing more.
- Definition of done for every task: code, a test, one README line, and a screenshot for UI work. Stub mode makes CI fast; the nightly golden path runs for real.
- Nothing ships unless it is in the golden path or behind a flag. Seven nodes that never fail beat twenty that mostly work.
- Daily rhythm: a 15-minute morning sync where the lead sets the day's three priorities; an evening QA report (green/red per node) added to this doc; every decision dated in `CHANGELOG.md`, which later becomes the "what changed during the submission period" write-up.

**A0 — Lead**

- [ ] D0 · Redeem the $25 Token Factory promo (code `NEBIUS-DEVPOST-GLOBAL26`), join the Builders Program for the second $25 plus $25 Tavily, create a Tavily API key.
- [ ] D0 · Create a Nebius AI Cloud project, attach billing, check Administration → Limits → Quotas, file a quota request for 1×H100 (`gpu-h100-sxm`) and 1×L40S (`gpu-l40s-a or -d, whichever the region lists`) plus one VM; post the request in the Nebius Discord so it moves. This is the longest lead-time item in the plan.
- [ ] D0 · Make the repo public, add `LICENSE` (MIT), register the team and a draft project on Devpost under Best Apps and Agents.
- [ ] D0 · Create the agent worktrees and branches, start `CHANGELOG.md`, paste the task list below into the agents' briefs.
- [ ] D1 · Run the contracts session with A1, A2, A3 and merge `docs/contracts.md`.
- [ ] D3 onward · Merge twice a day; run `make demo` on the integration branch every evening; call G2 on D5 and the freeze on D7.
- [ ] D9 · Submit by 6 PM ET; check every link logged-out; tag `v0.1-hackathon`.

**A1 — Platform & Nebius integration**

- [ ] D1 · P0 · `providers/tokenfactory.py`, extending the existing services/nebius\_token\_factory.py: OpenAI-compatible client moved from the legacy studio URL to `https://api.tokenfactory.nebius.com/v1` with retries, guided JSON, and per-call token and dollar accounting from a price table for the Nemotron tiers.
- [ ] D1 · P0 · Fine-tuning client: upload train/val files (`purpose="fine-tune"`), create a LoRA job, poll status and events, list checkpoints with metrics, choose the best by validation loss.
- [ ] D1 · P0 · LoRA deploy client: `POST /v0/models` with `source=<job>:<checkpoint>`, poll `GET /v0/models/{name}` to `active`, delete on cleanup.
- [ ] D1 · P0 · **The spike that de-risks the whole plan:** 50 rows → fine-tune `meta-llama/Llama-3.1-8B-Instruct` with LoRA → deploy → one chat completion. Record wall time, cost, and every quirk for the feedback write-up.
- [ ] D2 · P0 · Tavily client (search, extract) with credit accounting and a page cap. Same day: an ORCHAPOD\_IMAGE\_PREFIX setting, public GHCR packages, and a Nebius Object Storage bucket (S3-compatible) as the artifact store for anything that runs on Nebius.
- [ ] D2 · P1 · `providers/nebius_serverless.py`: Jobs (`POST /ai/v1/jobs` with image, args, env, secrets, S3 volumes, platform, preset, timeout; get, cancel, delete), Endpoints (create, get, delete), IAM token refresh, Object Storage client.
- [ ] D3 · P1 · Put the Serverless Job provider behind the same interface as the existing H100 VM provider so A5 and A3 swap it in without touching nodes.
- [ ] D3 · P0 · `.env.example` listing every variable with where to get it; budget-guard settings (per-run and daily caps).
- [ ] D4 · P0 · Decide hosting (one Nebius CPU VM for API + Postgres + MinIO + Redis, frontend on Vercel, HTTPS) and have it reachable by D6 with an uptime check.

**A2 — Pipeline nodes**

- [ ] D1 · P0 · Node contract in the SDK: inputs by name, artifacts plus `cost.json` and `metrics.json`, log streaming, and a stub flag; every node below follows it.
- [ ] D2 · P0 · Web Research node (Tavily): seed URLs or a query → extract → chunk → `corpus.jsonl` with source URL, deduped, with a max-pages parameter.
- [ ] D2 · P0 · Synth Data node: add a grounded mode (passage → N short, sourced Q&A pairs via Nemotron 3 Super with a JSON schema); keep magpie and evol-instruct; emit tokens and dollars per call.
- [ ] D3 · P0 · Data Prep node: exact and near dedupe, optional Nemotron 3.5 Lightning quality filter (score 1–5, drop below 3), stratified train/val/test split, output validated against Token Factory's dataset rules.
- [ ] D3 · P0 · Fine-tune node (Token Factory): wraps the A1 client; emits job id, checkpoint id, and a loss-curve artifact; handles failed and cancelled jobs.
- [ ] D3 · P0 · Deploy adapter node (Token Factory): emits the model name and proves it with one completion.
- [ ] D4 · P0 · Evaluate node: generate answers for the held-out test set from base and tuned with identical decoding; Nemotron 3 Ultra pairwise, reference-guided judging with position swap; outputs win/tie/loss, per-sample verdicts with reasoning, a summary JSON, and cost.
- [ ] D5 · P1 · Copilot: re-point the existing prompt-to-workflow builder (agent/workflow\_builder.py and the "AI prompt" tab, on Claude today) to Nemotron 3 Super on Token Factory with JSON-schema output, update its system prompt to the new node set, validate against the registry; five tested example prompts. Half a day, since the UI and the validate tool exist.
- [ ] D6 · P1 · Lane B wiring: a Serverless Endpoint URL is a valid "tuned model" source for Evaluate and the playground.

**A3 — Executor & backend**

- [ ] D1 · P0 · Run and node state machine that tolerates long-polling nodes (a fine-tune can take 10–30 minutes), with cancellation, timeouts, a retry policy, and idempotent re-run of a failed node.
- [ ] D2 · P0 · Remote logs: /internal/log and the SDK already push every line; verify the WebSocket fan-out for containers running on Nebius, which need a public ORCHAPOD\_CONTROL\_URL (ngrok in dev, the hosted API later), because Job logs are not available over REST.
- [ ] D2 · P0 · Artifact lineage and cost roll-up per node and per run; `GET /runs/{id}/summary`.
- [ ] D3 · P0 · Budget guard: per-run cap, daily cap per key, reduced scale for anonymous demo runs.
- [ ] D4 · P0 · Compare playground API: two model sources (Token Factory base, Token Factory LoRA name, or an endpoint URL) → streamed answers.
- [ ] D4 · P0 · Templates and the golden-run fixture: seed the database with a real completed run (artifacts, logs, verdicts); "Run it yourself" clones the template.
- [ ] D5 · P1 · Serverless Job runtime: submit, poll, S3 artifact mounts, surface the failure reason.
- [ ] D6 · P0 · Public-demo hardening: anonymous read, guarded run, rate limits, CORS, health endpoints.

**A4 — Frontend**

- [ ] D2 · P0 · Palette entries and config forms for Research, Fine-tune, Deploy, and Evaluate with defaults and help text; hide the four palette nodes that have no container (hf-import, file-upload, s3-import, auto-label-cleanlab).
- [ ] D3 · P0 · Template gallery with "Distill a docs specialist" and two more templates; one-click Run.
- [ ] D3 · P0 · Run page: per-node status, live logs, elapsed time, cost meter; failure state with "retry node".
- [ ] D4 · P0 · Eval view: win-rate stat, win/tie/loss bars, sample judgments with the judge's reasoning.
- [ ] D4 · P0 · Compare playground: one prompt, base and tuned side by side, models picked from the run.
- [ ] D5 · P1 · Copilot box on the canvas: sentence in, pipeline appears, accept or edit.
- [ ] D6 · P0 · Polish: empty states, error toasts, loading states, OG image, a demo-mode banner that says what a run costs.
- [ ] D7 · P0 · Screenshots for README and Devpost; a 1080p recording-friendly layout.

**A5 — Training (Lane B)**

- [ ] D1 · P1 · Spike on a rented A100 80 GB (vast.ai, as with the reranker runs) while Nebius quota is pending: Unsloth 16-bit LoRA on the default student with 200 rows, loss goes down, merge, serve with vLLM, one completion; then try Nemotron 3 Nano 30B-A3B the same way and keep it only if merge and serve work within the day. Default student: `nvidia/Llama-3.1-Nemotron-Nano-8B-v1` (dense Llama architecture, 16 GB merged; the branch's current default is Qwen3-4B in code and Nemotron Mini 4B in the README).
- [ ] D2 · P1 · Training container: `train.py` reads the dataset from a mounted bucket, logs through the SDK, saves adapter and merged weights back to the bucket; pinned versions; `--max-steps` demo mode; public image on GHCR or Nebius Container Registry.
- [ ] D3 · P1 · Serving spec: `vllm/vllm-openai:v0.18.0-cu130`, weights from the bucket volume, `--served-model-name`, token auth, port 8000; a smoke-test script.
- [ ] D5 · P1 · After G2: first real Serverless Job on `gpu-h100-sxm`, measure time and cost; then the Endpoint; wire both into the run.
- [ ] D6 · P1 · Evaluate base Nemotron 3 Nano (Token Factory) against the tuned endpoint; capture the results for the video.
- [ ] D7 · P1 · Judging-window strategy for the endpoint: wake-on-demand button or a scheduled Dec 1–15 window, implemented or documented with its cost.

**A6 — QA & verification**

- [ ] D1 · P0 · CI on the integration branch: lint, unit tests, stub-mode pipeline test.
- [ ] D2 · P0 · Contract tests for every provider from recorded responses, plus a $1-a-day real-call test against Token Factory.
- [ ] D3 · P0 · `scripts/e2e_demo.py`: the golden path headless through the API; asserts artifacts, cost under the cap, and an eval summary; runs nightly from D3.
- [ ] D4 · P0 · Playwright smoke: template → run → eval view → playground.
- [ ] D5 · P0 · Failure drills: Token Factory rate limit, fine-tune job failure, judge timeout, preempted Serverless Job; the run recovers or fails with a readable message.
- [ ] D7 · P0 · Fresh-clone test: follow the README on a clean machine; time to first run under 20 minutes.
- [ ] D8 · P0 · Three full rehearsals on the hosted app; every glitch logged and fixed or documented; sign-off checklist.

**A7 — Submission & DevRel**

- [ ] D2 · P0 · README skeleton with the required sections: what, why, how; architecture drawing; "How we use Nemotron, Token Factory, AI Cloud, and Tavily"; setup; run the demo; costs; what changed during the submission period; license.
- [ ] D4 · P0 · Devpost draft: title, tagline, description, built-with, track, links; start the Token Factory and NVIDIA feedback doc from A1 and A5 notes.
- [ ] D6 · P0 · Video script from the beat list above, shot list, captions, OBS settings, no music.
- [ ] D8 · P0 · Record two takes on the hosted app, edit, upload to YouTube as public with a thumbnail.
- [ ] D8 · P0 · Final README pass with screenshots and exact commands; turn `CHANGELOG.md` into the "what changed" paragraph.
- [ ] D9 · P0 · Submit; verify every link opens logged-out; archive the tagged release.

## Submission checklist, risks, and runbook

Submit on Oct 29, 2026 by 6 PM ET, not on the deadline day. The checklist is what Devpost will ask for, in order; the risks table names the things most likely to sink the entry, and the first three are the ones to act on today.

**Submission checklist**

- [ ] Track: Best Apps and Agents selected.
- [ ] Title, tagline, and description that name the sponsor pieces explicitly: Nemotron 3 Super (teacher), Nemotron 3 Ultra (judge), Nemotron 3 Nano (student), Token Factory inference and fine-tuning with serverless LoRA deploy, AI Cloud Serverless Jobs and Endpoints, Object Storage, Tavily.
- [ ] Demo URL loads logged-out, shows the completed golden run, and "Run it yourself" works within the caps.
- [ ] YouTube video public, under 3:00, no music, no third-party marks; link pasted.
- [ ] Repo public with `LICENSE` (MIT) and a README that explains setup and the sponsor usage well enough to pass stage one on its own.
- [ ] "What changed during the submission period" paragraph (from `CHANGELOG.md`).
- [ ] Token Factory, AI Cloud, and NVIDIA feedback: specific, with examples (job logs not available over REST, dataset validation messages, LoRA validation time, whatever we hit).
- [ ] Built-with tags: Nebius Token Factory, Nemotron, Nebius AI Cloud, Tavily, vLLM, Unsloth, FastAPI, Next.js, React Flow, PostgreSQL.
- [ ] Both teammates added on Devpost and accepted; one representative named.
- [ ] Secrets scanned out of git history before the repo went public; demo key has per-run and daily caps; other keys rotated.
- [ ] Branch frozen and tagged `v0.1-hackathon`; the hosted app is monitored and funded through Dec 15, 2026.

**Risks and mitigations**

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| GPU quota on AI Cloud not granted by Oct 25 | High | Lane B missing from the demo | File the request on D0 and escalate in the Nebius Discord; Lane A is a complete product on its own; A5 validates the container on a rented GPU so Lane B can land in a day once quota arrives. Never show a non-Nebius GPU run as Nebius in the video |
| Token Factory fine-tuning surprises (dataset validation, queue time, adapter validation errors) | Medium | Lane A slips | The D1 spike finds them with 50 rows; keep the demo dataset small; fallback base `meta-llama/Llama-3.3-70B-Instruct` or uploading an externally trained adapter |
| Tuned model does not beat base under the judge | Medium | Weak story | Reference-guided pairwise judging with position swap; target format, brevity, and sourcing, which fine-tuning reliably moves; report honestly and add a format-compliance metric beside win rate |
| Hosted demo dies during judging (Dec 1, 2026 to Dec 15, 2026) | Medium | Design score collapses | Seeded golden run needs no live call to render; uptime monitor with restart; funded key; weekly check during judging |
| Hybrid Nemotron 3 Nano will not merge or serve in vLLM | Medium | Lane B slips | D1 spike; same-day switch to `nvidia/Llama-3.1-Nemotron-Nano-8B-v1` |
| Scope creep (Copilot, extra nodes, extra templates) | High | Golden path breaks late | Flags for everything P1; feature freeze D7 evening; QA gate on every merge |
| Two humans, ten days | High | Tasks slip | Agents do the typing; humans do accounts, decisions, review, and the video; cut P1 items first, never the golden path |
| Public "Run it yourself" burns credit | Low | Dollars | Reduced scale, per-run and daily caps, a kill switch env flag |
| Secrets in git history when the repo goes public | Medium | Stage-one risk and a security incident | Run a history scan before flipping, rotate every key, put `.env` in `.gitignore` |

**Runbook**

1. D8 recording morning: fund the key, run the golden path once, confirm eval and playground, clear stale runs, set demo scale, record two 1080p takes.
2. D9 submission: final nightly e2e green, tag, submit, verify every link logged-out, announce in the Nebius Discord.
3. Judging window: check uptime and spend daily; keep about $20 of Token Factory credit available; wake the Lane B endpoint if it is scheduled; answer judge questions on Devpost within a day.

**Sources**

- [Hackathon overview](https://nebiusglobalaihackathon.devpost.com/) · [Official rules](https://nebiusglobalaihackathon.devpost.com/rules) · [FAQs](https://nebiusglobalaihackathon.devpost.com/details/faqs) · [Schedule](https://nebiusglobalaihackathon.devpost.com/details/dates) · [Resources and credits](https://nebiusglobalaihackathon.devpost.com/resources)
- [Nebius Builders Program](https://dev.nebius.com/builders)
- [Nemotron models on Token Factory](https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference) · [Token Factory cookbook](https://github.com/nebius/token-factory-cookbook) (fine-tuning and LoRA deploy notebooks)
- [Models for fine-tuning](https://docs.tokenfactory.nebius.com/post-training/models) · [Deploy a fine-tuned model](https://docs.tokenfactory.nebius.com/fine-tuning/deploy-custom-model) · [Serverless LoRA base models](https://docs.tokenfactory.nebius.com/fine-tuning/models)
- [Serverless AI overview](https://docs.nebius.com/serverless/overview) · [Jobs quickstart](https://docs.nebius.com/serverless/quickstart/jobs) · [Managing jobs](https://docs.nebius.com/serverless/jobs/manage) · [`nebius ai job create` reference](https://docs.nebius.com/cli/reference/ai/job/create) · [Deploy a model on an Endpoint](https://docs.nebius.com/serverless/tutorials/deploy-model) · [Managing endpoints](https://docs.nebius.com/serverless/endpoints/manage)
- [Unsloth: Nemotron 3](https://unsloth.ai/docs/models/nemotron-3) · [Tavily free plan](https://costbench.com/software/web-scraping/tavily/free-plan/)
