# STATE — Orchapod × Nebius hackathon
Updated: 2026-10-22T07:01Z by orchestrator · Phase: P0 · Next gate: G1 Oct 24 · Branch: NebiusHackathon (checkout ~/src/orchapod-hack)

## Next actions (in order)
1. Hari — waiting: TAVILY_API_KEY; for the golden path (Lane B, R25) the Nebius AI Cloud setup — project id (NEBIUS_PROJECT_ID), a `nebius` CLI login on this Mac, the Object Storage bucket — plus the hosting console steps (vCPU quota 0→8 in eu-north1, GPU quotas → 1 + 1, VM, Hostinger A records; docs/HOSTING.md); golden-run topic by D6 (the docs specialist now uses Nemotron Nano); optional: HF_TOKEN + the Token Factory fine-tune rate only for the Llama templates; MinIO test data; AI disclosure; vast.ai instances.
2. Spikes 1 and 2 DONE (R24, R25). Spike 3 waits for TAVILY_API_KEY. MERGED: platform-w7, ml-w6 (docs template Lane B on Nemotron Nano, $2.66; CPU variant), backend-w7 (Super reporter, flakes fixed). In review: qa-w7 (e2e_agent real mode) → first live intent #2 run (≤ $0.50). In progress: devrel-w6, frontend-w6.
3. Wave 5: COMPLETE incl. qa-w6 and backend-w6 (startup sweep of leftover node containers; cancel race fixed; SQLite WAL). Parked: a millisecond double-click cancel can leave a node unmarked.
4. G1 Oct 24: intent #2 from the agent is LIVE-green (run 84e57f84, $0.10). The golden path is STUB-green on template 1; qa-w8 moves the smoke's golden path to template 4 (R25). The live golden run waits on GPU quota + the hosted API (Hari).

