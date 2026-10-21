# backend-w2 report — wave 2 (2026-10-21)

**Status:** DONE (all three brief items, the mid-wave commit-before-publish request, and both notes from the platform-w2 review).
**Branch:** `hack/backend-w2`, worktree `.claude/worktrees/backend-w2`, base c75c119 (checked with `git merge-base --is-ancestor`). Not pushed.
**Spend:** $0. No keys are set. Everything runs on STUB=1 or on Token Factory replies recorded through `httpx.MockTransport`.

## Commits (oldest first)
| SHA | What |
| --- | --- |
| 41a37c1 | fix(api): executor and run-control carry-overs from the backend-w1 re-review |
| c998e2f | feat(api): budget guard: run/day caps, kill switch, anonymous scale, day ledger |
| cd3cec1 | fix(api): commit before publishing any event that announces a DB change (orchestrator request) |
| 0975899 | feat(api): Orchapod Agent API on Nemotron: plan, run, report, templates; the Claude path is deleted |
| 9a2c173 | chore(api): create the bucket at start; the API image path has the SDK and the agent knowledge file |
| e38f31b | fix(api): an inline tf-deploy job with a non-string model can no longer crash review() |
| 29423aa | fix(api): the validator checks each gpu node's provider_pref; any unreadable TF reply is a 502 (platform-w2 review) |

## What was built
### 1. Orchapod Agent API (apps/api/agent/planner.py, apps/api/routes/agent.py, apps/api/agent/templates/*.json)
- **POST /agent/plan**
  - The model call: Nemotron 3 Super (`SUPER`) through `TokenFactory.chat`, with guided JSON (`{"rationale", "plan"}`), temperature 0, `thinking=False`, `max_tokens=4096` and `read_timeout=300`.
  - The prompt: every request reads docs/agent_knowledge.md fresh, plus a catalog built from the NODE_REGISTRY rows not marked `hidden`. Each catalog entry gives the inputs JSON Schema, outputs, runtime, and typical $ and minutes.
  - Repairs: validation errors go back to the model for up to 2 repairs.
  - Status codes: 422 for a blank intent or one over 2,000 chars; 503 for the kill switch or a missing `NEBIUS_API_KEY`; 402 when the day budget is gone (see DECISION 1); 502 for any exception from the TokenFactory client: a `ProviderError`, or a 2xx it cannot read (still a KeyError for some shapes).
  - STUB=1: returns the closest canonical template (word overlap with its intent and title) and makes no model call.
