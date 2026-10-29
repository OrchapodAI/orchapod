# Changelog

Dated, user-facing changes made during the Nebius × NVIDIA hackathon submission period (Aug 26 – Oct 30, 2026). Orchapod's first commit is May 4, 2026 (367c605); this file becomes the Devpost "what changed" write-up.

## 2026-10-29
- The code is public at https://github.com/OrchapodAI/orchapod (MIT), with its full history; the README's setup clones it from there.

## 2026-10-27
- The canvas's cost check before a run lists only the steps that rent a GPU, at the GPU they rent: vllm-serve's L40S at $1.55 an hour. Before, every step showed an H100 at $4.50, and a run with no GPU step still asked for a confirmation.
- A plan that fine-tunes, quantizes and judges on CPU is checked before it runs: the tuned model is compared with the same 4-bit base. Before, the planner could pick the 16 GB full-precision base, which does not fit the CPU eval, or pair the LoRA with an endpoint, and such a run failed at its last step.
- Grounded synthetic data keeps only answers whose figures appear in their source passage. On a live finance run, about one row in ten stated a number its page did not hold (four different net incomes for one bank, from teaser pages). It also reads the whole corpus: before, three pages of menus or cookie text in a row ended it at half the corpus.

## 2026-10-25
- The golden path ran live, end to end on Nebius, from the hosted demo (app.orchapod.dev): Tavily research on the Nebius docs, 300 grounded Q&A pairs from Nemotron 3 Super, a LoRA fine-tune of NVIDIA Nemotron Nano 8B on an H100 Serverless Job, base and tuned served from one L40S Serverless Endpoint, and Nemotron 3 Ultra judging base against tuned: 7 wins, 22 ties, 1 loss on 30 questions. 24 minutes, $1.61.
- The hosted demo is live at app.orchapod.dev and api.orchapod.dev (a Nebius VM, Object Storage, HTTPS).
- The training image no longer bundles the Mamba-2 kernels (they broke `import unsloth` on GPUs); the golden path's student never needed them.
- The golden path ran live a second time, typed as one sentence on the hosted /agent page: Super's live plan, then Run. 23.5 minutes, $1.58; Nemotron 3 Ultra: 7 wins, 20 ties, 3 losses on 30 questions. Both runs are on the hosted demo.
- Run pages keep every node's logs after the run, say where each step runs (a Nebius Job or Endpoint with its live state), color the run's workflow on the canvas, and show the Agent's report in a Report tab.
- The compare tab keeps the tab you picked while a run finishes. Before, the finished run's eval view could take it over mid-stream.
- The planner no longer adds a made-up "report" node: the Agent writes the report itself. Plan rationales are in plain words.
- On the public demo, a plan that needs rented GPUs comes back as planned, marked admin-only, with a link to its golden run, instead of being shrunk to fit a budget it can never fit. When the day's public budget is spent, the page says so and when it resets.
- A third live run, on real-estate compliance in five states, quantized the trained Nemotron Nano 8B and judged it on CPU, with no endpoint: Nemotron 3 Ultra gave 11 wins, 19 ties and 0 losses on 30 held-out questions from its own synthetic set. 51 minutes, $1.35.
- Smaller polish: the loss chart reads cleanly, finished runs say "ended", an expired endpoint's compare tab explains why, and "watch the golden run" links appear only where a golden run exists.

## 2026-10-24
- Live: the golden path's data half ran on real services. Tavily extracted 20 Nebius docs pages, Nemotron 3 Super wrote 300 grounded Q&A pairs from them (each with its source passage and URL), and data prep validated them: 154 s, $0.07 in all.
- Tavily spike: all 20 docs pages extract cleanly into 98 passages for 4 credits; an advanced search costs 2.

## 2026-10-22
- First live run: intent #2 through the Orchapod Agent on real Token Factory. Nemotron 3 Super planned it, synthetic data and data prep ran, and Super wrote the report (928 rows, 446 s, $0.10 in all).
- Nemotron 3 Super writes run reports in the background when a run ends (one call, 30 s, template fallback).
- The docs-specialist template trains NVIDIA Nemotron Nano 8B (Lane B) and serves base + LoRA from one L40S endpoint ($2.66 estimated); a CPU variant judges a GGUF + GGUF LoRA without an endpoint.
- Token Factory's per-token LoRA deploy is retired (410): tf-deploy is hidden; fine-tunes are served by vllm-serve.
- `make agent-e2e INTENT=… MAX_COST=…` runs one intent live with hard caps; stub mode runs GPU nodes locally at $0.
- Second live run: intent #3 (a 3.1 GB maths model quantized to 0.99 GB on CPU in 75 s; Nemotron 3 Ultra judged q4_k_m against f16 live: 1 win, 4 ties on 5 questions; $0.02). A first attempt showed that Super's live plan can omit a dataset config; data-prep now picks one.
- The golden path (template 4, Nemotron Nano docs specialist) runs end to end in stub mode, through the Agent API and from the web app's template card to the eval view and the compare playground.
- The web app's node palette shows only the nodes on the demo path, in golden-path order, with forms for training and serving; a report that never arrives is reported after 60 s.
- Node containers receive keys by name only, so no key appears on a command line.
- A fresh clone reaches green in under 7 minutes (warm caches). The local object store now uses a community MinIO build, because the official image can no longer be pulled anonymously.
- `make e2e API=https://api.<domain>` runs the live golden run against the hosted API with an admin token, a $3 cap and a two-hour limit, and prints the evidence: per-node times, costs and the endpoint's expiry.
- Web polish for first-time visitors: the plan card and the run view scroll into view, no empty "Coming soon" pages, the title is Orchapod, and the log panel no longer moves the page.
- Secret scan over every branch is clean; the README's setup steps match what a new user runs.

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
