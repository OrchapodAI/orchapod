# ml-w2 report: wave 2 (2026-10-21)

Branch `hack/ml-w2`, worktree `.claude/worktrees/ml-w2`. Base check: `git merge-base --is-ancestor c75c119 HEAD` passes (branched at f592fd5). Status: **DONE**. Spend: **$0**. Everything ran in STUB mode or against local fakes, I rented no GPU, and I sent no Token Factory key anywhere.

## Commits (not pushed)
| SHA | What |
| --- | --- |
| 717650b | test(containers): unsloth-train fakes scoped to that file's tests; test_dockerfiles.py minors |
| 1b29608 | feat(tf-finetune): the node, its registry block, Dockerfile, CI matrix line, WORKFLOW_SPEC line, test fixtures |
| 4b96cff | feat(tf-deploy): the node, its registry block, Dockerfile, CI matrix line, WORKFLOW_SPEC line |
| 810debe | fix(tf-finetune): `poll` updates the job in place, so `finally` sees its last status (found in self-review) |

## Task 1: tf-finetune and tf-deploy (contracts "ML nodes", runtime `api`)

### tf-finetune (`containers/tf-finetune/run.py`, 136 lines)
- **Inputs** (as in the contract): `model` (meta-llama/Llama-3.1-8B-Instruct), `train_data`, `eval_data`, `n_epochs` (2), `hyperparameters` ({}), `timeout_min` (60).
  - `eval_data` that is "", or a file that is empty or whitespace only, means no validation file.
  - Train and eval are uploaded as `train.jsonl` and `eval.jsonl`, because the artifact names have no extension and Token Factory may check it.
- **Job creation**: `fine_tuning.create(model, train, val, {"lora": true, "n_epochs": n} | hyperparameters, suffix="<run_id[:8]>-<node_id>")`.
  - If create fails with kind `server` (a 5xx or read timeout, so the job may have started), the node calls `fine_tuning.list()` and adopts the unfinished job that carries our suffix; otherwise it fails. Create is never re-sent.
  - Before anything is sent, the node compares the estimate with `ORCHAPOD_MAX_COST_USD`. The estimate is (train bytes / 4) × epochs × the PRICES fine-tune rate, marked with a `ponytail:` comment.
- **Polling**: `fine_tuning.get` every 15 s, sending `trained_steps`/`total_steps` to `log.progress(..., extra={"phase": status})`. New job events go to the log once each, in time order.
  - A `server`/`rate_limit` error after the client's own retries waits for the next poll instead of killing a paid job.
  - Past `timeout_min` the node exits 1 with "timeout: …" and the job is cancelled.
- **Outputs on success**: the checkpoint is `best_checkpoint` (lowest valid_loss, else the last).
  - `job` is the 8-key JSON from the contract, with the same dict in metadata, kind `metrics`.
  - `lora_adapter` is a directory built from the checkpoint's `result_files` (filename from `files.get`, reduced to its basename so a remote name cannot leave the directory), kind `model`, metadata `{format: peft, base_model}`.
  - `metrics_json` is `job` plus `loss_curve` (one row per checkpoint, by `step_number`) and `wall_s`.
- **Failure and cancel**: a `failed` or `cancelled` job exits 1 with `error.message`.
  - `finally` cancels an unfinished job on failure, timeout or SIGTERM. If the cancel itself fails, it logs an ERROR saying the job may still bill.
  - The node then bills `trained_tokens` (from the cancel reply, if any) via `cost.add("token_factory", model, trained_tokens=…)`.

