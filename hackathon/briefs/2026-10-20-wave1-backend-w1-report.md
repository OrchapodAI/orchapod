# Report — backend-w1 (wave 1, 2026-10-20)

**Status: DONE_WITH_CONCERNS.** Everything in the brief works. The concerns are about merging: platform's prices.py and local_docker.py, and qa's conftest.py.

**Branch:** hack/backend-w1, based on 178d2e6 (`git merge-base --is-ancestor 178d2e6 HEAD` passes). Not pushed.

**Commits:**
- 58e5b3d feat(sdk): cost.add and cost_json at exit, write_metrics, output names, secret header, progress webhook
- 1a4d55b fix(sdk): a blank env value means the contract default
- 6f7f629 feat(executor): run state machine, cancel, retry, summary, startup sweep
- 0af5cec fix(sdk): upload small files with one PUT so cost_json survives interpreter exit
- 0c41757 fix(executor): startup sweep terminates pods after the API is serving

**Spend:** $0. There were no paid calls; everything ran on local Docker, MinIO, Redis and Postgres.

## Proof
- **`make check`** (venv active, in the worktree): exit 0. ruff reports "All checks passed!". pytest reports **181 passed, 55 warnings**, against a baseline of 153 passed and 58 warnings. The stub e2e is skipped because qa's script doesn't exist yet.
- **`python -m pytest tests -q 2>&1 | grep -c "never awaited"`** → **1**. It is the existing `_terminate_after_ttl` line, which qa's `no_bg_tasks` covers.
  - No test of mine patches `asyncio.create_task`. The deploy test stubs `launch` in one line.
- **New tests: 28.**
  - tests/sdk/test_sdk.py has 8.
  - tests/api/test_executor.py has 20.
- **Failing without the code:** I ran the 20 new API tests against a `git archive` copy of the code before the executor commit. All 20 failed: 11 failures, plus 9 setup errors because the old internal.py has no `INTERNAL_SECRET`.
- **Real-container e2e** (a throwaway harness in the scratchpad, not committed):
  - Setup:
    - The image is `orchapod/data-prep:dev` with my SDK layered on top, tagged `orchapod-e2e/data-prep:latest`.
    - The API ran on port 8011.
    - The bucket, image and database it used were removed afterwards.
    - The harness swaps in the contract's `docker stop -t 30` terminate, which ships in platform's branch.
  - SQLite run, using the random secret (ORCHAPOD_INTERNAL_SECRET unset):
    - **ok:** `succeeded`. Run cost is 0.01, rolled up from cost_json. The artifacts are cost_json, dataset and metrics_json. `GET /artifacts/{id}/download` → 307 to the MinIO URL, and the content was verified.
    - **fail:** `exit 1: RuntimeError: boom`. The cost is still 0.01.
    - **cancel:** `cancelled` in 0.3 s, and the node error is `cancelled`. The node's `finally` ran on SIGTERM (its `cleanup` artifact arrived), and cost_json was written at exit.
  - Postgres run (a throwaway database in the compose Postgres):
    - The ok run succeeded.
    - I then killed the API (`kill -9`) while a node was running and restarted it. The startup sweep took 2.0 s. The run is `failed` with "control plane restarted". The container was SIGTERMed, its `cleanup` and `cost_json` reached the live API, and no containers are left.

## What was built
**Node SDK** (packages/sdk-py/orchapod):
- `cost.add(provider, model, in_tokens=0, out_tokens=0, usd=None, calls=1, **extra)`:
  - It aggregates per (provider, model).
  - With `usd=None` it prices the call from `PRICES`, using the shape agreed with platform-w1:
    - `token_factory`: model → in/out, $ per 1M tokens.
    - `token_factory_finetune`: model → $ per trained token.
    - `tavily`: credit.
    - `nebius_serverless`: platform → $ per GPU-hour.
  - A missing price raises LookupError, so unpriced calls fail closed (R5).
  - `BudgetExceeded` is raised once spend passes ORCHAPOD_MAX_COST_USD.
  - `prices.py` is an **empty stub**; platform's version wins at merge.
