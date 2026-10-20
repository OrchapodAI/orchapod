# STATE — Orchapod × Nebius hackathon
Updated: 2026-10-20T22:39Z by orchestrator · Phase: P0 · Next gate: G1 Oct 24 · Branch: NebiusHackathon (checkout ~/src/orchapod-hack)

## Next actions (in order)
1. Hari: put NEBIUS_API_KEY and TAVILY_API_KEY in ~/src/orchapod-hack/.env (Human actions) — unblocks spikes 1–3 and every live check.
2. Contracts v1 — DONE (docs/contracts.md; rulings R1–R15 at its end).
3. Spike 4 — DONE: Lane B student = nvidia/Llama-3.1-Nemotron-Nano-8B-v1 (DECISION below).
4. Ponytail audit — DONE; triaged into the board below (audit: hackathon/briefs/2026-10-20-ponytail-audit-report.md).
5. Spikes 1–3 once keys land: platform (TF train → deploy → chat; Tavily extract), backend (Nemotron Super guided-JSON plan).
6. Wave 1 (hackathon/briefs/2026-10-20-wave1.md) — IN_PROGRESS: platform-w1, backend-w1, data-w1, ml-w1, frontend-w1, qa-w1, devrel-w1. Wave 2 after platform's clients merge: synth grounded/structured + web-research (data), tf-finetune/tf-deploy/judge-eval (ml), Agent API + budget + /compare (backend), quality_filter, config.py migration.

