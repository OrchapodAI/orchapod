# Changelog

Dated, user-facing changes made during the Nebius × NVIDIA hackathon submission period (Aug 26 – Oct 30, 2026). Orchapod's first commit is May 4, 2026 (367c605); this file becomes the Devpost "what changed" write-up.

## 2026-10-22
- First live run: intent #2 through the Orchapod Agent on real Token Factory. Nemotron 3 Super planned it, synthetic data and data prep ran, and Super wrote the report (928 rows, 446 s, $0.10 in all).
- Nemotron 3 Super writes run reports in the background when a run ends (one call, 30 s, template fallback).
- The docs-specialist template trains NVIDIA Nemotron Nano 8B (Lane B) and serves base + LoRA from one L40S endpoint ($2.66 estimated); a CPU variant judges a GGUF + GGUF LoRA without an endpoint.
- Token Factory's per-token LoRA deploy is retired (410): tf-deploy is hidden; fine-tunes are served by vllm-serve.
- `make agent-e2e INTENT=… MAX_COST=…` runs one intent live with hard caps; stub mode runs GPU nodes locally at $0.

## 2026-10-21
- Evaluation: Nemotron 3 Ultra judges base against tuned answers in both orders against a reference answer, reporting win rate, consistency and (for maths) exact match; scraped text is always fenced as untrusted input. Quantized models are served locally with llama.cpp; a llama.cpp bug that garbled f16 answers on Apple silicon is fixed.
- Intent #3 (quantize a small maths model): GGUF q4_k_m with an f16 baseline on CPU; both answered 50 GSM8K questions in about 18 minutes on a laptop, with exact-match scores within noise of each other.
- Compare playground: two models answer one prompt side by side, streamed; even a refused request records what it spent.
- Four one-click templates (real-estate compliance, movie-engagement data, maths quantization, a Nebius docs specialist), each with a reduced "Run it yourself" version that says whether it fits the public demo's spending cap.
- Data prep: an optional Nemotron 3.5 Lightning quality filter, and small runs always keep a test and an evaluation row.
- Model serving: the serve node creates a Nebius Serverless Endpoint that serves the base model and the fine-tuned adapter side by side; the GPU training container follows the recipe proven on the spike.
- Public-demo hardening: per-visitor rate limits, an origin allow-list, deep health checks, a kill switch, workflows with runs are read-only to visitors, GPU nodes are admin-only, secrets are dropped before anything is stored and never returned.
- Hosting files for one VM (Docker Compose, automatic HTTPS, nightly backups, a watchdog); not deployed yet.
- Web app: the evaluation view, a dataset card, error toasts, honest empty and loading states, a demo banner and a loss chart that also works for finished runs.
- Tests: the agent end to end passes for all three example intents in stub mode, a browser test covers the golden path from template to playground, and failure drills check the exact error a visitor sees.
- Paid GPU safety: every Nebius job and endpoint gets an expiry and is deleted when it expires, a create whose reply was lost is found by name and cleaned up, a job stops when it reaches its node's budget, and GPU time is billed even when a job is killed; the Nebius Serverless client for Jobs and Endpoints is built and tested offline, not yet run live.
- Visitors can cancel only the runs they started, and editing a workflow that already has runs saves a copy instead.
- Prompt-injection guard: text from the web reaches a model only inside fenced tags that disguised characters (zero-width, bidirectional, fullwidth, hidden tag characters) cannot close; one shared implementation for every node.

## 2026-10-20
- The Orchapod Agent API: one sentence in, a validated Nemotron plan with cost and time estimates out; plans run, are monitored and get a written report. Spend caps per run and per day, with reservations so parallel runs cannot overshoot.
- New nodes: Tavily web research; synthetic data grounded in scraped passages (fenced as untrusted text) or matching a JSON schema; Token Factory fine-tune and deploy with idempotent retry.
- Intent #2 (synthetic movie-engagement data) runs end to end in stub mode through the API, the executor and the containers in 4 seconds, with a downloadable 500-row dataset.

- One Token Factory client and one Tavily client (`packages/providers`): retries that never re-send a billable create, per-call dollar accounting from one price table, the rule that the Nebius key only goes to Token Factory, and a deterministic offline stub mode.
- Run engine: every node row exists from the start, retry a failed node and continue downstream, cancel with a 30-second grace that cleans up remote work, restart recovery, per-run cost roll-up and a run summary API.
- Node SDK: cost and metrics files written on any exit, progress events, signed calls to the control plane.
- Data prep: reads pipeline outputs directly, adds QA and structured formats, exact and near-duplicate removal, train/eval/test splits stratified by source URL.
- Every container builds from the repository root; the Claude fallback is gone from the evaluation container; GPU nodes default to Nebius and never fall back to another GPU provider.
- Web app: the Orchapod Agent page, forms for the new nodes, a run page with a live cost meter and node retry; nothing fake on screen.
- Lane B student model chosen by experiment: Llama-3.1-Nemotron-Nano-8B trained, merged and served on one GPU (Nemotron 3 Nano 30B-A3B also works on 80 GB GPUs).
- A README written for the judges, with drift tests.

- Repo hygiene: removed a committed SQLite database, compiled Python files and a stray worktree copy; one workflow-schema package instead of two.
- Hackathon build harness: operating manual, plan, state board and journal under `hackathon/`; project hooks and seven agent roles under `.claude/`; `make up`, `make check` and `make checkpoint` (the `e2e`, `agent-e2e` and `demo` targets are defined; their scripts are in progress).
- Quality gate: `make check` is green — ruff pinned to a minimal rule set with 30 lint fixes; CI runs lint and the 153 unit tests on every push.
- Interface contracts v1 (`docs/contracts.md`): node SDK, provider clients, config, data and ML nodes, run state machine, budget guard, events and the Orchapod Agent API; plus the agent's knowledge base (`docs/agent_knowledge.md`).

## 2026-10-02 – 2026-10-08 (Purva)
- Nebius × NVIDIA integration: Nebius Token Factory service and a Nebius provider.
- Synthetic-data pipeline with Nemotron 3 Super as the teacher model (merged from the data-engine branch).
- Token Factory model IDs verified against the live catalog.
- End-to-end executor fixes: database commits, NEBIUS_API_KEY forwarding, container SDK.
- Quick-start docs with Colima/Homebrew setup.