- `io.read_inputs()` arms the exit hooks:
  - cost_json (kind metrics, metadata `{"usd"}`) is written at a normal exit, at an uncaught exception (also logged as ERROR) and at SIGTERM, which is raised as `SystemExit(143)` so `finally` blocks run.
  - The hooks are armed in read_inputs, not at import, so pytest and spawned worker processes never write cost_json.
- `io.write_metrics(dict)`: `stub` is filled in from STUB, and the dict travels as metadata when it is ≤ 16 KB; otherwise the metadata is `{"truncated": true}`.
- Output names must match `[a-z][a-z0-9_]*` (fullmatch).
- The bucket and region come from env. A blank env value means the default.
- Output registration retries after 1, 2 and 4 s, then raises.
- `log.post()` sends X-Orchapod-Secret on every /internal call. `log.progress` → `/internal/progress`. Log and progress calls never raise.

**Executor and API** (apps/api):
- **NodeRun rows:** every row is created `pending` when the run starts. A UniqueConstraint covers (run_id, node_id).
- **Runtimes:** `cpu` and `api` nodes run on LocalDocker; `gpu` nodes go through pick_provider.
- **Image:** `${ORCHAPOD_IMAGE_PREFIX:-ghcr.io/bangadpurva}/<type>:latest`.
- **Refs:** an unresolved ref fails the node with `unresolved ref <ref>`. Resolved inputs and the pod are stored on the NodeRun.
- **Errors:** a failure emits `node_status failed {error}` and then `run_status`. The error strings are:
  - `exit <code>: <last ERROR line>`, where /internal/log stores the last ERROR line on NodeRun.error
  - `timeout after <n> s`, from ORCHAPOD_NODE_TIMEOUT_S (default 5400)
  - `cancelled`
  - `no <runtime> provider: …`
  - `provision failed: …`
  - `internal: …`
- **One launcher:** `launch()` registers the task for start, retry and /inference/deploy.
- **Cancel:** cancels the task. The executor terminates the pod (SIGTERM, 30 s grace) and records the node `failed` "cancelled" and the run `cancelled`. Events go out in that order, so the socket doesn't close first.
- **Retry:** `POST /runs/{id}/nodes/{node_id}/retry` → 202. It returns 404 for an unknown run or node. It returns 409 unless the run is failed or cancelled and the node is failed, and also while the old task is still stopping. It reuses the row, so `ORCHAPOD_RESUME_CHECKPOINT_URI` = the newest checkpoint.
- **Summary:** `GET /runs/{id}/summary` returns the contract's shape:
  - Nodes come in DAG order.
  - Per-node usd is the sum of the node's cost_json artifacts.
  - `download_url` is `/artifacts/{id}/download`.
  - `GET /artifacts/{id}/download` → 307 to a presigned URL that lasts 1 h.