## Board (status ∈ TODO | IN_PROGRESS(<agent>, <branch>) | REVIEW | DONE | BLOCKED(<why>))
### orchestrator
- [x] P0 D0 bootstrap: clone, clean-ups, harness, tooling, push — DONE
- [x] P0 D1 contracts session → docs/contracts.md v1 merged (299 lines, rulings R1–R15) — DONE
- [ ] P0 D3+ merge twice a day; nightly real e2e; G2 call D5; freeze D7; submit D9 — TODO
### platform
- [ ] P0 D1 spike 1 (now decisive): 50 rows → TF LoRA fine-tune meta-llama/Meta-Llama-3.1-8B-Instruct → try POST /v0/models deploy → one chat call; ALSO dump the raw job + checkpoint JSON and test whether adapter files can be downloaded — BLOCKED(NEBIUS_API_KEY)
- [ ] P0 D1 TF client: api.tokenfactory.nebius.com, retries, guided JSON, per-call token + $ accounting — TODO
- [ ] P0 D1 fine-tuning client: files, LoRA job, poll status/events, checkpoints, best by val loss — TODO
- [ ] P0 D1 LoRA deploy client: POST /v0/models, poll to active, delete on cleanup — TODO
- [ ] P0 D2 spike 3 + Tavily client: search, extract, credit accounting, page cap — BLOCKED(TAVILY_API_KEY)
- [ ] P0 D2 ORCHAPOD_IMAGE_PREFIX (executor, CI, local provider agree) — TODO
- [ ] P0 D1 one Token Factory client: fold the three hand-rolled clients on the legacy host into it, delete the zero-caller one — TODO
- [ ] P0 D2 LocalDocker: a fast-failing container can be removed before `docker wait` sees it → node reads as succeeded (pre-existing; found by platform-w1) — TODO (wave 2)
- [ ] P1 D2 nebius_serverless provider: Jobs, Endpoints, IAM refresh, Object Storage — TODO
- [ ] P0 D2 setup gaps from devrel-w1 + ml-w1 review: compose (platform) still publishes 8000, names the 253B judge and passes ANTHROPIC_API_KEY; scripts/build-and-push-containers.sh builds 6 of 8 nodes (qa); storage bucket never auto-created (call ensure_bucket_exists at API start — backend); web app defaults to localhost:8000 (→ 8001 — frontend) — TODO (wave 2)
- [ ] P0 D3 .env.example complete (every var + where to get it) + budget-guard settings — TODO
- [ ] P0 D4 hosting decision; reachable by D6 with an uptime check — TODO
### data-engineering
- [ ] P0 D2 web-research node: seed URLs | query → extract → chunk → corpus.jsonl, dedupe, max_pages, STUB=1 — TODO
- [ ] P0 D2 synth-distilabel grounded mode (passage → short sourced Q&A, JSON schema) + price fix $0.30/$0.90 — TODO
- [ ] P0 D2 synth-distilabel structured mode for intent #2 (user_id, movie_title, action, timestamp, device) — TODO
- [ ] P0 D2 Dockerfiles build from the repo root (synth-distilabel, data-prep: `COPY packages/sdk-py/orchapod`, `COPY containers/<node>/…`); delete synth-distilabel's byte-identical SDK copy — TODO
- [ ] P0 D2 data-engineering reviews the R19 diffs of its two Dockerfiles (synth-distilabel, data-prep) — TODO (wave 2)
- [ ] P0 D2 synth-distilabel: remove the Anthropic/OpenAI teacher branches and the openai/anthropic pip deps from its image (Nemotron via packages/providers only) — TODO (wave 2)
- [ ] P0 D3 data-prep: exact + near dedupe, train/val/test, TF dataset rules (quality filter → wave 2) — APPROVED, waits for backend-w1 (hack/data-w1 @ a623fe6)
- [ ] P1 data-prep minors (review of data-w1): unhashable role crashes instead of dropping (move tf_valid inside the try); CSV keep_default_na=False; small-n test split can be empty; log before near-dedupe; tests for missing dataset, CSV, eval/test composition — TODO (with quality_filter, wave 2)
### ml-engineering
- [ ] P1 D1 spike 4: Unsloth 16-bit LoRA on nvidia/Llama-3.1-Nemotron-Nano-8B-v1, vast.ai A100 (≤ $6 / 3 h) — DONE ($1.29, 48 min; containers/unsloth-train/spike/RESULTS.md)
- [x] P0 D2 all 8 Dockerfiles build from the repo root + test_dockerfiles.py; synth's vendored SDK deleted (R19) — DONE (a298ea1)
- [x] P0 D2 lm-eval: Claude/Anthropic judge fallback removed — DONE (a298ea1)
- [ ] P2 test_dockerfiles.py minors: continuation regex `\\[ \t]*\n`, `assert DOCKERFILES` instead of >= 8, one-line docstring (no LocalDocker claim), ROOT.glob — TODO
- [ ] P0 D3 tf-finetune node: job id, checkpoint id, loss_curve.json; failed/cancelled handled — TODO
- [ ] P0 D3 tf-deploy node: model name + one proving completion — TODO
- [ ] P0 D4 judge-eval node: base vs tuned, identical decoding, Ultra pairwise reference-guided, position swap — TODO
- [ ] P0 D4 quantize path for intent #3: maths shortlist, GGUF q4_k_m on CPU, 50-item GSM8K eval — TODO
- [ ] P1 D2 unsloth-train container: bucket I/O, SDK logs, --max-steps, pinned to spike 4's requirements.lock.txt (BOS fix; Mamba out_proj excluded; tvm-ffi restore) — TODO
- [ ] P1 D3 vllm-serve: test `--enable-lora` with the 8B adapter (one endpoint for base + tuned); merged weights are the proven fallback — TODO
- [ ] P1 D3 vllm-serve spec (vllm/vllm-openai:v0.18.0-cu130, token auth) + smoke script — TODO
- [ ] P1 D5 after G2: real Serverless Job + Endpoint; D6 eval vs base; D7 judging-window plan — TODO
### backend
- [ ] P0 D1 spike 2: Nemotron 3 Super guided-JSON plan for intent #2 — BLOCKED(NEBIUS_API_KEY)
- [ ] P0 D1 run/node state machine for long-polling nodes: cancel, timeouts, retry-node — REVIEW(hack/backend-w1)
- [ ] P0 D1 SDK: cost_json + metrics_json, progress, internal secret — REVIEW(hack/backend-w1)
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
- [ ] P0 D2 palette: hide hf-import, file-upload, s3-import, auto-label-cleanlab; Research/Fine-tune/Deploy/Evaluate forms; buildYamlFromGraph JSON.stringifies object inputs (R13) — APPROVED, merges after backend-w1 (hack/frontend-w1)
- [ ] P0 D2 /agent page: chat box, plan card (Edit/Run), live run view, report card — APPROVED, merges after backend-w1 (hack/frontend-w1)
- [ ] P0 wave-2 frontend first: YAML quoting hole (strings starting with [ { " ' , must be quoted — LLM text flows through planYaml); RunView fetches need a .catch (stuck on Loading… after /agent/run); vllm-serve badge gpu → api; key by index for warnings/errors; a11y (aria-describedby, IME isComposing, live region); defaultInputs: drop teacher_kind, keep_alive_min 30 — TODO
- [ ] P1 sidebar shows numbers that look hardcoded (Runs 348, Base Models 47, Datasets 23, "$0 used / $250", team "orbital-research") — confirm, then feed from the API or remove; Deploy palette text promises per-token serving (unverified until spike 1); web tests into make check + CI (qa); pnpm 9 vs 11 (CI uses 9) — TODO
- [ ] P0 D3 template gallery (3 templates, one-click Run); run page cost meter + retry node — TODO
- [ ] P0 D4 eval view (win rate, W/T/L bars, judged samples); compare playground — TODO
- [ ] P1 D3 hide Vast.ai/RunPod surfaces from the demo path (one-click deploy, /inference + /endpoints pages); loss chart never receives data — wire it to loss_curve.json — TODO
- [ ] P0 D6 polish (empty, error, loading states; demo banner) · D7 screenshots — TODO
### qa
- [x] P0 D1 CI on NebiusHackathon + repo ruff config so `make check` is green; synth-distilabel in the image matrix — DONE (e11757e)
- [ ] P0 D2 CI pushes `:latest` on NebiusHackathon (R4); pins in requirements-dev.txt; never-awaited warning fixed — APPROVED; rebase after backend-w1 and fold in review minors (loosen test_harness pins, delete _clear_ttl_tasks + order-coupled tests, conftest utcnow) (hack/qa-w1)
- [ ] P2 56 remaining pytest warnings (mostly datetime.utcnow; list by owner in qa-w1 report) — TODO
- [ ] P0 D2 provider contract tests from recorded responses + a $1/day real Token Factory call — TODO
- [ ] P0 D3 scripts/e2e_demo.py (stub + real with --max-cost), nightly — TODO
- [ ] P0 D3 scripts/e2e_agent.py for the three canonical intents — TODO
- [ ] P0 D4 Playwright smoke: template → run → eval → playground; /agent intent #2 — TODO
- [ ] P0 D5 failure drills · D7 fresh-clone test < 20 min · D8 three rehearsals — TODO
### devrel
- [ ] P0 D2 README skeleton: what, why, how, sponsor usage, setup, demo, costs, what changed, license — APPROVED after fix round 1; merges after platform-w1, same push as qa-w1 (hack/devrel-w1)
- [ ] P1 devrel next README pass: put ANTHROPIC_API_KEY and OPENAI_API_KEY back in the test's STALE list (sponsor-compliance guard); README:140 hosted golden run and README:181 make e2e/agent-e2e/demo need TODO(D8) until real — TODO
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
- DECISION 2026-10-20: Lane B student = nvidia/Llama-3.1-Nemotron-Nano-8B-v1 — spike 4: 60 steps 62 s / 15.9 GiB, merge 41 s, vLLM healthy 51 s, fits an L40S; Nemotron-3-Nano-30B-A3B also works (router frozen) but is 12× slower per step and needs 80 GB — a proven option, not the default.
- OPEN DECISION: intent #1 deploy default (3B on a Serverless Endpoint vs 8B serverless LoRA) · hosting (D4).

- DECISION 2026-10-20 (audit triage): Anthropic/OpenAI code leaves the demo path now (P0, stage-one rule); Vast.ai/RunPod/legacy Compute stack (~3,500 lines) is hidden from the demo path (P1) and deleted after G1 if still off-path (P2); other dead weight (Alembic beside create_all, second model registry, static Registry page, zero-caller modules) is P2.

## Blockers
- NEBIUS_API_KEY and TAVILY_API_KEY missing → spikes 1–3 and all live checks.
- RISK (P0, Lane A): Token Factory docs (checked 2026-10-20) say Meta fine-tunes deploy "only via Dedicated endpoints"; the serverless-deploy page is 404; custom weights on Dedicated endpoints are "beta, available on request"; Llama-3.3-70B left TF serverless 2026-08-31 (ml-engineering). Fallbacks in order: (a) /v0/models still works → as planned; (b) adapter downloadable → merge + GGUF on a Nebius CPU VM via llama.cpp (no GPU quota) or vLLM + LoRA on an AI Cloud Serverless Endpoint (needs quota); (c) Dedicated-endpoint custom-weights beta via Nebius Support; (d) Lane B serves the tuned model.

## Human actions
- [ ] Token Factory key → .env NEBIUS_API_KEY; redeem $25 promo (nebius.com/promo-code, NEBIUS-DEVPOST-GLOBAL26); join the Builders Program (dev.nebius.com/builders) for +$25 TF and +$25 Tavily
- [ ] Tavily key → .env TAVILY_API_KEY
- [ ] URGENT: ask Nebius (Discord / Token Factory Support): is per-token LoRA deploy (POST /v0/models) still available for Llama-3.1-8B fine-tunes, and can we join the custom-weights beta for Dedicated endpoints? GPU quota is now critical for both lanes
- [ ] AI Cloud project + billing; quota request 1× H100 (gpu-h100-sxm), 1× L40S, 1 VM, 1 VPC — file today, post in the Nebius Discord; Object Storage bucket + service account
- [ ] GHCR packages public (owner bangadpurva → Purva)
- [ ] Devpost team + draft project (Best Apps and Agents)
- [ ] vast.ai: two stopped instances from other projects (54041703 rec-l2-bench-2, 54062531 esci-bench-v2), stopped since 2026-10-03, still billing storage (~$0.20/h per the spike agent) — destroy them? Hari's call; agents leave them alone
- [ ] DECISION: disclose in the README/Devpost that the build used AI coding agents? (Hari's call)
- [ ] Before the repo goes public (G3): gitleaks clean, keys rotated, docs/Jira.csv reviewed for personal data

## Tooling (installed skills/plugins/MCP, with install command)
- python 3.12.13 venv (`uv venv --python 3.12 .venv`; `uv pip install -r requirements-dev.txt -r apps/api/requirements.txt pyyaml boto3 redis huggingface_hub ruff`)
- uv 0.11.12 · node 26.5 · pnpm 11.0.9 · docker 28.1.1 (Docker Desktop; colima not needed) · gh 2.88.1 (cannot see this repo; use git) · jq 1.7.1 · tmux 3.6a · make 3.81
- ruff 0.17.1 (`uv tool install ruff`) · gitleaks 8.30.1 (`brew install gitleaks`)
- Playwright MCP (`claude mcp add -s project playwright -- npx @playwright/mcp@latest`, in .mcp.json)
- Plugins: superpowers 6.3.0, ponytail, episodic-memory (already installed) · nebius CLI: deferred to G2
## Spend to date (per day, per key)
- 2026-10-20: $1.29 (vast.ai A100 SXM4 80 GB at $1.2485/h, 48 min, spike 4; instance destroyed)
## Golden path status (last real run: id, date, cost, result)
- Never run end to end. `make check` green since e11757e (ruff E4/E7/E9/F clean, pytest 153 passed); gitleaks clean (1 triaged false positive).