### tf-deploy (`containers/tf-deploy/run.py`, 84 lines)
- **Input**: `job` may be tf-finetune's `job` r2 URI, the same object inline, or a JSON string. Anything else (an unresolved `${{ }}`, a list, missing keys) exits 1 before any call, with a readable line. `name` defaults to `orchapod-<run_id[:8]>`.
- **Deploy and wait**: `lora.deploy(name, base, "<job_id>:<checkpoint_id>")`, then the node polls `lora.status(<returned id>)` every 15 s with `log.progress` for up to 15 min.
- **Proof and output**: one `chat(..., max_tokens=16, base_model=base)` proves the model. `model_ref` is `{base_url: tf.base_url, model: <returned id>, api_key_env: NEBIUS_API_KEY, base_model}`, kind `model`; its metadata adds `proof`. `metrics_json` is `{model, base_model, source, wait_s}`.
- **No per-token LoRA**: `ProviderError` kind `unsupported` exits 1 with `str(e) + " — serve it with vllm-serve + lora_adapter"` and deletes nothing.
- **Other failures**: status `error` or `deleted`, the 15-min cap, a failed proof, any other ProviderError, or SIGTERM delete the deployment it created. On success the deployment stays up, because idle costs nothing.

### Schema, images, CI, docs
- `packages/workflow_schema/models.py` (R3):
  - `NodeType.TF_FINETUNE` sits under Training and `TF_DEPLOY` under Post-training.
  - One block at the end of the file holds `TFFinetuneInputs/Outputs`, `TFDeployInputs/Outputs` and both `NODE_REGISTRY[...] = {..., "runtime": "api"}` rows.
- Both Dockerfiles use `python:3.12-slim` with `boto3==1.35.71 httpx==0.28.0` (the API's pins), `COPY packages/sdk-py/orchapod`, `COPY packages/providers` and their own run.py. `.github/workflows/ci.yml` gains the matrix lines `tf-finetune` and `tf-deploy`; the matrix equals the set of `containers/*/Dockerfile` (qa-w1's `test_ci_builds_every_container` rule, checked in Python).
- The doc lines are the `tf-finetune` and `tf-deploy` sections in `docs/WORKFLOW_SPEC.md`: inputs, outputs, wiring, and what to do on the vllm-serve fallback.

