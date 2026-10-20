# STATE — Orchapod × Nebius hackathon
Updated: 2026-10-20T22:39Z by orchestrator · Phase: P0 · Next gate: G1 Oct 24 · Branch: NebiusHackathon (checkout ~/src/orchapod-hack)

## Next actions (in order)
1. Hari: put NEBIUS_API_KEY and TAVILY_API_KEY in ~/src/orchapod-hack/.env (Human actions) — unblocks spikes 1–3 and every live check.
2. Contracts session: platform, data-engineering, ml-engineering, backend propose their sections (read-only); orchestrator merges docs/contracts.md.
3. Spike 4 (ml-engineering): vast.ai A100 80 GB, ≤ $6 / 3 h, destroyed after → DECISION: Lane B student.
4. Ponytail audit — DONE; triaged into the board below (audit: hackathon/briefs/2026-10-20-ponytail-audit-report.md).
5. Spikes 1–3 once keys land: platform (TF train → deploy → chat; Tavily extract), backend (Nemotron Super guided-JSON plan).
6. Dispatch the D1–D2 P0 tasks below, at most two per agent, each in its own worktree.

## Board (status ∈ TODO | IN_PROGRESS(<agent>, <branch>) | REVIEW | DONE | BLOCKED(<why>))
### orchestrator
- [x] P0 D0 bootstrap: clone, clean-ups, harness, tooling, push — DONE
- [ ] P0 D1 contracts session → docs/contracts.md merged — IN_PROGRESS(platform, data-engineering, ml-engineering, backend; read-only proposals)
- [ ] P0 D3+ merge twice a day; nightly real e2e; G2 call D5; freeze D7; submit D9 — TODO
### platform
- [ ] P0 D1 spike 1: 50 rows → TF LoRA fine-tune Llama-3.1-8B → /v0/models deploy → one chat call — BLOCKED(NEBIUS_API_KEY)
- [ ] P0 D1 TF client: api.tokenfactory.nebius.com, retries, guided JSON, per-call token + $ accounting — TODO
- [ ] P0 D1 fine-tuning client: files, LoRA job, poll status/events, checkpoints, best by val loss — TODO
- [ ] P0 D1 LoRA deploy client: POST /v0/models, poll to active, delete on cleanup — TODO
- [ ] P0 D2 spike 3 + Tavily client: search, extract, credit accounting, page cap — BLOCKED(TAVILY_API_KEY)
- [ ] P0 D2 ORCHAPOD_IMAGE_PREFIX (executor, CI, local provider agree) — TODO
- [ ] P0 D1 one Token Factory client: fold the three hand-rolled clients on the legacy host into it, delete the zero-caller one — TODO
- [ ] P1 D2 nebius_serverless provider: Jobs, Endpoints, IAM refresh, Object Storage — TODO
- [ ] P0 D3 .env.example complete (every var + where to get it) + budget-guard settings — TODO
- [ ] P0 D4 hosting decision; reachable by D6 with an uptime check — TODO
### data-engineering
- [ ] P0 D2 web-research node: seed URLs | query → extract → chunk → corpus.jsonl, dedupe, max_pages, STUB=1 — TODO
- [ ] P0 D2 synth-distilabel grounded mode (passage → short sourced Q&A, JSON schema) + price fix $0.30/$0.90 — TODO
- [ ] P0 D2 synth-distilabel structured mode for intent #2 (user_id, movie_title, action, timestamp, device) — TODO
- [ ] P0 D2 Dockerfiles build from the repo root (synth-distilabel, data-prep: `COPY packages/sdk-py/orchapod`, `COPY containers/<node>/…`); delete synth-distilabel's byte-identical SDK copy — TODO
- [ ] P0 D2 synth-distilabel: remove the Anthropic/OpenAI teacher branches (Nemotron on Token Factory only) — TODO
- [ ] P0 D3 data-prep: exact + near dedupe, Lightning quality filter, train/val/test, TF dataset rules — TODO
### ml-engineering
- [ ] P1 D1 spike 4: Unsloth 16-bit LoRA on nvidia/Llama-3.1-Nemotron-Nano-8B-v1, vast.ai A100 (≤ $6 / 3 h) — IN_PROGRESS(ml-engineering, hack/ml-spike4)
- [ ] P0 D2 Dockerfiles build from the repo root (distill-sft, hf-download, lm-eval, quantize, vllm-serve) — TODO
- [ ] P0 D2 lm-eval: judge fallback re-pointed to Nemotron Ultra (no Anthropic/OpenAI) — TODO
- [ ] P0 D3 tf-finetune node: job id, checkpoint id, loss_curve.json; failed/cancelled handled — TODO
- [ ] P0 D3 tf-deploy node: model name + one proving completion — TODO
- [ ] P0 D4 judge-eval node: base vs tuned, identical decoding, Ultra pairwise reference-guided, position swap — TODO
- [ ] P0 D4 quantize path for intent #3: maths shortlist, GGUF q4_k_m on CPU, 50-item GSM8K eval — TODO
- [ ] P1 D2 unsloth-train container: bucket I/O, SDK logs, --max-steps, pinned versions — TODO
- [ ] P1 D3 vllm-serve spec (vllm/vllm-openai:v0.18.0-cu130, token auth) + smoke script — TODO
- [ ] P1 D5 after G2: real Serverless Job + Endpoint; D6 eval vs base; D7 judging-window plan — TODO
### backend
- [ ] P0 D1 spike 2: Nemotron 3 Super guided-JSON plan for intent #2 — BLOCKED(NEBIUS_API_KEY)
- [ ] P0 D1 run/node state machine for long-polling nodes: cancel, timeouts, retry-node — TODO
- [ ] P0 D1 SDK: cost.json + metrics.json conventions — TODO
- [ ] P0 D2 Orchapod Agent planner on Nemotron (Claude out of agent/workflow_builder.py) + POST /agent/plan — TODO
- [ ] P0 D2 executor forwards only Nebius/Tavily/HF keys to containers (no ANTHROPIC/OPENAI); default provider_pref not vastai — TODO
- [ ] P1 D3 checkpoint-resume never fires (looks in a fresh NodeRun's empty outputs); drop the 19 debug log.warning lines in the executor — TODO
- [ ] P0 D2 remote logs: public ORCHAPOD_CONTROL_URL, WebSocket fan-out verified — TODO
- [ ] P0 D2 lineage + cost roll-up; GET /runs/{id}/summary — TODO
- [ ] P0 D3 budget guard: per-run, per-day, anonymous scale, ORCHAPOD_KILL_SWITCH — TODO
- [ ] P0 D3 agent validate → run → monitor → report; POST /agent/run, GET /agent/runs/{id}/report — TODO
- [ ] P0 D4 compare playground API; templates + golden-run fixture — TODO
- [ ] P1 D5 Serverless Job runtime · P0 D6 public-demo hardening (anon read, rate limits, CORS, health) — TODO
### frontend
- [ ] P0 D2 palette: hide hf-import, file-upload, s3-import, auto-label-cleanlab; Research/Fine-tune/Deploy/Evaluate forms — TODO
- [ ] P0 D2 /agent page: chat box, plan card (Edit/Run), live run view, report card — TODO
- [ ] P0 D3 template gallery (3 templates, one-click Run); run page cost meter + retry node — TODO
- [ ] P0 D4 eval view (win rate, W/T/L bars, judged samples); compare playground — TODO
- [ ] P1 D3 hide Vast.ai/RunPod surfaces from the demo path (one-click deploy, /inference + /endpoints pages); loss chart never receives data — wire it to loss_curve.json — TODO
- [ ] P0 D6 polish (empty, error, loading states; demo banner) · D7 screenshots — TODO
### qa
- [ ] P0 D1 CI on NebiusHackathon + repo ruff config so `make check` is green; synth-distilabel in the image matrix — REVIEW(hack/qa-check @ 7e77488)
- [ ] P0 D2 provider contract tests from recorded responses + a $1/day real Token Factory call — TODO
- [ ] P0 D3 scripts/e2e_demo.py (stub + real with --max-cost), nightly — TODO
- [ ] P0 D3 scripts/e2e_agent.py for the three canonical intents — TODO
- [ ] P0 D4 Playwright smoke: template → run → eval → playground; /agent intent #2 — TODO
- [ ] P0 D5 failure drills · D7 fresh-clone test < 20 min · D8 three rehearsals — TODO
### devrel
- [ ] P0 D2 README skeleton: what, why, how, sponsor usage, setup, demo, costs, what changed, license — TODO
- [ ] P0 D4 Devpost draft + Token Factory / AI Cloud / NVIDIA feedback doc — TODO
- [ ] P0 D6 video script + shot list · D8 record and upload · final README pass — TODO
- [ ] P0 D9 submit; every link checked logged-out; tag v0.1-hackathon — TODO

## Decisions (DECISION <date>: <what> — <why>; OPEN DECISION: <question>)
- DECISION 2026-10-20: integration branch is NebiusHackathon; agent branches stay local; fetch + merge origin before every push; never force-push; tag v0.1-hackathon at the freeze — Hari, chat.
- DECISION 2026-10-20: checkout ~/src/orchapod-hack, outside iCloud — Hari.
- DECISION 2026-10-20: .env seeded from the old .env.local minus Anthropic, OpenAI, NVIDIA NIM and RunPod keys — Hari.
- DECISION 2026-10-20: spike 4 on a vast.ai A100 80 GB, ≤ $6 and ≤ 3 h, instance destroyed after — Hari.
- DECISION 2026-10-20: worktree.baseRef=head plus a base check in every brief, because the remote default branch is main — orchestrator.
- DECISION 2026-10-20: compose project orchapod-hack; `make up` starts postgres, redis, minio only; API on 8001 (8000 = complychip2) — orchestrator.
- DECISION 2026-10-20: skip claude-mem (episodic-memory installed; these files are the source of truth); nebius CLI deferred to G2 — orchestrator.
- DECISION 2026-10-20: every container image builds with the repo root as context (matches CI, scripts/build-and-push-containers.sh and the local_docker hint); Dockerfile owners fix their COPY paths — qa finding.
- OPEN DECISION: Lane B student (spike 4) · intent #1 deploy default (3B on a Serverless Endpoint vs 8B serverless LoRA) · hosting (D4).

- DECISION 2026-10-20 (audit triage): Anthropic/OpenAI code leaves the demo path now (P0, stage-one rule); Vast.ai/RunPod/legacy Compute stack (~3,500 lines) is hidden from the demo path (P1) and deleted after G1 if still off-path (P2); other dead weight (Alembic beside create_all, second model registry, static Registry page, zero-caller modules) is P2.

## Blockers
- NEBIUS_API_KEY and TAVILY_API_KEY missing → spikes 1–3 and all live checks.

## Human actions
- [ ] Token Factory key → .env NEBIUS_API_KEY; redeem $25 promo (nebius.com/promo-code, NEBIUS-DEVPOST-GLOBAL26); join the Builders Program (dev.nebius.com/builders) for +$25 TF and +$25 Tavily
- [ ] Tavily key → .env TAVILY_API_KEY
- [ ] AI Cloud project + billing; quota request 1× H100 (gpu-h100-sxm), 1× L40S, 1 VM, 1 VPC — file today, post in the Nebius Discord; Object Storage bucket + service account
- [ ] GHCR packages public (owner bangadpurva → Purva)
- [ ] Devpost team + draft project (Best Apps and Agents)
- [ ] vast.ai: two stopped instances from other projects (54041703 rec-l2-bench-2, 54062531 esci-bench-v2), stopped since 2026-10-03, still billing storage (~$0.20/h per the spike agent) — destroy them? Hari's call; agents leave them alone
- [ ] Before the repo goes public (G3): gitleaks clean, keys rotated, docs/Jira.csv reviewed for personal data

## Tooling (installed skills/plugins/MCP, with install command)
- python 3.12.13 venv (`uv venv --python 3.12 .venv`; `uv pip install -r requirements-dev.txt -r apps/api/requirements.txt pyyaml boto3 redis huggingface_hub ruff`)
- uv 0.11.12 · node 26.5 · pnpm 11.0.9 · docker 28.1.1 (Docker Desktop; colima not needed) · gh 2.88.1 (cannot see this repo; use git) · jq 1.7.1 · tmux 3.6a · make 3.81
- ruff 0.17.1 (`uv tool install ruff`) · gitleaks 8.30.1 (`brew install gitleaks`)
- Playwright MCP (`claude mcp add -s project playwright -- npx @playwright/mcp@latest`, in .mcp.json)
- Plugins: superpowers 6.3.0, ponytail, episodic-memory (already installed) · nebius CLI: deferred to G2
## Spend to date (per day, per key)
- 2026-10-20: $0
## Golden path status (last real run: id, date, cost, result)
- Never run end to end. Baseline 2026-10-20: pytest 153 passed; ruff 168 findings (no repo config yet); gitleaks clean (1 triaged false positive).
