# backend-w3 report — wave 3b (2026-10-21)

**Status:** DONE. Brief items 0–2 are done, and so is the orchestrator's mid-wave P0 (artifact-meta redaction, R10).
**Branch:** `hack/backend-w3`, worktree `.claude/worktrees/backend-w3`, base 10168de (`git merge-base --is-ancestor 1c0b746 HEAD` passes). Not pushed.
**Spend:** $0. No keys are set, so STUB=1 and httpx.MockTransport prove the code.

## Commits (oldest first)
| SHA | What |
| --- | --- |
| d129cd7 | test(api): tests use production's SQLAlchemy session (126 → 2 warnings); grants reset per test |
| 9c82811 | fix(api): a node's budget grant ends only when its container has exited |
| e117656 | feat(api): POST /compare streams two ModelRefs side by side over SSE |
| 8a3afbf | feat(sdk): a node's log lines are kept as its `logs` artifact at exit |
| 768bff8 | feat(agent): "Run it yourself" clones each template at reduced scale |
| ce4820f | fix(api): no token in artifact meta reaches the DB or the browser (R10, P0) |
| 7d62c1d | feat(demo): make demo seeds the golden run; --export turns a finished run into it |
| b7dbca6 | fix(api): /compare's done.usd is always a float (0.0 off Token Factory), or null |
| 140cb4f | fix(api): a /compare answer ends even when its spend cannot be written |

## What was built
### 0. backend-w2 re-review carry-overs
- **Grant lifetime** (`apps/api/executor/run_workflow.py`).
  - A node's budget grant is now released only once its container has exited.
  - After a double cancel, or a cancel during provision, the teardown stays in `_inflight` and keeps the grant. `_track`'s done-callback releases it when the last teardown finishes.
  - On a normal exit nothing changes, because the executor already awaits the teardown.
  - The two cancel tests now assert that the grant is held during the SIGTERM grace and while the container is still coming up, and released afterwards.
- **Several grants add up:** `test_grants_of_several_runs_add_up_to_the_day_cap`.
  - Setup: run cap $1, day cap $2.5, four concurrent runs.
  - Result: the grants are {1, 1, 0.5}, and one run fails `budget: day cap $2.5 reached`.
  - An autouse `no_grants` fixture in tests/api/conftest.py clears `budget._granted` around every test.
- **Known ceiling:** a `ponytail:` note on `budget.reserve()` records it. A node reserves its run's whole remaining budget, so an admin run in flight can leave anonymous callers nothing. The upgrade path is D6: per-node estimates, or a separate anonymous day budget. Not built (ruling: no admin runs on the hosted app).
- **Warnings: 126 → 2.**
  - Root cause: the tests used SQLModel's AsyncSession, which deprecates the `execute()` that production code calls on SQLAlchemy's session.
  - Fix: the tests now use production's session class, and 5 `db.exec(` calls in tests became `db.scalars(`.
  - The 2 left are third-party (starlette testclient, botocore).

### 1. POST /compare (`apps/api/routes/compare.py`)
- **Request.** `{"messages": [{role: system|user|assistant, content ≤ 8000}] (1–50), "refs": [ModelRef, ModelRef], "max_tokens": 1–2048 (512)}`. Both refs get temperature 0 and the same max_tokens. Extra ModelRef keys, such as tf-deploy's `proof`, are ignored.
- **Response.** SSE `data: {"i", "delta"}` …, then `{"i", "done": true, "usd": float}` for each ref.
  - A mid-stream failure ends that answer with `{"i", "done": true, "usd": null, "error": "the model call failed mid-stream; the API log has the cause"}`.
  - **Confirmed for the orchestrator's `error?` contract line** (test `test_a_failure_mid_stream_ends_that_answer_with_an_error`).
- **Pairing rule, server-side, before anything is sent:**
  - `NEBIUS_API_KEY` is used only when base_url equals `$NEBIUS_BASE_URL` (stripped, no trailing /).
  - `ORCHAPOD_ENDPOINT_TOKEN` is used only with an `endpoint` artifact registered through /internal/ttl. It may be given with or without `/v1`, must have a future `expires_at`, and must have no `deleted_at`.
  - Anything else gets 422 "refused ModelRef …": a foreign URL, `""` (an open proxy), another env var.