- **Startup sweep:** orphaned runs → `failed`. The running node (or else the first unfinished one) gets "control plane restarted". Its pod is terminated in the background once the API is serving. A workflow that no longer compiles can't block startup.
- **`_build_env`:** forwards exactly the contract's Config list. ANTHROPIC, OPENAI and CLOUDFLARE keys are dropped. It adds:
  - `ORCHAPOD_MAX_COST_USD` = min(run budget left, UTC-day budget left).
  - `ORCHAPOD_INTERNAL_SECRET`. Per R2, it is random when unset or blank, and /internal/* always checks it.
- **Cost roll-up:** cost_json adds to Run.cost_usd and emits `run_cost`.
- **Removed:** `/internal/node-complete`, the debug log lines and the vllm-serve special case.
- **Other:** `models.utcnow()` replaces the deprecated `datetime.utcnow()`. storage.py takes its region from `ORCHAPOD_R2_REGION`.
- **Docs:** docs/NODE_CONTRACT.md has the new env table, the URI and name rule, and the cost/metrics/exit, cancel/timeout and retry rules.

## Found and fixed by the real-container runs
These were not caught by the unit tests.
1. **cost_json never arrived from a real container.** boto3's `upload_file` runs on an s3transfer thread pool, and at atexit Python refuses new futures ("cannot schedule new futures after interpreter shutdown").
   - Fix: files under 8 MiB go up with one `put_object`; larger files keep `upload_file`.
   - The exit test's fake S3 now uses a thread pool for `upload_file`, so it fails without the fix.
2. **The startup sweep awaited `docker stop` before the API was serving.** The SIGTERMed node could not register its last outputs, and the SDK's retries held startup for 16 s.
   - Fix: terminations run as background tasks after the DB update.

## Not done / deferred
- **`/internal/ttl` with `endpoint_id`, `endpoints.delete` at expiry, and the sweep of expired endpoints.** These need platform's NebiusServerless client, which isn't in wave 1. Today's `_terminate_after_ttl`, the vast.ai version, is unchanged.
- **Budget guard (wave 2, per the brief):**
  - 402 and 503 on start and retry, the node-boundary checks, the kill switch, the control-plane ledger and the anon scale are not done.
  - Only `ORCHAPOD_MAX_COST_USD` and the SDK's `BudgetExceeded` exist now.
- **`ORCHAPOD_PREVIOUS_OUTPUTS` is not forwarded.** It has no definition and no consumer (see open questions).
- **The legacy vllm-serve** (vast.ai, which blocks on vLLM) now ends at the 5400 s timeout. ml's wave-2 rewrite exits after /internal/ttl.

## Merge notes
- **prices.py** is an add/add conflict with platform-w1: keep platform's file.
- **local_docker.py** (platform) must land for local dev:
  - The image resolution `orchapod/<type>:dev` is needed because my image ref is now `ghcr.io/bangadpurva/...`.
  - `docker stop -t 30` is needed; otherwise cancel kills with no SIGTERM grace.
- **tests/api/conftest.py:** I changed one block. The `client` sends `X-Orchapod-Secret` by default, which /internal tests need now that /internal/* is never open. qa-w1 edits the same file.
- **tests/containers/test_unsloth_train.py** replaces `sys.modules["orchapod*"]` at import and never restores them. tests/sdk works around this with a fresh-import fixture; worth a qa or ml fix.
- **vllm-serve's direct `POST /internal/ttl`** sends no secret, so it now gets 403. ml's rewrite should call `orchapod.log.post("/internal/ttl", {...})`.
- **The compose Postgres `orchapod` database has no tables yet**, so the unique constraint is created on first start. The Alembic migration was not updated, because create_all is what runs.

## Proposed DECISIONs
- **Set ORCHAPOD_INTERNAL_SECRET explicitly** (`openssl rand -hex 32`) in every hosted deployment, not only multi-worker ones. After a restart, a random secret changes, and in-flight containers' final cost_json posts get 403. The Postgres e2e used a fixed secret, and they landed.
- **Cancel waits for the executor**, up to 60 s, so it returns the final `cancelled` RunOut and node events precede the terminal `run_status`.
- **The summary's `download_url` is the stable `/artifacts/{id}/download`**, not a presigned URL, because the agent report caches it in the DB and a presigned URL would expire after 1 h.

## Open questions
1. **`ORCHAPOD_PREVIOUS_OUTPUTS`** (Config: "backend's") has no definition anywhere, and retry already forwards `ORCHAPOD_RESUME_CHECKPOINT_URI`. Define it or drop it from the contract?
2. **The `api` runtime rows** (tf-finetune, tf-deploy, judge-eval, vllm-serve) arrive with ml's NODE_REGISTRY blocks in wave 2. The executor supports them now, and a test covers it by patching the registry.