- **review()** (validation). Errors read `"<node_id>: <problem>"`, and the plan is checked for:
  - Shape: snake_case unique ids; visible types only; `needs` that exist; no cycles (through compile_dag).
  - Inputs: against inputs_schema; unknown inputs are errors.
  - Refs: each must be exactly one `${{ nodes.<id>.outputs.<name> }}`, name a node in `needs` and a real output, and sit at the top level only. Plans have no `inputs.X`.
  - agent_knowledge constraints: Token Factory fine-tune bases with no Nemotron; per-token LoRA only for Llama 3.1 8B (the base spike 1 tests); teacher and judge must be priced Nemotron models.
  - Inline ModelRefs may only pair `NEBIUS_API_KEY` with `$NEBIUS_BASE_URL`. Endpoint refs must come from a vllm-serve output.
  - gpu nodes need a configured provider from their effective `provider_pref` (plans carry no resources, so ResourceSpec's default, `["nebius"]` after platform-w2). A lone `VASTAI_API_KEY` no longer passes a plan the executor would refuse.
  - The estimate must fit the budget left.
- **estimate()**
  - Priced from `PRICES` by inputs: synth-distilabel (rows × teacher price, capped at `max_usd`), web-research (Tavily credits), judge-eval (two orders × rows × judge price) and vllm-serve (keep_alive × GPU-hour).
  - Every other node uses a typical (usd, minutes) from `TYPICAL`.
  - Warnings: tf-finetune has no fine-tune price yet (spike 1), and tf-deploy is unverified.
- **POST /agent/run**
  - Validates again: 503 kill switch, then 422 `{"detail", "errors"}`, then 402 when the estimate is over the budget left.
  - Then creates the Workflow (`yaml.safe_dump(plan)` plus graph_json, so it opens on the canvas), the Run (`provisioning_gpu`) and the `agent_run` row.
  - Launches with the caller's budget scale and returns 201 `{run_id, workflow_id, estimate}`.
- **GET /agent/runs/{id}/report**
  - Returns the `/runs/{id}/summary` fields plus `intent`, `estimate`, `ready` and `markdown`; 404 for runs the agent did not start.
  - On the first GET after a terminal status, Nemotron 3.5 Lightning writes the report, which is cached in `agent_run.report_md` (R8).
  - Fallback: STUB=1, the kill switch, an empty day budget or any exception from the call use the deterministic template instead.
  - A retry clears the cached report, so the run's next terminal status gets a fresh one.
- **GET /agent/templates:** the three canonical intents with `rationale` and a live `estimate`. They use the same intent strings as the /agent page's examples.
  - #1 web-research → synth grounded → data-prep 0.8/0.1 → tf-finetune Llama-3.2-3B → vllm-serve + lora_adapter → judge-eval: $1.72, ~57 min.
  - #2 synth structured (the contract's schema, 500 rows, max_usd 0.25, max_tokens 2500 per data-w2) → data-prep `structured`: $0.15, ~7 min. It fits the anonymous $0.30 run cap.
  - #3 hf-download Qwen2.5-Math-1.5B → quantize gguf q4_k_m + keep_f16 → data-prep gsm8k test[:50] qa → judge-eval exact_match, n_judge 20: $0.10, ~30 min.
- **/workflows/from-prompt** now uses `make_plan`, the same planner with the same status codes. It saves the draft if it compiles, else returns 422 with the planner's errors.
- **Removed:** `apps/api/agent/workflow_builder.py` (the Claude path) and `anthropic` from apps/api/requirements.txt. The image check below confirms `anthropic` is not installed.
- **NODE_REGISTRY:** `"hidden": True` on hf-import, file-upload, s3-import and auto-label-cleanlab (no container), and on distill-sft and lm-eval (off the demo path). A header comment lists the row keys.
- **Doc line:** docs/agent_knowledge.md "Node catalog" now says where the catalog and the typical costs come from.

### 2. Budget guard (apps/api/services/budget.py; tables `spend` and `agent_run`)
- **Scale (R7):** `scale()` is a FastAPI dependency: 1 when `X-Orchapod-Admin` equals `ORCHAPOD_ADMIN_TOKEN` (both stripped, compared with `secrets.compare_digest`), else `ORCHAPOD_ANON_SCALE` (default 0.1). A blank token counts as unset, so then everyone is anonymous.
- **Kill switch:** `kill_switch()` treats anything but blank or `0` as on, so it fails safe.
- **Caps:** `left(db, run, scale)` returns (budget left, the cap that binds `run|day`, that cap). Both caps are multiplied by the scale. Day spend = Run.cost_usd of the runs created today + the `spend` ledger.
- **Ledger (R6):** `control_plane(db, source, call)` runs one TokenFactory call in a worker thread. Its `on_usage` appends to a list (list.append is atomic, so it is thread-safe) and writes one `spend` row afterwards, also when the call failed after TF billed it. The planner and reporter use it; /compare (wave 3) should too.
- **Where the guard applies:**
  - start and retry: 503 kill switch, 402 when nothing is left.
  - /agent/run: 402 when the estimate is over the budget left.
  - /agent/plan: a plan error for the same, and 402 when the day budget is gone.
  - Every node boundary in the executor: fails the node with `kill switch` or `budget: <run|day> cap $<x> reached`.
  - `ORCHAPOD_MAX_COST_USD` is the budget left at that boundary.
- **Scale in the executor:** `executor.launch(run_id, scale)` passes the caller's scale to the executor (see DECISION 2).
- **At API start:** `ensure_bucket_exists` runs in the default executor, so it never delays startup. boto3 gets connect timeout 5 s and 2 attempts; presigning makes no network call, so it is unaffected.
- **API image:** `apps/api/Dockerfile.dev` sets `PYTHONPATH=/app:/app/packages/sdk-py` and copies `docs/agent_knowledge.md` to `/app/docs`. Without the path, `api.main` now fails to import, because budget.py imports the TF client, which imports `orchapod.prices`.

### 3. backend-w1 re-review carry-overs
- run_workflow's `try:` now covers loading the workflow, creating the rows, and the setup commit and broadcast. A failure there fails the run instead of leaving it in `provisioning_gpu`.
- `ORCHAPOD_NODE_TIMEOUT_S` is parsed before provision. A bad value used to leak a running container.
- Provisions and teardowns left behind by a cancel are tracked per run (`_inflight`). `executor.busy(run_id)` covers the executor task and those futures, and retry returns 409 while it is true.
- start and retry move the run with `UPDATE … WHERE status IN (…)` plus a rowcount check. Retry also resets the node with `WHERE status = 'failed'`, in the same transaction as the run move and the report reset.

### 4. Orchestrator request: commit before publish
- `/internal/artifact` used to publish `run_cost` and `artifact` before the session committed. It now commits first.
- The same fix applies to `/internal/log` (when an ERROR line sets the node error), `/internal/ttl`, cancel and the legacy `/inference/extend`. The executor already committed before broadcasting.
- The test (`test_events_fire_only_after_their_change_is_committed`) uses a file-backed SQLite and reads through a second connection the moment each event fires. Before the fix it saw `('run_cost', 'running', 0.0, [])`.

### 5. platform-w2 review notes (orchestrator)
- The validator tests each gpu node's effective `provider_pref` against `get_providers()`, not `bool(get_providers())`. Test: a configured provider that no plan prefers does not count. On the merged tree with only `VASTAI_API_KEY` set, a gpu node gets `no GPU provider in provider_pref ['nebius'] is configured (nebius needs NEBIUS_PROJECT_ID)`.
- The planner maps any exception from the TokenFactory client to 502. The reporter falls back to the template on any exception. Test: a 200 whose choice has no `message`.

## Proof
- `make check` on the branch (29423aa): `All checks passed!` · `322 passed, 1 skipped` · `SKIP stub e2e: scripts/e2e_demo.py not written yet (qa)` · exit 0.
  - The skipped test is `test_intent_2_runs_on_the_nodes_that_exist`, with reason "waits for data-w2's synth-distilabel `structured` template".
- **Trial merge** of NebiusHackathon @ be446ae (which now has platform-w2, frontend-w2 and qa's `no_bg_tasks`) and hack/data-w2 into this branch, then reset: both auto-merged, and `make check` gave `All checks passed!` · `408 passed`, 0 skipped. So intent #2's template validates against data-w2's real schema with no errors and no warnings, and the `hidden` flags merge cleanly in models.py.
- **Mutation checks** (each fix reverted by hand, the target test run, the file restored): 17 of 17 caught.
  - Carry-overs: busy → running_tasks; unconditional start; timeout parsed after provision.
  - Budget: ledger left out of spent_today; blank-token admin; scale not passed to the executor; node-boundary check off.
  - Events: commit removed.
  - Agent: no repairs; hidden ignored; any key/URL pair accepted; report not cached; retry keeps the report; Nemotron rule off.
  - Review notes: any provider counts; the planner catches only ProviderError; the reporter catches only ProviderError.
- **Live smoke**
  - Setup: uvicorn on :8017, STUB=1, a throwaway Postgres database `orchapod_bw2` in our compose server (dropped afterwards), trial merge with data-w2, and no containers launched.
  - Results:
    - `/health` ok.
    - Templates: `[('real-estate-compliance', 1.724, 56.5), ('movie-engagement', 0.15, 6.5), ('maths-quantize', 0.096, 30.3)]`.
    - STUB plan for intent #2: `errors=[]`.
    - Intent #3: `["quantize: unknown input 'keep_f16'", "evaluate: unknown node type 'judge-eval'"]`.
    - Anonymous /agent/run with ORCHAPOD_ANON_SCALE=0.0001: `402 {"detail":"run cap $0.0003: $0.00 left, the plan needs $0.15"}`.
    - Bad plan: `422 {"detail":"the plan has errors","errors":["a: unknown node type 'lm-eval'"]}`.
    - from-prompt: `movie-engagement-synthetic-data 2 nodes`.
    - Postgres tables: `agent_run artifact model noderun run spend workflow`.
    - Server log: no errors.
- **API image:** built from the worktree with `docker build -f apps/api/Dockerfile.dev .` (image removed after).
  - With the fix, inside the image: the routes are `['/agent/plan', '/agent/run', '/agent/runs/{run_id}/report', '/agent/templates']`; the knowledge file reads 3,960 chars; the three template slugs load; `anthropic importable: False`.
  - With `PYTHONPATH=/app` (the old setting): `ModuleNotFoundError: No module named 'orchapod'`.

## What does not work yet
- **Templates #1 and #3 do not validate until other nodes land.** /agent/run refuses them with a 422 that lists exactly what is missing.
  - judge-eval (wave 3).
  - vllm-serve's `lora_adapter` input and its `model_ref`/`base_model_ref` outputs (ml; the contract has them, the schema does not yet). vllm-serve is still `runtime: gpu` here, so it also needs a GPU provider.
  - quantize's `keep_f16`/`gguf_f16` (ml).
- **The live planner and reporter are unproven against Token Factory** (no key). Spike 3 should run one /agent/plan for real to check guided JSON with `strict: true`, `thinking=False` and an open `inputs: {"type": "object"}`.
- **A local real run of templates 1 and 2 fails at the data nodes until images are rebuilt** (from data-w2). `orchapod/synth-distilabel:dev` on this Mac is 5 months old, there is no `orchapod/web-research:dev`, and ghcr has no `web-research:latest` until CI pushes it. **Orchestrator action after merging data-w2:** rebuild with `docker build -t orchapod/<node>:dev -f containers/<node>/Dockerfile .`, or delete the stale `:dev` images.
- **Warnings:** on the branch, tests/api shows 116 warnings (83 before). The new ones are the same kinds: SQLModel's `session.execute` deprecation, which only the tests' SQLModel session emits; production uses SQLAlchemy's session. The merged tree shows 106 in total, because qa's fixture removes the never-awaited ones.

## Open questions
1. **The web app never sends `X-Orchapod-Admin`, so every UI caller is anonymous:** $0.30 per run and $1.50 per day at the default `ORCHAPOD_ANON_SCALE=0.1`.
   - Intent #1 ($1.72) therefore shows a budget error on the plan card, and Run stays disabled.
   - For the local demo: set `ORCHAPOD_ANON_SCALE=1` in .env, or have frontend send the header from a local setting (wave 3?).
2. **Contract lines the orchestrator owns** (I did not edit contracts.md):
   - /agent/plan can return 402.
   - GET /agent/templates items also carry `rationale`.
   - `ORCHAPOD_ADMIN_TOKEN` belongs on the "Budget" line of "Config" (it is in .env.example).

## DECISIONs for the orchestrator to record
1. **/agent/plan returns 402 when the day budget left is ≤ 0** (the contract lists 422/502/503). Otherwise the day cap cannot bound planner spend (R6). With budget left, an estimate over it is a plan error, as the contract says.
2. **The caller's budget scale is passed to `launch(run_id, scale)` and is not persisted.** The executor lives only in its process, and every start, retry or /agent/run is a request whose scale is known; a restart fails in-flight runs (sweep), and their retry is a new request. Node-boundary and in-node caps use the scale of whoever started or retried the run. The legacy /inference/deploy launches at scale 1.
3. **Hidden registry rows:** hf-import, file-upload, s3-import and auto-label-cleanlab (no container); distill-sft and lm-eval (off the demo path).
4. **Intent #1's template uses option 1 of the OPEN DECISION:** 3B served by vllm-serve with base and lora_adapter on one endpoint. `SERVERLESS_LORA_BASES` is the Llama 3.1 8B ids that spike 1 tests. After spike 1, moving to 8B + tf-deploy is a template edit.
5. **Intent #3's model is Qwen/Qwen2.5-Math-1.5B-Instruct** (≤ 2B, maths-trained) until ml's D4 shortlist.
6. **Retry clears `agent_run.report_md`,** so a retried agent run gets a fresh report.

## Coordination and merge notes
- **platform-w2** (already in NebiusHackathon): `read_timeout` is aligned. Its 650ce2e makes it a per-call keyword kept out of the body, matching the planner's call. The test spy also strips the keyword, which is harmless on either client version.
- **data-w2:**
  - Checked templates 1 and 2 against its nodes (they match).
  - Suggested `max_tokens` 800 and 2500; both applied.
  - Its branch auto-merges with mine (trial merge above).
- **ml-w2:** appends its tf-finetune/tf-deploy registry blocks at the end of models.py; my `hidden` flags sit inside existing rows. Its uncommitted blocks match the field names my templates and tests use (`model`, `train_data`, `eval_data`, `n_epochs`; `job`; outputs `job`, `lora_adapter`, `model_ref`).
- **qa (`no_bg_tasks`, already in NebiusHackathon):** no new test hand-patches `asyncio.create_task`; they monkeypatch `executor.launch`, as backend-w1's did. The trial merge with qa's conftest passes.
  - The `launched` fixture in tests/api/test_executor.py now forwards `(run_id, scale)`.
  - tests/api/test_budget.py imports fixtures from test_executor.py; if qa moves them into conftest.py, that import goes.
  - tests/api/conftest.py is untouched.
- **Schema:** no column was added to an existing table. `agent_run` and `spend` are new tables, so `create_all` creates them on existing dev databases with no migration.
- **Ponytail notes in code:**
  - `TYPICAL` costs are rough until spikes 1–3.
  - Two concurrent first report GETs may both call Lightning (< $0.001; both are in the ledger).