- **Refusals happen before the 200.** Both answers are started (the first chunk is read in worker threads) before the response begins, so failures are plain HTTP errors:
  - 422 for a request Token Factory rejects (`bad_request`: an unpriced model, an unknown model).
  - 502 for any other failure. The detail is fixed and the cause goes to the log.
  - 402 when the day budget is spent, at the caller's scale; 503 for the kill switch.
- **Spend.**
  - Each answer finishes in its own task (kept in `_streams`), so its spend reaches the day ledger (`spend.source = "compare"`) even if the client hangs up. A test calls the route and never reads the body.
  - A ledger write that fails is logged at ERROR, and the done event is still sent (fix 140cb4f; before it, the stream hung).
  - `budget.meter()` and `budget.record()` are now shared with `control_plane`.
- **Known ceilings (ponytail):**
  - When one ref fails before its first token, the other ref's started answer is closed unread. Token Factory bills those few tokens, but they are not in our ledger.
  - Each compare holds two worker threads while it streams. D6 rate limits bound this.

### 2. Golden-run fixture, logs, "Run it yourself"
- **`make demo` → `scripts/seed-golden-run.py`.** It seeds one finished run into `DATABASE_URL` + `ORCHAPOD_R2_*`, read the same way the API reads them.
  - Rows: the workflow (with its canvas graph), run, node runs, artifacts, models, and the agent run with its cached report.
  - Files: the text files the artifacts link to, each at most 1 MB: datasets, eval_summary with the verdicts, metrics, and every node's logs.
  - Seeding replaces the run by id and merges the workflow.
  - It keeps the run's timestamps, so an old run never counts toward today's budget.
  - It moves `r2://<fixture bucket>/` to `ORCHAPOD_R2_BUCKET`.
- **`--export RUN_ID`** writes a finished run back into the same file, with artifact meta redacted. It skips directories (lora_adapter) and binaries (GGUF): their rows show, but their downloads do not.
- **`scripts/golden-run.json` (89 KB) is a placeholder STUB run** of the real-estate template (run `5b45f389-2ba5-46da-8b45-df7c9ddf3c18`; every metric says `stub: true`).
  - How it was made: an in-process API on a scratch SQLite DB and the compose MinIO, with web-research, synth-distilabel, data-prep and tf-finetune run for real as host processes with STUB=1. The API wrote the report (STUB template). The file is the output of export().
  - vllm-serve's lora path and judge-eval are not merged, so they ran as STUB stand-ins written to the contract. The judge-eval stand-in used the STUB Token Factory client, whose judge picks "A" in both orders.
  - So the eval is n=2, 2 ties, win_rate 0.5, consistency 0.
  - The generator was throwaway and is not committed. The bucket keys it wrote were deleted.
  - ml-w3's real judge-eval writes the same `eval_summary` and Verdict keys (checked on `hack/ml-w3`).
  - **TODO(D8): `--export` the real golden run, commit the file, then run `make demo` on the hosted app.**
- **Logs persist** (`packages/sdk-py`).
  - At exit, after cost_json, the SDK writes `logs` (kind `log`): every line it logged, as JSONL `{ts, level, message}`. A finished run, and the fixture, therefore keep their logs, since the live WebSocket stream has no replay.
  - A failed `logs` registration is logged as a WARN, so the node's last ERROR line is still its error.
  - The agent report lists results, not log files.
  - Doc line: docs/NODE_CONTRACT.md.
  - **Node images must be rebuilt to pick this up.**
- **The run summary orders nodes as they ran** when a workflow no longer compiles (a retired node type, or judge-eval until ml-w3 merges). Before, they came back in database order, which was alphabetical through the unique index.
- **"Run it yourself."**
  - Each template has `reduced_inputs` ({node id: inputs}).
  - `GET /agent/templates` adds `reduced: {plan, estimate}`: the same pipeline with those inputs applied. The UI posts `reduced.plan` to /agent/run.
  - Estimates, full → reduced:

    | Template | Full | Reduced | Fits the default anonymous $0.30 run cap? |
    | --- | --- | --- | --- |
    | real-estate | $1.76 | $0.88 | No (see DECISION 1) |
    | movie | $0.15 | $0.03 | Yes |
    | maths | $0.10 | $0.02 | Yes |

  - A test runs movie's reduced plan through /agent/run as an anonymous caller and gets 201.
  - real-estate's $0.88 is tf-finetune's typical $0.50 (no fine-tune price until spike 1) plus 10 min of L40S ($0.30).

