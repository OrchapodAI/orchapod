# STATE — Orchapod × Nebius hackathon
Updated: 2026-10-27T03:06Z · prev 2026-10-26T00:20Z by orchestrator · Phase: P3 · G1 MET 10-22 · G2 MET 10-25 (live golden run) · Next gate: G3 Oct 27 freeze · Branch: NebiusHackathon (checkout ~/src/orchapod-hack)

## Next actions (in order)
1. Nothing in flight.
   - The hosted app runs dfe67d7 (deployed 10-25 19:13Z); NO-CAP TEST WINDOW (Hari, 10-27 03:04Z): day and run caps $1000, visitors 0.1 ($100, no GPU) until the 12:00Z timer restores $5 / $3 / 0.1 (it waits for runs in flight); the cap rises to $20 on Oct 29 00:00Z (timer).
   - The fresh clone is green in 3 min 35 s (qa-w11); the security review has no open critical or high finding; gitleaks is clean over all refs.
   - Next: G3 (Oct 27), hackathon/G3-CHECKLIST.md. Section A is done except the tag; B's anonymous check passed 10-26 00:11Z on dfe67d7; D is Hari's.
2. DONE 10-25:
   - D8 rehearsal PASS: 0ee1e20a, from the hosted UI, 23.5 min, $1.58, Ultra 7/20/3 (win rate 0.57).
   - Wave 6 + frontend-w8b/w9/w10 deployed (85878e4).
   - Screenshots in docs/img (082cf60).
   - Silent video draft: footage/video-draft/ (gitignored).
3. Hari (hackathon/WAITING_FOR_HUMAN):
   - the voice-over and the video upload;
   - the day cap for the judging window;
   - the repo public at G3 (keys rotated, Jira.csv);
   - Devpost submit.
4. Oct 27: G3 freeze, tag v0.1-hackathon. Oct 29 6 PM ET: submit.
   - Operating rule from now: no admin runs on the hosted app. Admin spend uses up the public's day share.
5. P2 when idle:
   - data: quality_filter → chat(create=True);
   - backend: the unsloth estimate from max_steps (the flat $1.88 makes Super shrink plans that can never fit).

## Board (status ∈ TODO | IN_PROGRESS(<agent>, <branch>) | REVIEW | DONE | BLOCKED(<why>))
### orchestrator
- [x] P0 D0 bootstrap: clone, clean-ups, harness, tooling, push — DONE
- [x] P0 D1 contracts session → docs/contracts.md v1 merged (299 lines, rulings R1–R15) — DONE
- [ ] P0 D3+ merge twice a day; nightly real e2e; G2 call D5; freeze D7; submit D9 — TODO
### platform
- [x] P0/P1 DONE:
  - TF client (inference, fine-tuning, LoRA deploy; e0fa9a2); spikes 1 and 3;
  - ORCHAPOD_IMAGE_PREFIX; provider default ["nebius"]; the LocalDocker race;
  - NebiusServerless Jobs/Endpoints (platform-w5); setup gaps; .env.example complete;
  - the zero-caller service deleted.
- [x] P0 D4 hosting: hosted demo LIVE 2026-10-25 at app/api.orchapod.dev.
  - VM orchapod-hosted: eu-west1 cpu-d3 4vcpu-16gb, 66.201.6.77.
  - Bucket orchapod-artifacts-d0c131 (eu-north1) and Nebius Container Registry cr.eu-north1.nebius.cloud/e00zbsmf901a9v6504.
  - DNS at Hostinger. Deploy: `ORCHAPOD_DEPLOY_HOST=orchapod@66.201.6.77 scripts/deploy-hosted.sh`.
  - DONE (orchestrator; LOG 05:02Z–05:24Z)