### Proof
- `make check` gives **330 passed**, 66 warnings (baseline 294 passed, 66 warnings); ruff is clean. The e2e step SKIPs (qa's `scripts/e2e_demo.py` is not written yet).
- **Unit tests**: tests/containers/test_tf_finetune.py has 14 and test_tf_deploy.py has 16. They run against a fake Token Factory (`tf_routes`: real `TokenFactory` on `httpx.MockTransport`) and a fake clock (`clock`), both in tests/containers/conftest.py.
- **Mutation check**: I broke each guard by hand and every mutant fails at least one test. The guards were: cancel in finally, path sanitising, lost-create recovery, estimate guard, transient-poll tolerance, event dedupe, empty-eval handling, adopting only an unfinished job, timeout, lora flag, fine-tune billing, delete in finally, unsupported mapping, the 15-min cap, prompt failure on `error`, job validation, 16-token proof, base_model in the ref, and the name input. Two tests were tightened so their mutants fail fast instead of hanging or passing.
- **Images**: `docker build -t orchapod/tf-{finetune,deploy}:dev -f containers/<node>/Dockerfile .` builds both (269 MB). `/app/run.py` in each image is byte-identical to HEAD; both `:dev` images are left on this Mac for the Orchestrator's e2e.
- **Real API, executor and LocalDocker, STUB=1**: this branch's API ran on :8012 with a scratch SQLite and the compose MinIO. Workflow `finetune (tf-finetune) → deploy (tf-deploy, job: ${{ nodes.finetune.outputs.job }})`:
  ```
  run ee035f37-3819-41e9-bfdd-13338c579f7a succeeded in 4 s, cost_usd=0.0, error=None
    node finetune  tf-finetune  succeeded  usd=0.0 error=None
    node deploy    tf-deploy    succeeded  usd=0.0 error=None
    artifact finetune/job  metrics  {"job_id": "ftjob-stub-0b77f6b4", ..., "checkpoint_id": "ftckpt-stub-2bc2a8cc-2", ...}
    artifact finetune/lora_adapter  model  {"format": "peft", "base_model": "meta-llama/Llama-3.1-8B-Instruct"}
    artifact deploy/model_ref  model  {"base_url": "https://api.tokenfactory.nebius.com/v1", "model": "orchapod-ee035f37", "api_key_env": "NEBIUS_API_KEY", ...}
    deploy resolved inputs: {'job': 'r2://orchapod-artifacts/runs/ee035f37-.../finetune/job'}
  ```
- **Real SIGTERM chain**:
  - Setup: the tf-finetune container ran against a local fake Token Factory whose job never finishes (`NEBIUS_BASE_URL=http://host.docker.internal:8099/v1`). A test-only `prices.py` was mounted with a dummy Llama fine-tune rate, because R5 refuses unpriced fine-tunes.
  - Action: `docker stop -t 30`, issued mid-poll.
  - Result: exit **143** at once; log `[WARN] cancelled Token Factory job ftjob-fake`.
  - The fake server saw `POST /v1/files`, `POST /v1/fine_tuning/jobs`, `GET …/ftjob-fake`, `GET …/events`, then **`POST …/ftjob-fake/cancel`**.
  - cost_json: `{"usd": 0.00015, "items": [{"provider": "token_factory", ..., "trained_tokens": 1500}]}`, which is the cancel reply's trained tokens.
- gitleaks over `f592fd5..HEAD`: no leaks.

## Task 2: test leak and test_dockerfiles minors
- `tests/containers/test_unsloth_train.py` now builds its fakes without touching `sys.modules`. It loads run.py inside `pytest.MonkeyPatch.context()`, and an autouse fixture sets the fakes back for each test with `monkeypatch.setitem`.
  - New test `test_loading_run_py_leaves_sys_modules_as_it_was` fails on the old code and passes now.
- `tests/containers/test_dockerfiles.py` gets the four deferred minors:
  - the continuation regex is now `\\[ \t]*\n`, with a new test that failed on the old regex;
  - `assert DOCKERFILES`;
  - a one-line docstring without the LocalDocker claim;
  - `any(ROOT.glob(s))` in place of `glob.glob`.
- **The tests/providers/conftest.py workaround can go (platform removes it, and its `import sys` with it).** Evidence, with the workaround deleted locally:
  - Full suite: 295 passed.
  - In the order that exposes the leak (`tests/containers/test_unsloth_train.py tests/providers tests/sdk`), the old test file gives **2 collection errors** and the new one gives **130 passed**.
  - (Running `tests/containers` first hides the leak, because data-prep's tests import the real `orchapod.prices` before the fakes go in.)
- The same stale reason sits in backend's `tests/sdk/test_sdk.py` `sdk` fixture ("test_unsloth_train.py leaves fakes in sys.modules"). The fixture still works, but its comment and re-import are no longer needed.

## Open questions and items for the Orchestrator
1. **DECISION to record**: a best checkpoint with no `result_files` makes tf-finetune warn and write an **empty** `lora_adapter` instead of failing. The `job` output stays usable by tf-deploy, which needs only job_id and checkpoint_id. vllm-serve cannot use an empty adapter. The cost if wrong is a confusing downstream vllm-serve failure.
2. **Spike 1 must confirm** (each assumption is in code, and failure is explicit):
   - TF job objects carry `suffix`. If they don't, the lost-create lookup finds nothing and the node fails as before.
   - `result_files` are file ids whose `files.get` has `filename`.
   - Whether TF bills trained tokens for a cancelled job, and whether the cancel reply carries `trained_tokens`.
   - `lora.status`/`lora.delete` take the id `lora.deploy` returned, not the requested name. This follows TF's docs and platform's recorded test; the contract text says "lora.status(name)".
   - The fine-tune price per trained token for Llama-3.1-8B and its chat price. Until PRICES has them, a non-STUB tf-finetune is refused at create and tf-deploy's proving chat is refused (R5, by design).
3. **SPEND SAFETY, related to the open platform-w2 item**: `ResourceSpec.provider_pref` in packages/workflow_schema/models.py still defaults to `["nebius", "vastai"]`, and the executor builds `ResourceSpec()` when a node has no `resources`. So fixing only provider_selector.py:74 leaves vast.ai as the fallback for every gpu node. The contract says `["nebius"]`. I did not change it, because it is not my block.
4. **Merge notes** (all mechanical):
   - `models.py`: my block is appended at the end; data-w2 will likely append too.
   - `ci.yml`: two matrix lines after synth-distilabel; qa-w1 edits the tags block.
   - `tests/containers/conftest.py`: two fixtures appended.
   - `docs/WORKFLOW_SPEC.md`: two sections after vllm-serve.
5. The NODE_REGISTRY rows carry no typical cost or time. If backend-w2's planner adds a key for that, tf-finetune costs trained tokens × the spike-1 rate. tf-deploy costs about $0 (idle LoRA is free, plus one 16-token call) and waits minutes.
6. The default deploy `name` `orchapod-<run_id[:8]>` repeats within a run. Two tf-deploy nodes in one run, or a retry after a failed delete, would collide. I kept the contract default.

## Fix round 1 (Orchestrator review): d9c7d45, 160ba33
- **Important (spend leak), fixed in tf-finetune.** `sent = True` is set just before `fine_tuning.create`. In `finally`, when `sent and not job.get("id")`, the node runs `find(tf, suffix)` in its own try, then cancels through the usual path. `job.get("id")` is used everywhere; `job_id` is gone. A create reply without an id now fails with a readable line.
  - Test: `test_a_job_whose_create_reply_was_lost_is_found_by_suffix_and_cancelled` covers three cases: SIGTERM mid-POST (the route records the request, then raises `SystemExit(143)`), a non-JSON 2xx, and a reply without an id. Each asserts the cancel POST and the bill.
  - Real check: a fake Token Factory held the create reply, and `docker stop` hit mid-POST. Exit 143. The fake saw `GET …/jobs?limit=20` (the R19 lookup, nothing found), `POST /v1/files`, `POST /v1/fine_tuning/jobs`, `GET …/jobs?limit=20` (found by suffix `mlw2stub-midpost`), then **`POST …/ftjob-slow/cancel`**. cost_json billed 321 trained tokens.
- **Ruling R19 (idempotent retry).** Before fetching or uploading anything, `find(tf, suffix)` looks for this node's job in validating_files, queued, running or succeeded.
  - Running (or validating/queued): adopted, and polling resumes.
  - Succeeded: adopted, and the node goes straight to outputs. It is not billed again, because the attempt that saw it finish billed it.
  - Only otherwise does the node upload and create.
  - The lookup comes before the estimate, so a retry can adopt a succeeded job even when the budget left is below the estimate.
  - Tests: `test_retry_adopts_this_nodes_job_instead_of_paying_again[running-resumes-polling | succeeded-goes-to-outputs]`. A cancelled job with the same suffix is listed first and must be skipped.
  - **For the Orchestrator:** docs/contracts.md's tf-finetune flow still says "retry-node starts a new job"; R19 replaces that line. I left contracts.md to you.
- **Minors**
  - 2: done. The cancel reply's non-null fields are merged into the job, so `trained_tokens: null` or a missing key keeps the last poll's count. Tested as `test_timeout…[None-700]`.
  - 3: done. `contextlib.suppress(BudgetExceeded)` around `cost.add` in `finally`. Tested.
  - 4: done. Job events have their own `try/except Exception: log.warn`. Tested: events failing with 401 still give a succeeded node with no cancel. The "finished job is not cancelled" test now triggers on a checkpoints 401.
  - 5: done. `timeout_min` has `le=85`. Tested.
  - 6: done. tf-deploy fails an unpriced base before `lora.deploy` (skipped under STUB, since nothing is spent). Tested both ways.
  - 7: **skipped (optional).** Checkpoints usually come about once per epoch, so with the default 2 epochs the live chart would get about 2 points that `metrics.loss_curve` already carries, at the cost of one more GET per poll. Say so and I add it.
  - Ponytail: tf-deploy's nested try is folded into the outer `except` (only `lora.deploy` raises `unsupported`).
- **Mutation check:** each of the 11 new guards, broken one at a time, fails at least one test.
- **Gate:** `make check` gives **339 passed**, 66 warnings; ruff is clean on apps, packages and containers; gitleaks clean. Both `:dev` images are rebuilt and byte-identical to HEAD. The STUB end-to-end through this branch's API (:8012, scratch SQLite) passes again: run 780871a3 succeeded, tf-finetune → tf-deploy.