### P0 from the orchestrator: no token in artifact meta (R10)
- **One helper**, `apps/api/services/redact.redact()`, replaces the value of every secret-looking key with `"[redacted]"`.
  - It reaches nested dicts and lists.
  - Key names are case-insensitive, and camelCase and kebab-case are normalised to snake_case first.
  - A word of the key must be `api_key|apikey|token|secret|password|authorization`.
  - Keys ending in `_env` stay, so a ModelRef's `api_key_env` (which /compare needs) survives. Counts such as `max_tokens`, `trained_tokens` and `in_tokens` do not match.
- **Applied where meta comes in:** `/internal/artifact`, so the DB never stores a token.
- **Applied wherever meta goes out:**
  - `GET /runs/{id}/summary`. This also covers `GET /agent/runs/{id}/report` and Lightning's report prompt.
  - `GET /runs/{id}/artifacts` and `GET /artifacts`.
  - The golden-run export.
- Output redaction also covers rows stored before this fix.
- The legacy `/inference/endpoints` returns no meta.
- **Tests:** tests/api/test_redact.py and test_golden_run.py. The old vllm-serve's exact `{"api_key": …}` registration goes through the real webhook, and `sk-live` appears in none of the 4 routes or the export.

## Proof
- **`make check`** in the worktree on 140cb4f: exit 0.
  - `All checks passed!`
  - `534 passed, 2 warnings`
  - web 12/12
  - `SKIP stub e2e`
- **Mutation checks:** 19 of 19 caught. Each change was reverted by hand, its tests were run, and the file was restored.
  - Grant release: 1/1 (the old release failed both cancel tests).
  - /compare: 6/6 (any pair accepted, expiry ignored, no start before 200, no ledger, 4xx as 502, error cause leaked).
  - Seed/export: 6/6 (bucket not moved, no replace, objects not exported or uploaded, agent run not seeded, order fallback).
  - Redaction: 6/6 (ingestion, summary/report, run artifacts, artifact list, export, `api_key_env` kept).
- **Live smoke over real HTTP** (scratchpad smoke.sh):
  - Setup: `make demo` twice into a scratch SQLite DB and the compose MinIO, then `uvicorn api.main:app` with STUB=1 on :8017 (checked free).
  - Results:
    - Seeding twice keeps the same run id.
    - Summary: `succeeded 0.0 [research, synth, prep, finetune, serve, evaluate all succeeded]`, 30 artifacts, 6 logs.
    - Report: `ready True`.
    - The eval_summary download answered 307 to a MinIO presigned URL and served `{n 2, judged 2, ties 2, win_rate 0.5, consistency 0.0, stub True}` with 2 samples.
    - The synth logs came back as JSONL from MinIO.
    - Templates: `1.756→0.8793, 0.15→0.03, 0.096→0.024`.
    - /compare SSE answered `HTTP 200 text/event-stream` with `{"i":0,"delta":"stub-…"}`, then `{"i":1,…}`, then a done event for each.
    - Our key sent to `https://evil.example/v1` was refused with `HTTP 422 refused ModelRef …`.
    - The old vllm-serve's api_key meta was registered (201) and then showed `sk-live hits=0 redacted=[redacted]` on summary, run artifacts, artifact list and report.
    - uvicorn log: 0 errors. Cleanup: 28 objects deleted, scratch DB removed.
- **Trial merges** (aborted; nothing committed):
  - NebiusHackathon @ d257183 (devrel-w3, data-w3 review): clean, 543 passed.
  - hack/qa-w3 (also edits docs/NODE_CONTRACT.md): clean, 572 passed.
  - hack/ml-w3 conflicts only in `.github/workflows/ci.yml`, between ml-w3's wave-3a base and the integration branch; none of my files.