### data-engineering
- [x] P0 all DONE (data-w2, data-w3, a298ea1):
  - web-research (Tavily, STUB=1);
  - synth grounded + structured with the $0.30/$0.90 prices;
  - data-prep dedupe, splits, TF rules and the Lightning quality_filter;
  - Dockerfiles build from the repo root;
  - no Anthropic/OpenAI teacher branches.
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
- [x] P1 D3 vllm-serve `--enable-lora` with the 8B adapter (base + tuned on one L40S endpoint) — DONE, proven live in d20d30f3
- [x] P0 SECURITY vllm-serve token out of meta at the source (ModelRef api_key_env) + API redaction — DONE (ml-w4, backend-w3)
- [x] P1 shared R18 fence in packages/providers (NFKC/zero-width/bidi/tag-block aware, linear) used by synth-distilabel, data-prep, judge-eval — DONE (platform-w6)
- [x] P1 D3 vllm-serve spec (vllm/vllm-openai:v0.18.0-cu130, token auth, --enable-lora base + tuned on one endpoint) — DONE (ml-w4..w6; live smoke = the golden run on G2)
- [x] P1 D5 a real Serverless Job (H100) and Endpoint (L40S); D6 eval vs base (Ultra 7W/22T/1L) — DONE (d20d30f3) · [ ] D7 judging-window plan (endpoint up only while recording) — TODO
### backend
- [x] P0 D1 spike 2: strict json_schema + thinking=False confirmed live; intent #2 plan valid first time ($0.0025, 7 s); Lightning too slow for reports → Super — DONE (2026-10-22, $0.0055)
- [x] P0 D1 run/node state machine for long-polling nodes: cancel, timeouts, retry-node — DONE (bc5c59f)
- [x] P0 D1 SDK: cost_json + metrics_json, progress, internal secret — DONE (bc5c59f)
- [x] P0 D2 Orchapod Agent planner on Nemotron (Claude out of agent/workflow_builder.py) + POST /agent/plan — DONE (backend-w2)
- [x] P0 D2 executor forwards only Nebius/Tavily/HF keys (_FORWARD); default provider_pref ["nebius"] — DONE
- [x] P1 D3 checkpoint-resume: retry reuses the row, so the newest checkpoint_step_* becomes ORCHAPOD_RESUME_CHECKPOINT_URI (tests/api/test_executor.py:316) — DONE
- [x] P0 D2 remote logs: public ORCHAPOD_CONTROL_URL (hosted), WebSocket fan-out, persisted node_log + GET /runs/{id}/logs — DONE (hosted 10-25; backend-w9 6748fe6)
- [x] P3 where each step runs: summary provider + resource {kind, id, live state}; header GPU from the first GPU node — DONE (backend-w9 6748fe6)
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
- [x] P1 Deploy palette text promises per-token serving — DONE (frontend-w6: tf-deploy out of the palette, R25 order, forms for train/serve)
- [x] P0 D3 run page cost meter + retry node (frontend-w2); template gallery with one-click Run (frontend-w3) — DONE (3d250c5)
- [x] P0 D4 eval view, dataset card, compare playground (STUB pills) — DONE (frontend-w3, 3d250c5); P2: the STUB pill reads metrics meta, dropped above 16 KB
- [x] P1 D3 loss chart fills from the fine-tune node's loss_curve on load; live events append — DONE (frontend-w4)
- [x] P0 D6 polish: toasts, honest error/empty/loading states, OG image, demo banner, `fits` on template cards, loss chart from loss_curve — DONE (frontend-w4); fresh-clone polish (scroll, no 'Coming soon', title, labels) DONE (frontend-w7); D7 screenshots — TODO (after the wave 6 deploy)
- [x] P3 log history, provider/resource on node cards, canvas ?run= status — DONE (frontend-w8 a22bacf) · [ ] ui-smoke regression fix (compare playground unmounted) — IN_PROGRESS(frontend, hack/frontend-w8b)
### P2 follow-ups (2026-10-22)
- [x] platform: local_docker passes node env by name (`-e K`, values in the CLI's env) — DONE (orchestrator, checked on Docker Desktop); [ ] platform reviews the orchestrator's chat(create=True) (21e3806) at its next task — TODO
- [ ] data: quality_filter → chat(create=True); Lightning's 16–110 s latency vs its 30 s read timeout (opt-in, no template uses it) — TODO
- [ ] backend: estimate unsloth-train from max_steps (the flat $1.88 makes the reduced docs plan $2.32) — TODO
### qa
- [x] P0 D1 CI on NebiusHackathon + repo ruff config so `make check` is green; synth-distilabel in the image matrix — DONE (e11757e)
- [x] P0 D2 CI pushes `:latest` on NebiusHackathon (R4); pins in requirements-dev.txt — DONE
- [x] P2 pytest warnings (were 126) — now 2 (1123 passed) — DONE
- [ ] P0 D2 provider contract tests from recorded responses + a $1/day real Token Factory call — TODO
- [x] P0 D3 real e2e: `make agent-e2e INTENT=… MAX_COST=…` (qa-w7; live runs 84e57f84, 59786797) and the live golden run `make e2e API=https://api.<domain>` (qa-w9, runs on G2 day) — DONE; nightly: dropped (manual, capped runs instead)
- [x] P0 D3 scripts/e2e_agent.py --stub for the three canonical intents (+ plan-shape rules); strict by construction since qa-w5 (no SKIP path) — DONE
- [x] P0 D4 Playwright smoke (`make ui-smoke`, orchestrator-only): /agent intent #2, template run, public-cap check, golden path — DONE (qa-w3..w5)
- [x] P0 D7 fresh-clone test: green in 6 min 38 s on warm caches (qa-w10, 2026-10-22); its P0 (MinIO image gone) fixed — DONE · [x] failure drills (tests/drills) — DONE · [ ] D8 three rehearsals — TODO
### devrel
- [x] P0 D2 README skeleton — DONE
- [x] P1 README pass (STALE list, TODO(D8) markers) — DONE (devrel-w2)
- [x] P0 D4 Devpost draft (docs/devpost.md) + Token Factory / AI Cloud / NVIDIA feedback doc (docs/feedback.md) — DONE (devrel-w2); live golden-run facts + bring-up feedback DONE (devrel-w9 93ab38b; 6 TODO(D8) left, all future)
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
- DECISION 2026-10-22 (orchestrator): intent #1 deploy = vllm-serve (spike 1: per-token deploy 410; R24).
- DECISION 2026-10-22 (orchestrator): G1 = template 4 green from the UI on stubs + live intents #2/#3 through the Agent; PLAN's live Lane A bar is superseded by R24/R25.
- DECISION 2026-10-25 (Hari): hosted day cap ORCHAPOD_MAX_DAY_USD = $20 from 2026-10-29 00:00 UTC (judging window; public share $2/day). It is applied by the VM's orchapod-daycap.timer.
- DECISION 2026-10-24 (Hari): hosted day cap ORCHAPOD_MAX_DAY_USD = $10 for G2 day (two golden-run attempts fit), back to $5 after the golden run.
- DECISION 2026-10-22 (orchestrator): local MinIO image = pgsty/minio pinned by digest (minio/minio is gone from anonymous Docker Hub; qa-w10 P0).
- DECISION 2026-10-25 (orchestrator): no GPU-free Lane A fallback. G2 passed live on Lane B (d20d30f3).
- DECISION 2026-10-25 (orchestrator): the unsloth-train image trains Llama-architecture students only. Its Mamba-2 wheels broke `import unsloth` on CUDA (fa20d166); fix 69cafd1.
- DECISION 2026-10-25 (Hari): node images come from the Nebius Container Registry in the same project (plan B), because GHCR is private. Jobs pull with no credentials.

- DECISION 2026-10-20 (audit triage): Anthropic/OpenAI code leaves the demo path now (P0, stage-one rule); Vast.ai/RunPod/legacy Compute stack (~3,500 lines) is hidden from the demo path (P1) and deleted after G1 if still off-path (P2); other dead weight (Alembic beside create_all, second model registry, static Registry page, zero-caller modules) is P2.

## Blockers
- None. Keys, quota, billing and hosting are all in place (2026-10-25).
- RESOLVED by R24/R25 (Lane B is the golden path, live 10-25). Was RISK (P0, Lane A): Token Factory docs (checked 2026-10-20) say Meta fine-tunes deploy "only via Dedicated endpoints"; the serverless-deploy page is 404; custom weights on Dedicated endpoints are "beta, available on request"; Llama-3.3-70B left TF serverless 2026-08-31 (ml-engineering). Fallbacks in order: (a) /v0/models still works → as planned; (b) adapter download IS documented (checkpoint `result_files` + GET /v1/files/<id>/content, per /post-training/how-to-fine-tune; corrected 2026-10-21) → merge + GGUF on a Nebius CPU VM via llama.cpp (no GPU quota) or vLLM + LoRA on an AI Cloud Serverless Endpoint (needs quota) — untested whether the files load as PEFT; (c) Dedicated-endpoint custom-weights beta via Nebius Support; (d) Lane B serves the tuned model.

## Human actions
- [x] Token Factory key → .env NEBIUS_API_KEY (DONE); redeem $25 promo (nebius.com/promo-code, NEBIUS-DEVPOST-GLOBAL26); join the Builders Program (dev.nebius.com/builders) for +$25 TF and +$25 Tavily
- [x] Tavily key → .env TAVILY_API_KEY — DONE 10-24
- [-] DROPPED (R24; Lane B live): ask Nebius (Discord / Token Factory Support): is per-token LoRA deploy (POST /v0/models) still available for Llama-3.1-8B fine-tunes, and can we join the custom-weights beta for Dedicated endpoints? GPU quota is now critical for both lanes
- [x] DONE 10-25: AI Cloud project + billing; quota request 1× H100 (gpu-h100-sxm), 1× L40S, 1 VM, 1 VPC — file today, post in the Nebius Discord; Object Storage bucket + service account
- [ ] GHCR packages public (owner bangadpurva → Purva) — optional now (plan B registry; the README builds images locally)
- [ ] Devpost team + draft project (Best Apps and Agents)
- [ ] vast.ai: two stopped instances from other projects (54041703 rec-l2-bench-2, 54062531 esci-bench-v2), stopped since 2026-10-03, still billing storage (~$0.20/h per the spike agent) — destroy them? Hari's call; agents leave them alone
- [ ] DECISION: disclose in the README/Devpost that the build used AI coding agents? (Hari's call)
- [ ] Before submission: GitHub's default branch is `main` (pre-hackathon code) — set it to NebiusHackathon, or link the branch explicitly in Devpost (repo admin: Purva)
- [x] DECISION: golden-run topic = the Nebius docs specialist on NVIDIA Nemotron Nano 8B (R25, Hari) — DONE: live golden run d20d30f3, 2026-10-25
- [ ] Before the repo goes public (G3): gitleaks clean over all refs — DONE 2026-10-22 (.gitleaksignore, 11 triaged false positives; no .env secret in history); keys rotated; docs/Jira.csv reviewed for personal data (Hari)

## Tooling (installed skills/plugins/MCP, with install command)
- Nebius MCP (user scope): `claude mcp add --env SAFE_MODE=true --transport stdio --scope user nebius -- uvx --refresh-package nebius-mcp-server --with "pydantic<2.12" "nebius-mcp-server@git+https://github.com/nebius/mcp-server@main"` (the pydantic pin works around an upstream dependency clash); Nebius CLI 0.12.294 in ~/.nebius/bin; Hostinger Connector plugin (DNS only)
- python 3.12.13 venv (`uv venv --python 3.12 .venv`; `uv pip install -r requirements-dev.txt -r apps/api/requirements.txt pyyaml boto3 redis huggingface_hub ruff`)
- uv 0.11.12 · node 26.5 · pnpm 11.0.9 · docker 28.1.1 (Docker Desktop; colima not needed) · gh 2.88.1 (cannot see this repo; use git) · jq 1.7.1 · tmux 3.6a · make 3.81
- ruff 0.17.1 (`uv tool install ruff`) · gitleaks 8.30.1 (`brew install gitleaks`)
- Playwright MCP (`claude mcp add -s project playwright -- npx @playwright/mcp@latest`, in .mcp.json)
- Plugins: superpowers 6.3.0, ponytail, episodic-memory (already installed) · nebius CLI: deferred to G2
- jsonschema in the shared venv (data-w2; also pinned in requirements-dev.txt) · images to rebuild after data-w2 merges: orchapod/synth-distilabel:dev (5 months stale), orchapod/web-research:dev (new), orchapod/data-prep:dev
## Spend to date (per day, per key)
- 2026-10-25: ≈ $3.80 runs on the hosted stack (D8 rehearsal 0ee1e20a $1.5811 added at 08:59Z);
  earlier the same day ≈ $2.20 (golden run #1 fa20d166 $0.5842; golden run #2 d20d30f3 $1.6100; first hosted run eeeeb9ff $0.0058), plus the hosting VM and bucket billing hourly. No Jobs or Endpoints left (checked 08:12Z).
- 2026-10-20: $1.29 (vast.ai A100 SXM4 80 GB at $1.2485/h, 48 min, spike 4; instance destroyed)
- 2026-10-24: ≈ $0.11 (Tavily 6 credits $0.048 spike 3; live run #4 $0.0653)
- 2026-10-22: ≈ $0.16 Token Factory (spike 1 ≤ $0.03 fine-tune of 50 rows; spike 2 $0.0055; live runs $0.1007 + $0.0034 + $0.0175; key validation $0)
## Golden path status (last real run: id, date, cost, result)
- 2026-10-25T19:06Z: LIVE EXPERIMENT PASS, the CPU-variant shape on multi-state real-estate compliance. Run ca9838b7: 50.7 min, $1.35; H100 LoRA → q4_k_m GGUF + GGUF LoRA on CPU → Ultra 11/19/0 (0.68). Caveats in LOG; README/Devpost updated (b3eb12b).
- 2026-10-25T08:07Z: integration on 0865c31 (wave 6): make check E2E=1 GREEN (4 PASS); ui-smoke 4/5. The golden-path compare step regressed → frontend-w8b.
- 2026-10-25T06:53Z: scripts/golden-run.json is now the live golden run d20d30f3 (`make demo` seeds it; the hosted DB already has it).
- 2026-10-25T06:42Z: LIVE GOLDEN RUN PASS on the hosted stack — run d20d30f3: 24.2 min, $1.61 (est $2.66): Tavily → Super grounded synth (300 rows) → Unsloth LoRA of Nemotron Nano 8B on an H100 Job (loss 7.75→1.68) → vLLM base+LoRA on one L40S endpoint → Ultra judge: 7 W / 22 T / 1 L, win rate 0.6, consistency 0.73.
- 2026-10-24T16:08Z: LIVE golden-path data half PASS — run bf0ddb21 (Super's plan nebius-docs-grounded-qa: Tavily research → grounded synth → prep), 154 s, $0.0653 total, 300 grounded rows. The GPU half (unsloth-train → vllm-serve → judge-eval) waits on the nebius CLI login + quota + hosting.
- 2026-10-22T07:58Z: STUB golden path = template 4 (R25) green: e2e_agent golden path PASS (run 298cf7be, full plan) + ui-smoke golden test (template 4 card, reduced plan) on 3b7bf07.
- 2026-10-22T07:34Z: LIVE intent #3 through the Agent API PASS — run 59786797 (Super's plan quantize-math-expert; CPU quantize; Nemotron 3 Ultra judged live), 255 s, $0.0175 total. The earlier attempt cf49d0f1 failed on a missing HF config ($0.0034) → data-prep fix 782be76.
- 2026-10-22T07:01Z: LIVE intent #2 through the Agent API PASS — run 84e57f84 (Super's plan movie-interactions-synthetic: synth → prep), 446 s, $0.0966 run + $0.0041 planner/reporter = $0.1007, 928 rows, Super's report. First live run.
- Earlier (10-21/10-22): STUB G1 green (e2e_agent 3/3, ui-smoke 5/5); `make check` baseline 519 passed at 3d250c5; gitleaks clean at bootstrap.
