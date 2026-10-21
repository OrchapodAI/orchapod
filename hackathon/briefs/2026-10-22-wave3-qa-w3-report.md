# qa-w3 report — wave 3 (2026-10-22)

Status: **DONE** · branch `hack/qa-w3` · base 10168de (verified: `git merge-base --is-ancestor 1c0b746 HEAD`) · 16 commits, tip `0038b3d` · cost **$0** (STUB only, no key anywhere, no paid call) · not pushed · no subagents · worktree clean. Resumed after the restart; nothing committed was redone.

Commits, oldest first: `ee6227b` carry-overs, SKIP scaffolding deleted · `1902e58` e2e_agent.py · `3b37969` two weak assertions · `4d179f6` ui-smoke · `4adc9be` fail fast · `81d1b09` eval_summary guard, UI timeouts · `928ce8c` `88187df` agent test follows frontend-w3 · `2d39b33` `23c0534` process-group tests, ml-w4 named · `31438eb` dataset card vs file · `33a2d3e` missing UI piece = failure · `4df1b2a` `dbad191` two locator races · `06adc5f` only vllm-serve can SKIP · `0038b3d` golden path fails fast.

Not proven (read these):
1. The merges below are **scratch merges** in the scratchpad (removed afterwards); the real NebiusHackathon has not run my branch. On the real head, intent #1 and the golden-path UI test SKIP, because ml-w4's vllm-serve is not merged. Their PASS is proven only on a scratch tree that also holds **two scratch-only edits that are on no branch**: a minimal vllm-serve STUB and `reduced_inputs.research.max_pages: 20` in template #1 (finding 1).
2. The real `make agent-e2e` is not written (it needs keys, spike 3). It is refused without `--max-cost`; with it, it says "only --stub exists so far" and exits 2.
3. Nothing here runs in CI. Chromium only; the web app runs as `next dev`, not a production build.

## Results

| Item | Result | Proof |
|---|---|---|
| 0a SKIP exits 0, `--strict` makes it 3 | done, on the SKIP that exists (see "Item 0") | `test_a_skip_exits_0_and_strict_makes_it_3`; live: exit 0 / 3 |
| 0b `stop()` waits 45 s; `start_api` inside the try | done | `test_stop_gives_the_api_45_s…`, `test_a_stack_that_cannot_start_is_reported_not_a_traceback`, `test_the_api_stops_however_the_run_ends` |
| 0c drift guard `_FORWARD` → `PAID` | done | `test_paid_names_every_key_and_token_the_executor_forwards_to_containers` (HF_TOKEN out of PAID: red) |
| 0d delete the wave-2 SKIP machinery | done | `MISSING`, `skip_reasons`, `structured_supported`, `--strict` and the Makefile's `--strict` for e2e_demo, and the templates-on-disk fallback are gone |
| 1 `scripts/e2e_agent.py --stub`, three intents, plan → run → report | done | below |
| 1 `make agent-e2e` refuses without `--max-cost` | done | `test_a_real_run_is_refused_without_max_cost` (5 cases); live: exit 2 |
| 2 Playwright smoke | done: 4 tests, `make ui-smoke` | below |
| `make check` in the worktree | green | `560 passed, 126 warnings` · ruff clean · web `tests 12 / pass 12` · exit 0 |

## Proof