## Board (status ∈ TODO | IN_PROGRESS(<agent>, <branch>) | REVIEW | DONE | BLOCKED(<why>))
### orchestrator
- [x] P0 D0 bootstrap: clone, clean-ups, harness, tooling, push — DONE
- [x] P0 D1 contracts session → docs/contracts.md v1 merged (299 lines, rulings R1–R15) — DONE
- [ ] P0 D3+ merge twice a day; nightly real e2e; G2 call D5; freeze D7; submit D9 — TODO
### platform
- [x] P0 D1 spike 1: LoRA deploy retired (410) → Lane A serves via vllm-serve (R24); fine-tune works on meta-llama/Llama-3.1-8B-Instruct (6 min 45 s / 50 rows); R19 confirmed; adapter = PEFT dir — DONE (2026-10-22, ≤ $0.03)
- [x] P0 D1 TF client: api.tokenfactory.nebius.com, retries, guided JSON, per-call token + $ accounting — DONE (e0fa9a2)
- [x] P0 D1 fine-tuning client: files, LoRA job, poll status/events, checkpoints, best by val loss — DONE (e0fa9a2)
- [x] P0 D1 LoRA deploy client: POST /v0/models (unsupported path explicit), poll to active, delete — DONE (e0fa9a2; live behaviour = spike 1)
- [ ] P0 D2 spike 3 (Tavily extract of 10 docs.nebius.com pages) — BLOCKED(TAVILY_API_KEY); Tavily client DONE (packages/providers/tavily.py)
- [x] P0 D2 ORCHAPOD_IMAGE_PREFIX: executor, local provider and build script read it; CI pushes ghcr.io/<repo owner> = the default — DONE
- [x] P0 D1 one Token Factory client in packages/providers; zero-caller service deleted — DONE (e0fa9a2; synth and lm-eval switch in their tasks)
- [x] P0 D2 SPEND SAFETY: provider_selector defaults gpu nodes to ["runpod", "vastai"] (apps/api/services/provider_selector.py:74), so a set VASTAI_API_KEY rents a vast.ai GPU silently — default must be ["nebius"] and vastai only when named — DONE (platform-w2)
- [x] P0 D2 LocalDocker: a fast-failing container can be removed before `docker wait` sees it → node reads as succeeded (pre-existing; found by platform-w1) — DONE (platform-w2)
- [x] P1 D2 NebiusServerless (Jobs, Endpoints, REST ai/v1, IAM CLI fallback, find() recovery) + NebiusProvider on Jobs with a spend deadline — DONE (platform-w5; live behaviour waits on G2 quota + key)
- [x] P0 D2 setup gaps (compose 8001 and no Anthropic/253B judge; build script loops containers/*/; ensure_bucket_exists at API start; web default 8001) — DONE (wave 2)
- [x] P0 D3 .env.example complete (every var, default, where to get it, hosted-only block) + a test that every env name the code reads is listed — DONE (platform-w4)
- [ ] P0 D4 hosting: DECIDED A-M + orchapod.dev; repo side DONE (platform-w4); cloud side = Hari's console steps (docs/HOSTING.md bring-up: vCPU quota 0→8 in eu-north1 now, GPU quota 32→1 + 1, VM, bucket, Hostinger A records) — BLOCKED(Hari, console)
### data-engineering
- [x] P0 D2 web-research node: seed URLs | query → extract → chunk → corpus.jsonl, dedupe, max_pages, STUB=1 — DONE (data-w2)
- [x] P0 D2 synth-distilabel grounded mode (passage → short sourced Q&A, JSON schema) + price fix $0.30/$0.90 — DONE (data-w2)
- [x] P0 D2 synth-distilabel structured mode for intent #2 (user_id, movie_title, action, timestamp, device) — DONE (data-w2)
- [x] P0 D2 Dockerfiles build from the repo root; synth's vendored SDK deleted — DONE (a298ea1)
- [x] P0 D2 data-engineering reviewed the R19 diffs of its two Dockerfiles — DONE (data-w2 report)
- [x] P0 D2 synth-distilabel: Anthropic/OpenAI teacher branches and pip deps removed (Nemotron via packages/providers only) — DONE (data-w2)
- [x] P0 D3 data-prep: exact + near dedupe, train/val/test, TF dataset rules — DONE
- [x] P0 D3 data-prep quality_filter (Lightning 1–5, drop < 3, failure gate max(2, 10 %)) + the data-w1 minors + intent #1 data half in STUB — DONE (data-w3)
### ml-engineering
- [x] P1 D1 spike 4: Unsloth 16-bit LoRA on nvidia/Llama-3.1-Nemotron-Nano-8B-v1, vast.ai A100 — DONE ($1.29, 48 min; containers/unsloth-train/spike/RESULTS.md)
- [x] P0 D2 all 8 Dockerfiles build from the repo root + test_dockerfiles.py; synth's vendored SDK deleted (R19) — DONE (a298ea1)
- [x] P0 D2 lm-eval: Claude/Anthropic judge fallback removed — DONE (a298ea1)
- [x] P2 test_dockerfiles.py minors — DONE (ml-w2)
- [x] P0 D3 tf-finetune node (idempotent retry R19, lost-create recovery) — DONE (ml-w2; live behaviour waits on spike 1)
- [x] P0 D3 tf-deploy node (unsupported path → vllm-serve message; price check before deploy) — DONE (ml-w2; /v0/models = spike 1)
- [x] P0 D4 judge-eval node: base vs tuned, identical decoding, Ultra pairwise reference-guided, position swap, R18 fencing, pairing rule, GGUF via llama-server — DONE (ml-w3; R23)
- [x] P0 D4 quantize path for intent #3: maths shortlist, GGUF q4_k_m + keep_f16 on CPU, hf-download hardened — DONE (ml-w3); CPU timing of the full template → ml-w4
- [x] P1 D2 unsloth-train container on spike 4's lock: bucket I/O, SDK logs + loss, --max-steps, STUB — DONE (ml-w4; not built locally: ~20 GB amd64+CUDA)
- [ ] P1 D3 vllm-serve: test `--enable-lora` with the 8B adapter (one endpoint for base + tuned); merged weights are the proven fallback — TODO
- [x] P0 SECURITY vllm-serve token out of meta at the source (ModelRef api_key_env) + API redaction — DONE (ml-w4, backend-w3)
- [x] P1 shared R18 fence in packages/providers (NFKC/zero-width/bidi/tag-block aware, linear) used by synth-distilabel, data-prep, judge-eval — DONE (platform-w6)
- [ ] P1 D3 vllm-serve spec (vllm/vllm-openai:v0.18.0-cu130, token auth) + smoke script — TODO
- [ ] P1 D5 after G2: real Serverless Job + Endpoint; D6 eval vs base; D7 judging-window plan — TODO
### backend
- [x] P0 D1 spike 2: strict json_schema + thinking=False confirmed live; intent #2 plan valid first time ($0.0025, 7 s); Lightning too slow for reports → Super — DONE (2026-10-22, $0.0055)
- [x] P0 D1 run/node state machine for long-polling nodes: cancel, timeouts, retry-node — DONE (bc5c59f)
- [x] P0 D1 SDK: cost_json + metrics_json, progress, internal secret — DONE (bc5c59f)
- [x] P0 D2 Orchapod Agent planner on Nemotron (Claude out of agent/workflow_builder.py) + POST /agent/plan — DONE (backend-w2)
- [x] P0 D2 executor forwards only Nebius/Tavily/HF keys (_FORWARD); default provider_pref ["nebius"] — DONE
- [x] P1 D3 checkpoint-resume: retry reuses the row, so the newest checkpoint_step_* becomes ORCHAPOD_RESUME_CHECKPOINT_URI (tests/api/test_executor.py:316) — DONE
- [ ] P0 D2 remote logs: public ORCHAPOD_CONTROL_URL, WebSocket fan-out verified — TODO
- [x] P0 D2 lineage + cost roll-up; GET /runs/{id}/summary — DONE (bc5c59f)
- [x] P0 D3 budget guard: per-run, per-day, anonymous scale, ORCHAPOD_KILL_SWITCH — DONE (backend-w2)
- [x] P0 D3 agent validate → run → monitor → report; POST /agent/run, GET /agent/runs/{id}/report — DONE (backend-w2)
- [x] P0 D4 POST /compare; golden-run fixture (`make demo`); reduced-scale templates with `fits`; artifact meta redaction (R21/R22) — DONE (backend-w3)
- [x] P1 backend follow-ups: STUB stopwords, tf-finetune from tokens, SDK cost_json without thread joins, workflow_name, cancel tokens, executor gpu refusal, IAM token for rents_gpu nodes, GPU wall-time billing, endpoint deletion at expiry — DONE (backend-w5)
- [x] P0 D6 public-demo hardening: CORS allow-list, per-IP buckets (plan/run/compare/write), deep /health + /livez, kill switch per request, YAML aliases + 256k cap, extend deleted, read-only run workflows, gpu admin-only, secrets dropped at ingest — DONE (backend-w4); P2 left: anonymous cancel of others' runs, executor-level gpu refusal
- [x] P1 D5 Serverless Job runtime: NebiusProvider on Jobs (platform-w5) + IAM token, GPU wall-time billing, endpoint deletion (backend-w5) — code DONE; live waits on G2 quota + the hosted API (Jobs need a public https ORCHAPOD_CONTROL_URL)
### frontend
- [x] P0 D2 palette: hidden nodes without containers; Research/Fine-tune/Deploy/Evaluate forms; R13 JSON inputs — DONE
- [x] P0 D2 /agent page: chat box, plan card (Edit/Run), live run view, report card — DONE
- [x] P0 wave-2 frontend carry-overs (YAML quoting, RunView .catch, badges, a11y, defaultInputs) — DONE (frontend-w2)
- [ ] P1 Deploy palette text promises per-token serving — align with spike 1's answer — IN_PROGRESS(frontend-w6) (sidebar counts: DONE frontend-w2; web tests in make check + CI: DONE qa-w2)
- [x] P0 D3 run page cost meter + retry node (frontend-w2); template gallery with one-click Run (frontend-w3) — DONE (3d250c5)
- [x] P0 D4 eval view, dataset card, compare playground (STUB pills) — DONE (frontend-w3, 3d250c5); P2: the STUB pill reads metrics meta, dropped above 16 KB
- [x] P1 D3 loss chart fills from the fine-tune node's loss_curve on load; live events append — DONE (frontend-w4)
- [x] P0 D6 polish: toasts, honest error/empty/loading states, OG image, demo banner, `fits` on template cards, loss chart from loss_curve — DONE (frontend-w4); D7 screenshots — TODO
### P2 follow-ups (2026-10-22)
- [ ] platform: local_docker passes node env as `docker run -e K=V` (a key on a command line for an instant) → `-e K` with the value in the client's env; review the orchestrator's chat(create=True) (21e3806) — TODO
- [ ] data: quality_filter → chat(create=True); Lightning's 16–110 s latency vs its 30 s read timeout (opt-in, no template uses it) — TODO
- [ ] backend: estimate unsloth-train from max_steps (the flat $1.88 makes the reduced docs plan $2.32) — TODO
### qa
- [x] P0 D1 CI on NebiusHackathon + repo ruff config so `make check` is green; synth-distilabel in the image matrix — DONE (e11757e)
- [x] P0 D2 CI pushes `:latest` on NebiusHackathon (R4); pins in requirements-dev.txt — DONE
- [ ] P2 pytest warnings now 126 (sqlmodel session.exec deprecations; datetime.utcnow) — TODO
- [ ] P0 D2 provider contract tests from recorded responses + a $1/day real Token Factory call — TODO
- [ ] P0 D3 scripts/e2e_demo.py: --stub DONE (qa-w2; green 2026-10-21); real with --max-cost + nightly — TODO (needs the key)
- [x] P0 D3 scripts/e2e_agent.py --stub for the three canonical intents (+ plan-shape rules); strict by construction since qa-w5 (no SKIP path) — DONE
- [x] P0 D4 Playwright smoke (`make ui-smoke`, orchestrator-only): /agent intent #2, template run, public-cap check, golden path — DONE (qa-w3..w5)
- [ ] P0 D5 failure drills · D7 fresh-clone test < 20 min · D8 three rehearsals — TODO
### devrel
- [x] P0 D2 README skeleton — DONE
- [x] P1 README pass (STALE list, TODO(D8) markers) — DONE (devrel-w2)
- [x] P0 D4 Devpost draft (docs/devpost.md) + Token Factory / AI Cloud / NVIDIA feedback doc (docs/feedback.md) — DONE (devrel-w2; live facts TODO(D8))
- [ ] P0 D8 record and upload the video (script + shot list DONE: devrel-w3, d257183) · final README pass — TODO
- [ ] P0 D9 submit; every link checked logged-out; tag v0.1-hackathon — TODO

## Decisions (DECISION <date>: <what> — <why>; OPEN DECISION: <question>)
- DECISION 2026-10-20: integration branch is NebiusHackathon; agent branches stay local; fetch + merge origin before every push; never force-push; tag v0.1-hackathon at the freeze — Hari, chat.
- DECISION 2026-10-20: checkout ~/src/orchapod-hack, outside iCloud — Hari.
- DECISION 2026-10-20: .env seeded from the old .env.local minus Anthropic, OpenAI, NVIDIA NIM and RunPod keys — Hari.
- DECISION 2026-10-20: spike 4 on a vast.ai A100 80 GB, ≤ $6 and ≤ 3 h, instance destroyed after — Hari.
- DECISION 2026-10-20: worktree.baseRef=head plus a base check in every brief, because the remote default branch is main — orchestrator.
- DECISION 2026-10-20: compose project orchapod-hack; `make up` starts postgres, redis, minio only; API on 8001 (8000 = complychip2) — orchestrator. Local API moved to 8002 on 2026-10-21 (8001 = complychip-ED; CLAUDE.md).
- DECISION 2026-10-20: skip claude-mem (episodic-memory installed; these files are the source of truth); nebius CLI deferred to G2 — orchestrator.
- DECISION 2026-10-20: every container image builds with the repo root as context (matches CI, scripts/build-and-push-containers.sh and the local_docker hint); Dockerfile owners fix their COPY paths — qa finding.
- DECISION 2026-10-20: Lane B student = nvidia/Llama-3.1-Nemotron-Nano-8B-v1 — spike 4: 60 steps 62 s / 15.9 GiB, merge 41 s, vLLM healthy 51 s, fits an L40S; Nemotron-3-Nano-30B-A3B also works (router frozen) but is 12× slower per step and needs 80 GB — a proven option, not the default.
- DECISION 2026-10-21: gpu-l40s-a = $1.55/h (Intel L40S; $1.82 is the AMD gpu-l40s-d) — platform-w3, nebius.com/prices + docs component math; Lane B ≈ $2.65.
- DECISION 2026-10-21 (orchestrator ruling): ORCHAPOD_ANON_SCALE stays 0.1; real-estate's reduced template ($0.83 at the corrected L40S price) is admin-only until Hari raises the scale (≥ 0.3) inside the hosting decision.
- DECISION 2026-10-21: hosted VM never gets VASTAI_API_KEY; backups = 14 rotating slots in the bucket; deploy keeps explicit rsync excludes (.env, nebius/, deploys.log) — platform-w4, review agreed.
- DECISION 2026-10-21 (Hari): hosting A-M (Nebius cpu-e2 4 vCPU/16 GB, eu-north1), fallbacks A-W then B2; domain orchapod.dev (registrar Hostinger). Defaults until Hari says otherwise: deploy by Hari, day cap $5, anon scale 0.1, teardown Dec 16.
- OPEN DECISION: intent #1 deploy default (waits on spike 1).

- DECISION 2026-10-20 (audit triage): Anthropic/OpenAI code leaves the demo path now (P0, stage-one rule); Vast.ai/RunPod/legacy Compute stack (~3,500 lines) is hidden from the demo path (P1) and deleted after G1 if still off-path (P2); other dead weight (Alembic beside create_all, second model registry, static Registry page, zero-caller modules) is P2.

## Blockers
- TAVILY_API_KEY missing → spike 3, web-research live. (NEBIUS_API_KEY set 2026-10-22, validated.) GPU live runs → AI Cloud project + quota (Hari).
- RISK (P0, Lane A): Token Factory docs (checked 2026-10-20) say Meta fine-tunes deploy "only via Dedicated endpoints"; the serverless-deploy page is 404; custom weights on Dedicated endpoints are "beta, available on request"; Llama-3.3-70B left TF serverless 2026-08-31 (ml-engineering). Fallbacks in order: (a) /v0/models still works → as planned; (b) adapter download IS documented (checkpoint `result_files` + GET /v1/files/<id>/content, per /post-training/how-to-fine-tune; corrected 2026-10-21) → merge + GGUF on a Nebius CPU VM via llama.cpp (no GPU quota) or vLLM + LoRA on an AI Cloud Serverless Endpoint (needs quota) — untested whether the files load as PEFT; (c) Dedicated-endpoint custom-weights beta via Nebius Support; (d) Lane B serves the tuned model.

## Human actions
- [ ] Token Factory key → .env NEBIUS_API_KEY; redeem $25 promo (nebius.com/promo-code, NEBIUS-DEVPOST-GLOBAL26); join the Builders Program (dev.nebius.com/builders) for +$25 TF and +$25 Tavily
- [ ] Tavily key → .env TAVILY_API_KEY
- [ ] URGENT: ask Nebius (Discord / Token Factory Support): is per-token LoRA deploy (POST /v0/models) still available for Llama-3.1-8B fine-tunes, and can we join the custom-weights beta for Dedicated endpoints? GPU quota is now critical for both lanes
- [ ] AI Cloud project + billing; quota request 1× H100 (gpu-h100-sxm), 1× L40S, 1 VM, 1 VPC — file today, post in the Nebius Discord; Object Storage bucket + service account
- [ ] GHCR packages public (owner bangadpurva → Purva)
- [ ] Devpost team + draft project (Best Apps and Agents)
- [ ] vast.ai: two stopped instances from other projects (54041703 rec-l2-bench-2, 54062531 esci-bench-v2), stopped since 2026-10-03, still billing storage (~$0.20/h per the spike agent) — destroy them? Hari's call; agents leave them alone
- [ ] DECISION: disclose in the README/Devpost that the build used AI coding agents? (Hari's call)
- [ ] Before submission: GitHub's default branch is `main` (pre-hackathon code) — set it to NebiusHackathon, or link the branch explicitly in Devpost (repo admin: Purva)
- [ ] DECISION by D6: golden-run topic — the Nebius docs specialist (PLAN's default; template 4 now exists, NOT G1-ready until spike 1 settles tf-deploy) or intent #1 (US real-estate compliance; template 1)?
- [ ] Before the repo goes public (G3): gitleaks clean, keys rotated, docs/Jira.csv reviewed for personal data

## Tooling (installed skills/plugins/MCP, with install command)
- python 3.12.13 venv (`uv venv --python 3.12 .venv`; `uv pip install -r requirements-dev.txt -r apps/api/requirements.txt pyyaml boto3 redis huggingface_hub ruff`)
- uv 0.11.12 · node 26.5 · pnpm 11.0.9 · docker 28.1.1 (Docker Desktop; colima not needed) · gh 2.88.1 (cannot see this repo; use git) · jq 1.7.1 · tmux 3.6a · make 3.81
- ruff 0.17.1 (`uv tool install ruff`) · gitleaks 8.30.1 (`brew install gitleaks`)
- Playwright MCP (`claude mcp add -s project playwright -- npx @playwright/mcp@latest`, in .mcp.json)
- Plugins: superpowers 6.3.0, ponytail, episodic-memory (already installed) · nebius CLI: deferred to G2
- jsonschema in the shared venv (data-w2; also pinned in requirements-dev.txt) · images to rebuild after data-w2 merges: orchapod/synth-distilabel:dev (5 months stale), orchapod/web-research:dev (new), orchapod/data-prep:dev
## Spend to date (per day, per key)
- 2026-10-20: $1.29 (vast.ai A100 SXM4 80 GB at $1.2485/h, 48 min, spike 4; instance destroyed)
- 2026-10-22: ≈ $0.14 Token Factory (spike 1 ≤ $0.03 fine-tune of 50 rows; spike 2 $0.0055; live run #1 $0.1007; key validation $0)
## Golden path status (last real run: id, date, cost, result)
- 2026-10-22T07:01Z: LIVE intent #2 through the Agent API PASS — run 84e57f84 (Super's plan movie-interactions-synthetic: synth → prep), 446 s, $0.0966 run + $0.0041 planner/reporter = $0.1007, 928 rows, Super's report. First live run.
- 2026-10-22T05:43Z: G1 STUB green on 90020da (ml-w6 + backend-w7 merged): e2e_agent 3/3, demo e2e, ui-smoke 5/5. Live intent #2 next (qa-w7 real mode in review).
- 2026-10-21T17:53Z: G1 STUB green on 24e234a — e2e_agent 3/3, demo e2e, ui-smoke 5/5 (golden path, public-cap check, Save a copy). Live runs wait on NEBIUS_API_KEY.
- 2026-10-21: intent #2 STUB e2e PASS (`make check E2E=1` on 1c0b746): run 9214965e succeeded in 4 s, $0, dataset/train_jsonl/eval_jsonl registered, 500 rows downloadable. Live (non-STUB) runs wait on NEBIUS_API_KEY.
- Live: never run (waits on the key). `make check` green at 3d250c5 (519 passed, 126 warnings; web tests pass); gitleaks clean at bootstrap (1 triaged false positive).