- **gitleaks:** the 9 commits and scripts/golden-run.json are clean, and the fixture holds no local paths.

## What does not work / limits
- **real-estate's reduced plan ($0.88) does not fit the default anonymous run cap ($0.30)** (DECISION 1).
- **/agent/run still refuses templates #1 and #3** until ml lands vllm-serve's `lora_adapter` and `model_ref`/`base_model_ref` (with runtime `api`) and quantize's `keep_f16`.
- **The golden run's playground needs a live model.** A vllm-serve endpoint expires 30 min after the run, so /compare refuses the golden run's own refs on the hosted app; this is correct. Lane A's tf-deploy `model_ref` (Token Factory, per token) would keep working. Otherwise the run needs a "Wake endpoint" (D6–D8).
- **Existing quirks seen in the fixture** (P2, not touched):
  - The report links `finetune/lora_adapter`, a directory, which 404s.
  - `model_ref`/`base_model_ref` JSON artifacts auto-register as Model rows, so /models shows 3 identical names.
  - `_terminate_after_ttl` still marks the run succeeded at TTL expiry (R9's endpoint half is pending).
- **Environment:** platform's real-Docker test `test_local_docker.py::test_a_container_that_fails_at_once…` took 125 s in one run while Docker was busy. In other runs the suite took 8–35 s.

## DECISIONs for the orchestrator to record
1. **"Run it yourself" is client-side.** `GET /agent/templates` returns `reduced: {plan, estimate}` from each template's explicit `reduced_inputs`, and the UI posts it to /agent/run. There is no new route. For real-estate to run anonymously on the hosted app, set `ORCHAPOD_ANON_SCALE ≥ 0.3` (run cap ≥ $0.90), or offer only #2 and #3 to anonymous callers until spike 1 prices fine-tunes. Hari/D6.
2. **The SDK persists every node's log lines as a `logs` artifact** (kind `log`, JSONL `{ts, level, message}`) at exit, after cost_json. The events contract keeps "no replay".
3. **Artifact meta is redacted where it comes in and wherever it goes out**, by key name (rule above). `[redacted]` replaces the value; the key stays.
4. **The committed golden run is a STUB placeholder**, made from the real STUB nodes plus two contract stand-ins. D8 replaces it with `--export` of the real run.
5. **/compare refusals:** 422 for a ref outside the pairs, or for what Token Factory rejects (`bad_request`); 502 otherwise (fixed detail); 402/503 as for /agent/plan. Request bounds are as above, and both refs get temperature 0.

## Contract lines proposed (orchestrator edits docs/contracts.md)
- **/compare:** the done event adds `error?` (as the orchestrator planned); usd is null with it. Also add the error codes and request bounds above.
- **Agent API:** `GET /agent/templates` items add `reduced_inputs` and `reduced: {plan, estimate}`.
- **Node SDK:** "At exit, after `cost_json`, the SDK writes `logs` (kind log): JSONL `{ts, level, message}` of every line it logged."
- **R10:** the API redacts secret-looking keys in artifact meta on the way in and on every way out (services/redact.py).
- **Run control API:** for a workflow that no longer compiles, the summary lists nodes in the order they started.

## Notes for other agents
- **frontend-w3.**
  - The compare playground can take refs straight from the summary's `model_ref`/`base_model_ref` artifact `meta`; `api_key_env` survives redaction.
  - It should render `error` on a done event.
  - It should show a finished run's logs from the `logs` artifacts' `download_url`.
  - "Run it yourself" should post `reduced.plan`.
  - The legacy TryItChat now reads `meta.api_key` as `"[redacted]"`, never a key.
- **qa-w3.**
  - /compare needs its own background tasks, so do not put `no_bg_tasks` on a /compare test.
  - The golden run (`make demo`, run 5b45f389-…) gives the Playwright smoke a finished run with an eval_summary while judge-eval is not merged.
  - `make demo` needs MinIO (`make up`).
- **devrel.** `make demo` exists now (README:145 and :184 still say its script is being written); the hosted golden run is still TODO(D8).
- **Orchestrator, after merge.** Rebuild the node images (`orchapod/<node>:dev`), because the SDK is copied into them and now writes `logs`. `make check E2E=1` does this.