**Real head, scratch merge**: NebiusHackathon c36f051 (frontend-w3, data-w3, platform-w3, backend-w3 and ml-w3 merged) + my branch at 06adc5f; no conflict.
```
$ make check E2E=1
All checks passed!   648 passed, 2 warnings   ℹ tests 22 / pass 22 (web)
e2e: PASS intent #2 (stub): run 747db73a-… succeeded in 8 s (limit 300 s), cost $0, dataset, train_jsonl, eval_jsonl registered, dataset downloadable
e2e SKIP intent #1 (this is NOT a pass: it did not run; --strict turns it into a failure)
  - ml-w4: vllm-serve is not to contract yet (lora_adapter input, model_ref and base_model_ref outputs, runtime api; contracts "vllm-serve")
e2e: PASS intent #2: run 1a1de4c2-… succeeded in 8 s … report ready (707 chars)
e2e: PASS intent #3: run 478da726-… succeeded in 8 s, cost $0, estimate $0.096, report ready (939 chars)
e2e: 2 PASS, 1 SKIP (not passes), 0 FAIL      make: *** [check] Error 3
$ make ui-smoke        (exit 0)
  ✓ /agent: intent #2 is planned, run and reported · ✓ templates: one click runs intent #2 … dataset card
  ✓ run page: eval view and compare playground on a run served from a fixture · - golden path (SKIP, same reason)
e2e: playwright: 3 passed, 1 SKIPPED (not passes), 0 failed, 0 flaky
```
**`make check E2E=1` fails until ml-w4 merges**: the agent e2e exits 3 under `--strict` (make's own status is 2, "Error 3"). To run what exists: `python scripts/e2e_agent.py --stub` (SKIPs exit 0) or `--intent 2`.

**The same tree plus the scratch vllm-serve STUB** (the template as merged, for the agent e2e; with the one template line of finding 1 for the UI):
```
$ python scripts/e2e_agent.py --stub --strict
e2e: PASS intent #1: run a7f041c1-… succeeded in 10 s … estimate $1.621, report ready (1257 chars)   (6 nodes)
e2e: PASS intent #2: … in 8 s        e2e: PASS intent #3: … in 6 s (4 nodes)
e2e: 3 PASS, 0 SKIP (not passes), 0 FAIL        exit 0
$ make ui-smoke UI_ARGS=--strict       (2 runs; 3 more on the previous head)
e2e: playwright: 4 passed, 0 SKIPPED (not passes), 0 failed, 0 flaky
```
That run exercised my checks on ml-w3's real STUB output: judge-eval's `eval_summary` against the contract (with `exact_match`), quantize `keep_f16` → `gguf_f16`, hf-download, tf-finetune `job`/`lora_adapter`, and the UI against backend-w3's `/compare`.

## Item 0 — carry-overs
- Both wave-2 prerequisites are merged, so intent #2 either runs or fails: its SKIP machinery is deleted (0d). Test 0a was written for `get_templates → None`, a path 0d deletes, so it covers the SKIP that exists: `e2e_agent.py`'s named gap. A SKIP prints `e2e SKIP … (this is NOT a pass …)` and exits 0; `--strict` exits 3.
- `with_stack()` (new, in e2e_demo.py) is the one place that starts the API, waits for it and stops it however the run ends (failure, Ctrl-C, SIGTERM); a start that fails is `e2e FAIL: …`, not a traceback. e2e_demo, e2e_agent and e2e_ui all use it.
- `check_run` asserts what **each node type** registers (`MUST_REGISTER`, from the contract), not only data-prep.

## Item 1 — `scripts/e2e_agent.py`
`--stub [--intent 1|2|3|text] [--strict]`. Per intent: POST /agent/plan (the STUB planner must return that intent's canonical plan and estimate, no errors, estimate ≤ the $3 run cap) → build the node images → POST /agent/run → GET /agent/runs/{id}/report every 2 s until `ready`. Asserted: run succeeded in < 5 min, every node's contract artifacts and a `cost_json`, cost $0, the report names the plan, the data-prep dataset downloads (intent #2: rows with exactly the schema's fields), judge-eval's `eval_summary` has the contract's shape, quantize `keep_f16` registers the f16 baseline. API env: STUB, throwaway DB, no paid key, `ORCHAPOD_ANON_SCALE=1` and the caps pinned (the UI is anonymous; intent #1 costs $1.62 against a $0.30 anonymous cap).
- **Only the vllm-serve gap can SKIP** (`PENDING`, two patterns), and only when every plan error is that gap; any other error, or a plan that is not the canonical one, FAILs. ml-w3's and backend-w3's entries were deleted when they merged: a plan without judge-eval or keep_f16 now fails (`test_a_merged_piece_that_goes_missing_fails_instead_of_skipping`). `test_every_planner_error_about_vllm_serve_on_a_shipped_template_is_a_named_gap_or_gone` fails if the planner's wording drifts. A `ponytail:` comment lists what to delete once ml-w4 merges (PENDING, `skip_reasons`, the SKIP branch, `--strict`, the Makefile's `--strict`).
- Makefile: `E2E=1` runs `e2e_demo.py --stub && e2e_agent.py --stub --strict`.

## Item 2 — Playwright smoke (`make ui-smoke`, `tests/ui/`, `scripts/e2e_ui.py`)
`@playwright/test` **1.63.0**, pinned with its lockfile; it uses Chromium 1243, which was already in `~/Library/Caches/ms-playwright`, so **no browser download happened**. `make ui-deps` installs (pnpm 11 exits 1 on apps/web with `ERR_PNPM_IGNORED_BUILDS: sharp`, harmless: the Makefile ignores that line, and the driver names a missing install). `scripts/e2e_ui.py` starts the STUB API and `next dev` on the first free ports (8002+, 3100+), builds the images of the intents that can run, runs Playwright, stops both process groups, and prints the honest count from Playwright's JSON report.

| Test | Asserts |
|---|---|
| `/agent: intent #2 is planned, run and reported` | type the intent, Plan, the plan card (nodes, `$0.15 · ~N min`), one click on Run, the report "…: succeeded", `$0.00 spent of $0.15 estimated`, the artifacts tab, no page error, no console error, no API call ≥ 400; fails at once if the run or the report fails |
| `templates: one click runs intent #2 …` | the gallery's `Run template: <title>` on /agent; the dataset card: download link, the five fields, and **its row count equals the rows of the downloaded file** (the one-click Run is the reduced plan: 100 rows, not 500) |
| `run page: eval view and compare playground on a run served from a fixture` | contract-shaped `eval_summary` and a mocked `/compare` SSE: win rate 75 %, consistency, samples with both orders' reasoning, two model refs streamed side by side |
| `golden path: template, run, eval view, compare playground` | one click on template #1, the run, then the same eval and playground steps on real STUB data over POST /compare |

SKIP policy: only intent #1's pending list (the driver derives it from the planner's errors, so it is the vllm-serve gap and dissolves with ml-w4) can SKIP. A missing gallery, eval tab or `/compare` is a **failure**: frontend-w3 and backend-w3 are merged, and frontend-w4 promised not to rename accessible names, which the smoke now enforces. `UI_ARGS=--strict` fails SKIPs.

## Findings for the Orchestrator
1. **G1 blocker in STUB: the gallery's one-click Run of template #1 fails at judge-eval with `exit 1: no test rows`** (reproduced at head c36f051; the report says `$0.00 spent of $0.83 estimated`, i.e. the reduced plan). One-click posts the reduced plan (backend-w3, "Run it yourself"). In STUB, web-research returns one passage per page and grounded synth one pair per passage, so `max_pages: 4` gives `passages 4 → n_rows 4 (requested 40)` and data-prep splits `total 4, train 3, eval 1, test 0`. With `reduced_inputs.research.max_pages: 20` in `apps/api/agent/templates/1-real-estate-compliance.json` (20 rows, test 2) the whole UI golden path passes (strict). Fix options: that template line (backend), or make the STUB nodes honour the requested sizes (data-engineering). A keyed run is probably fine (real pages give many passages) but is unverified.
2. **vllm-serve (ml-w4) must satisfy what the smoke needs**: `lora_adapter` input, `model_ref`/`base_model_ref` outputs (kind `model`, metadata = the ModelRef with `api_key_env: ORCHAPOD_ENDPOINT_TOKEN`), runtime `api`, and a STUB path that registers its endpoint through `/internal/ttl` (an `endpoint` artifact with a future `expires_at`), otherwise `/compare`'s pairing rule refuses the ref (422). This scratch STUB made all three intents and all four UI tests pass (not committed):
   ```python
   inputs = io.read_inputs(); base = inputs["model"]
   log.post("/internal/ttl", {"action": "register_ttl", "keep_alive_min": int(inputs.get("keep_alive_min") or 30), "endpoint_url": "http://stub.invalid"})
   ref = {"base_url": "http://stub.invalid/v1", "model": "tuned", "api_key_env": "ORCHAPOD_ENDPOINT_TOKEN", "base_model": base}
   for name, body in (("model_ref", ref), ("base_model_ref", ref | {"model": base, "base_model": None})):
       path = io.local_path(name); json.dump(body, open(path, "w")); io.write_output(name, path, kind="model", metadata=body)
   ```
   Today's Dockerfile is `FROM vllm/vllm-openai:latest` (x86, ~10 GB); the node only calls the Nebius API now, so it should be python-slim like the other `api` nodes, or the e2e image build (600 s cap) will fail.
3. Template #1 estimates `~57 min` and $1.62; G1 wants under 25 minutes and $3. The minutes are `TYPICAL` guesses (backend), not measurements.
4. The /agent report card shows raw Markdown in a `<pre>` (`## movie-engagement-synthetic-data: succeeded`): for frontend.
5. A `docker build` failed once with a containerd "failed to prepare extraction snapshot" error while other agents were building; the rerun passed. After the machine restart Docker Desktop was down: I started it and ran `make up` (our compose project only).

## Mutation checks (each fails a named test, then restored)
- e2e logic: 24 mutations, 21 caught first time; three assertions were too weak (argparse's usage line contained "--max-cost"; a plan-mismatch test used errors that were not gaps of its plan) and were fixed: 24/24. They include: PENDING pattern dropped, node-type binding dropped, SKIP beats a plan mismatch, `--strict` ignored or always on, FAIL not failing, no `--max-cost` check, estimate cap, eval_summary stub flag / rate range / samples, keep_f16, report must name the plan, stop() 20 s or never kills, PAID without HF_TOKEN, start outside the try, API not stopped, `extra` env, poll_run cancel / ready, MUST_REGISTER, cost_json.
- Since: the planner rewording "unknown input" (vllm-serve guard); `stop_group` killing only the leader and `run_playwright` cleaning up only its child (process-group tests, which now poll instead of sleeping: one failed at a load average of 150).
- UI, against the product: `/agent/run` answering 402 and a report that names no plan are caught by the agent test; a plan error is caught by the driver before Playwright starts.

## Shared state and side effects
- `orchapod/<node>:dev` tags are shared: my scratch runs retagged data-prep, synth-distilabel, web-research, tf-finetune, judge-eval, quantize and hf-download (trees = head). I **deleted `orchapod/vllm-serve:dev`**, which held my scratch STUB. ml-w4 uses its own `:ml-w4` tags.
- Docker Desktop and the orchapod-hack compose stack are running (needed by everyone). No leftover processes; scratch clones and their `node_modules` removed. `tests/ui/node_modules` and `apps/web/node_modules` exist in the worktree (ignored).
- A loaded machine (load average 20–170) made the same UI test take 7 s to 100 s: timeouts are generous (test 5 min, global 9 min, expect 30 s, action 60 s).

## DECISIONs for the Orchestrator to record
- DECISION: `make check E2E=1` = `e2e_demo.py --stub` then `e2e_agent.py --stub --strict`; the only SKIP left is vllm-serve (ml-w4), and the code that SKIPs is deleted when it merges. Until then E2E=1 fails (agent e2e exit 3).
- DECISION: the Playwright smoke is `make ui-smoke` (separate from `check E2E=1`), Playwright pinned in `tests/ui`; a missing UI piece, judge-eval or `/compare` fails, a missing vllm-serve SKIPs; `UI_ARGS=--strict` fails SKIPs.
- DECISION: `make agent-e2e` refuses without `--max-cost`; the real run waits for keys (spike 3).
- DECISION: tests import the e2e drivers by name (`pytest.ini` pythonpath gains `scripts`).

## Open questions
1. Owner of finding 1 (template #1 reduced plan in STUB)? It blocks "G1 stays green in STUB" and the golden-path UI test.
2. Should `make ui-smoke` join `make check E2E=1`? It adds 1–2 minutes and needs node, pnpm and the cached Chromium.
3. A CI job for the stub e2es and the smoke (needs compose Redis/MinIO, Docker builds, and on Linux a 0.0.0.0 API bind, marked `ponytail:` in `start_api`)?
4. Lines for others, outside my paths: `CLAUDE.md:24` and `hackathon/ORCHESTRATOR.md:206`: "`make check E2E=1` adds the stub e2es (intent #2 through the workflow API, then the three canonical intents through the Agent, --strict)"; add "`make ui-smoke  # Playwright smoke of the web app on the stub stack (UI_ARGS=--strict fails SKIPs)`"; `README.md:114` and `:146` say E2E=1 runs only the synthetic-data intent.

## Files
New: `scripts/e2e_agent.py`, `scripts/e2e_ui.py`, `tests/e2e/test_e2e_agent.py`, `tests/e2e/test_e2e_ui.py`, `tests/ui/{package.json,pnpm-lock.yaml,playwright.config.ts,smoke.spec.ts,.gitignore}`. Changed: `scripts/e2e_demo.py`, `tests/e2e/test_e2e_demo.py`, `tests/test_harness.py`, `Makefile`, `pytest.ini`, `docs/NODE_CONTRACT.md` (step 7).
