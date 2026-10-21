# qa-w2 report — wave 2 (2026-10-21)

Status: **DONE** · branch `hack/qa-w2` · base 0c21d98 (verified ancestor) · commits `22c6c96`, `9194e9d`, `4ab098e`, `28504d9`, `5bf0369` · cost **$0** (no paid call: STUB, no key reaches the API) · not pushed · no subagents.

**Superseded in part by "Pre-review changes" (last section, `5bf0369`):** the stub e2e is now opt-in (`make check E2E=1`, strict). Wherever this report says `make check` runs it, ends with it or needs Docker, read that section.

Both items are complete. Item 2 prints a loud SKIP on today's tree because backend-w2 and data-w2 are not merged, and I **ran the real intent #2 path on scratch merges of their branches: PASS** (numbers below), so "goes green once both merge" is observed, not predicted.

Not proven (read these):
1. The real merged NebiusHackathon has not run it; the proof is on scratch clones (`git clone --local` in the scratchpad, removed afterwards; the repo and the worktrees were not touched).
2. `pnpm --config.verify-deps-before-run=false` is verified on pnpm 11 only. There is no pnpm 9 here and I did not download one. CI does not use the flag (plain `pnpm test`), and `make check PNPM=pnpm` overrides it.
3. The CI `Test` step is verified structurally (YAML parsed by a test), not by a CI run. The first push to NebiusHackathon is the real check.
4. Ctrl-C is not separately proven (SIGTERM is; both go through the same `finally`).

## Results

| Item | Result | Proof |
|---|---|---|
| 1a. CI web job runs the web tests | done | `tests/test_harness.py::test_ci_web_job_runs_the_web_tests` (red before: no `pnpm test` step) |
| 1b. `make check` runs the web tests | done | `test_make_check_runs_lint_unit_web_and_stub_e2e` reads `make -n check` (red before: no `-C apps/web test`) |
| 1c. pnpm-11 flag documented | done | Makefile comment above `PNPM ?=`; why: see "Item 1" |
| 1d. build-and-push script covers every `containers/*/` | done | `test_build_script_builds_and_pushes_every_container`, with a recording fake `docker` (red before: `hf-download`, `synth-distilabel` missing, it had 6 of 8) |
| 2. `scripts/e2e_demo.py --stub` | done | `make check` below; scratch merges below; 13 unit tests in `tests/e2e/` |
| `make check` in the worktree | green, exit 0 | below |

```
$ make check          # in the worktree, exit 0
ruff check apps packages containers                      -> All checks passed!
python3 -m pytest tests -q                               -> 315 passed, 2 skipped, 54 warnings in 4.43s   (was 299 passed, 54 warnings)
pnpm --config.verify-deps-before-run=false -C apps/web test
  $ node --test ../../tests/web/*.test.ts                -> tests 6, pass 6, fail 0
python3 scripts/e2e_demo.py --stub
  e2e: API up on http://127.0.0.1:8003 (STUB=1, throwaway DB)
  e2e SKIP (this is NOT a pass: intent #2 did not run):
    - backend-w2 is not merged: GET /agent/templates answers 404 and apps/api/agent/templates/*.json is absent
    - data-w2 is not merged: SynthDistilabelInputs rejects pipeline_template "structured" (packages/workflow_schema/models.py)
    It runs for real once these merge; --strict turns this SKIP into a failure (exit 3).
  e2e: done in 1 s, exit 0
```
The 2 skipped tests are guards on `apps/api/agent/templates/*.json`; they switch on when backend-w2 lands. Warnings are unchanged at 54: nothing I added warns.

## Scratch merges (the real intent #2 run)

| Scratch tree | Result |
|---|---|
| **NebiusHackathon@788a00a** (frontend-w2 merged) + `hack/qa-w2` | merges with **no conflict**; `make check` exit 0: ruff clean, 315 passed + 2 skipped, **12 web tests pass** (frontend-w2 added six), e2e SKIPs with both reasons |
| my branch + platform-w2 + data-w2 + backend-w2 | one conflict (NODE_CONTRACT.md, below; fixed on my branch afterwards). ruff clean; `pytest tests` **422 passed, 0 skipped** (both template guards ran and passed); `python scripts/e2e_demo.py --stub --strict`: **PASS**, run `b7df76f7-...`, synth then prep, **succeeded in 18 s** (limit 300 s), `cost $0`, dataset/train_jsonl/eval_jsonl registered, download link served **500 rows with exactly the five schema fields**, 23 s in total including both image builds |
| base + platform, data, ml, backend, frontend, devrel, then `hack/qa-w2` last | qa-w2 merges **cleanly**. ml-w2 conflicts with platform/data (see "Merge notes"); resolved crudely: web 6 pass, `pytest` 437 passed excluding two ml-w2 files my naive union broke, `--strict` e2e **PASS in 13 s** (18 s in total) |

## Item 1 — web tests in the gate, build script

- `.github/workflows/ci.yml`: the web job gets `Test` (`pnpm test`, working-directory apps/web) after the install.
- `Makefile`: `check` = ruff, pytest, `$(PNPM) -C apps/web test`, `scripts/e2e_demo.py --stub`. `PNPM ?= pnpm --config.verify-deps-before-run=false`. The "script not written yet" fallback is gone because the file exists.
- **Why the flag.** On pnpm 11 a plain `pnpm test` in apps/web first runs `pnpm install`, ends with `ERR_PNPM_IGNORED_BUILDS: sharp` and leaves an untracked `apps/web/pnpm-workspace.yaml` (`allowBuilds: sharp: set this to true or false`). I hit it on my first try and deleted the file. It is the stray file that broke CI before (012ac47) and must never be committed.
- The web tests import only types, so they need no install: verified with `node_modules` moved away. Node 22.18+ strips the types itself (CI's `node-version: 22` resolves to the latest 22.x; here Node 26.5).
- `scripts/build-and-push-containers.sh` loops over `containers/*/Dockerfile` and pushes to `${ORCHAPOD_IMAGE_PREFIX:-ghcr.io/bangadpurva}` (R4) instead of the removed `GITHUB_ORG` / the non-existent `ghcr.io/orchapod`. The brief said "matches CI"; the registry was the other half of that mismatch.
- Doc lines: `docs/NODE_CONTRACT.md` step 5 (no node list to update) and a new step 7 (what `make check` ends with).

## Item 2 — `scripts/e2e_demo.py --stub`

Flow, all through the API (the script never opens a DB):
1. Starts its own API: `STUB=1`, a throwaway SQLite file in a temp dir, `ORCHAPOD_CONTROL_URL` = its own port, kill switch pinned off. The port is the first free one from 8002 (8000/8001 are other projects'); the script **holds the listening socket and hands it to uvicorn with `--fd`**, so two `make check` at once cannot pick the same port or mistake each other's API for their own.
2. The API env has **no paid key**: `VASTAI_API_KEY`, `RUNPOD_API_KEY`, `NEBIUS_API_KEY`, `NEBIUS_IAM_TOKEN`, `NEBIUS_PROJECT_ID`, `ORCHAPOD_ENDPOINT_TOKEN`, `TAVILY_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `HF_TOKEN` are dropped, and it never loads `.env`. Redis and object storage are pinned to the compose stack (`redis://localhost:6379`, MinIO `http://localhost:9000`, `orchapod`/`orchapod_dev`) whatever the shell exports. Test: `test_api_env_is_stub_local_and_cannot_spend`.
3. `GET /agent/templates` (on 404: `apps/api/agent/templates/*.json`; any other status is a failure). Intent #2 = the template whose plan has a `synth-distilabel` node with `pipeline_template: structured`, not a slug.
4. Preflight (Docker answers, Redis, MinIO) names what is missing and says `make up`. Then `docker build -q -t orchapod/<node>:dev -f containers/<node>/Dockerfile .` for each node type in the plan, **always**: a layer-cached image takes about a second and an existing `:dev` may come from another worktree.
5. `POST /workflows` (YAML = `yaml.safe_dump(plan)`), `POST /runs`, `POST /runs/{id}/start`, poll `GET /runs/{id}/summary` every 2 s; past 300 s it cancels the run.
6. Asserts: status `succeeded`; ended within 300 s; the data-prep node (not synth, which also registers a `dataset`) registered `dataset`, `train_jsonl`, `eval_jsonl`; `cost_usd == 0` and every node `usd == 0` **with a `cost_json` on every node** (otherwise the 0 was never measured); the data-prep `dataset` download link (`/artifacts/{id}/download`, 307 to MinIO) serves JSONL rows with exactly the `row_schema` fields.
7. Cleanup: the API is stopped in a `finally` however the script ends (SIGTERM exercised; Ctrl-C takes the same path); the temp dir goes with it.

SKIP rule (never silent): exactly two SKIP conditions, each tied to a named wave-2 task and evaluated independently so both reasons print.
- backend-w2: `GET /agent/templates` is 404 **and** the JSON dir is absent.
- data-w2: `SynthDistilabelInputs` rejects `pipeline_template "structured"` (it validates the plan's own synth inputs, or a probe with a `row_schema`; any other input error is not "unmerged").
Once a prerequisite exists, a problem is a FAIL, never a SKIP (for example "N templates, none is intent #2"; a 500 on the route). `--strict` turns a SKIP into exit 3. The SKIP scaffolding carries a `ponytail:` comment listing what to delete after the merge, and two guard tests (`test_exactly_one_shipped_template_is_intent2`, `test_the_intent2_template_runs_on_the_nodes_that_exist`) switch on when the templates land.

`make e2e` (`--max-cost 3`) exits 2 with "only --stub exists so far; the real run (--max-cost) is written on D3".

### Evidence on today's tree (real stack: Docker Desktop, compose Redis and MinIO; one-off drivers, not committed)
Before the branches existed I drove the script's own functions with stand-in plans that use only `data-prep` (image content identical to base).

| Scenario | Outcome |
|---|---|
| SKIP path | exit 0 with both reasons; `--strict` exit 3; `--max-cost` exit 2 |
| data-prep alone, `hf://stub/rows`, `format: structured` | succeeded in 2.0 s; dataset, test_jsonl, train_jsonl, eval_jsonl, metrics_json, cost_json; `cost_usd` 0.0; 20 rows through the download link |
| two-node chain (`second.dataset = ${{ nodes.first.outputs.dataset }}`) | succeeded in 4.0 s; ref resolution between containers works; both nodes `usd` 0.0 with `cost_json` |
| failing node (nonexistent r2 dataset) | failed in 2.0 s: `exit 1: ClientError: ... (404) ... HeadObject`, reported with its node. The exit code was read, so platform-w2's fast-fail race did not trigger this time; the artifact check would still catch a false success |
| limit exceeded (limit shrunk to 0.5 s) | run cancelled through the API, final state `cancelled`, no leftover container |
| SIGTERM 0.7 s after launch | exit 143, port 8002 free afterwards, no orphaned uvicorn, no temp dir |
| two instances at once | both passed with their own ports, APIs and DBs |

Mutation checks (each fails the named test, then restored): API env keeps paid keys; `check_run` finds artifacts by name across the whole run (synth's `dataset` would stand in for data-prep's); the port choice ignores a busy port (on the first `free_port`; the test was then rewritten red-first for the held socket, `listen_on_free_port`); `preflight` stops naming Redis; a 500 on `/agent/templates` treated like a 404.

## Assumptions about unmerged work, checked on the scratch merges
1. Template shape: `{slug, title, intent, rationale, plan, estimate}`; backend-w2's `2-movie-engagement.json` has a `synth-distilabel` node with `pipeline_template: structured` and a dict `row_schema`. Confirmed.
2. Every node of that plan is `cpu` with a `containers/<type>/Dockerfile`. Confirmed (guard test).
3. `POST /runs/{id}/start` is not refused for an anonymous caller in STUB: backend-w2's `budget.guard(db, scale, run)` checks caps × `ORCHAPOD_ANON_SCALE` (run cap $0.30) against what is left, with `need=0`. Confirmed by the run.
4. `GET /runs/{id}/summary` keeps today's shape. Confirmed.
5. The template gives data-prep `format: structured`. Confirmed.
6. STUB synth rows carry exactly the schema's fields (the check compares field names, not types or enums). Confirmed: 500 rows.

## Merge notes for the Orchestrator
- **qa-w2 merges cleanly** onto NebiusHackathon@788a00a and after every other wave-2 branch. One conflict existed (platform-w2 and I both appended to the one-line "Local runs use ..." paragraph of `docs/NODE_CONTRACT.md`); my sentence is now step 7 of the list and the paragraph is back to base (`28504d9`).
- **ml-w2 conflicts with platform-w2 + data-w2** in `.github/workflows/ci.yml` (matrix lines), `packages/workflow_schema/models.py` (both append at the end of the registry) and `tests/containers/conftest.py` (ml-w2's `clock` fixture beside data-w2's `files` and `run_main`). A line-union is wrong: it leaves the `web-research` registry entry without its closing `}` (ruff syntax error) and loses `clock` (28 errors in `test_tf_deploy.py` and `test_tf_finetune.py`). Needs a hand merge.
- After the merge run `python scripts/e2e_demo.py --stub --strict`; it must print PASS. Then change the Makefile line to `--stub --strict` (or delete the scaffolding marked `ponytail:`), so a regression cannot hide as a SKIP.

## Shared state and side effects
- `orchapod/<node>:dev` tags are global to the Docker daemon, so every worktree shares them. BuildKit gives each build a new image id even when every layer is cached, so the e2e moves the tag every run. State now: `data-prep:dev` = `8797b5e98868` (was `c6c993072070`, built before the wave-2 worktrees existed); `synth-distilabel:dev` = `0de96aa26ccd` (was the 5-month-old `445cae918065`, with the vendored SDK and the OpenAI/Anthropic code), now built from the data-w2 merge. `hf-download:dev` is untouched. Anyone testing a node image should rebuild right before the run, which is why the e2e always rebuilds from the tree it runs in.
- `make check` now needs Docker and `make up`. A stack that is down is a FAIL naming the service, not a SKIP.
- Every e2e run leaves a few KB under `runs/<uuid>/` in the MinIO bucket (no delete API; not worth a cleanup path).
- The API binds 127.0.0.1, which Docker Desktop reaches as `host.docker.internal`. Linux needs 0.0.0.0 (marked `ponytail:` in `start_api`).
- The session scratchpad is shared with other agents. My scratch clones were `sim`, `sim2`, `sim3` (removed), plus `standin_*.py`, `make_check*.out`, `run_a.out`, `run_b.out`. I ran `rm -rf sim` before the first clone without checking it was free; nothing in the scratchpad references that name, but if an agent misses a directory called `sim`, that was me.
- A stray `apps/web/pnpm-workspace.yaml` appears after plain `pnpm` commands on pnpm 11; I deleted mine, and the worktree was clean at every commit.

## DECISIONs for the Orchestrator to record
- DECISION: `make check` ends with the stub e2e and therefore needs Docker and `make up`.
- DECISION: only the two named wave-2 prerequisites may SKIP; after both merge, `--strict` goes into the Makefile line.
- DECISION: the stub e2e is hermetic by construction: no paid key in the API env, compose stack pinned, temp DB, its own port.

## Open questions
1. CI does not run the stub e2e (needs compose Redis/MinIO, and on Linux a 0.0.0.0 bind for the API). Add a job after the wave-2 merge?
2. Add `apps/web/pnpm-workspace.yaml` to `.gitignore` (outside my paths)? One line prevents a repeat of 012ac47.
3. Lines for others, outside my paths: README.md:111 → `make check  # ruff + unit tests + web tests + stub e2e (needs Docker and make up); no keys, no spend` (devrel-w2 is editing the README, so I did not). CLAUDE.md "Commands" → `make check # lint + unit + web tests + stub-mode e2e (needs make up)`.
4. Pre-existing: `ruff check scripts` fails on an unused `json` import in `scripts/seed-demo-workflow.py` (outside the gate's lint paths; `make demo` points at a `seed-golden-run.py` that does not exist).
5. Pre-existing: running the web tests prints Node's `MODULE_TYPELESS_PACKAGE_JSON` warning; `"type": "module"` in apps/web/package.json (frontend's file) would silence it.
6. The 2 s poll and no retry of a failed API call are deliberate (`ponytail:` in `run_plan`); add backoff if the API ever flaps.

## Files
- New: `scripts/e2e_demo.py`, `tests/e2e/__init__.py`, `tests/e2e/test_e2e_demo.py`.
- Changed: `.github/workflows/ci.yml`, `Makefile`, `scripts/build-and-push-containers.sh`, `tests/test_harness.py`, `docs/NODE_CONTRACT.md`.
- Scratch drivers (not committed): `/private/tmp/claude-501/-Users-hari-Desktop-hackathon/066c0f1b-32ee-4418-ae97-33bd3cc37ec5/scratchpad/standin_{run,fail,chain}.py`.

## Pre-review changes (Orchestrator's request before review, commit `5bf0369`)

Why: several worktrees run `make check` in parallel, and the e2e builds and retags the shared `orchapod/<node>:dev` images, so they would overwrite each other.

| Change | How | Proof |
|---|---|---|
| The stub e2e is opt-in | `Makefile`: `ifeq ($(E2E),1)` selects the last step of `check`. Without it, one line: `SKIP stub e2e: set E2E=1 (orchestrator/integration only)`. With `E2E=1` it runs `scripts/e2e_demo.py --stub --strict`. `E2E=1 make check` works too. | `test_make_check_skips_the_stub_e2e_unless_asked` and `test_make_check_e2e_1_runs_the_stub_e2e_strict` read `make -n check E2E=<v>`; both were red first |
| `apps/web/pnpm-workspace.yaml` is ignored | `.gitignore`, with a comment naming 012ac47 | `test_pnpm_11_workspace_file_is_gitignored` (`git check-ignore`); red first |
| CI | unchanged: the test job still runs ruff and pytest only, and the e2e is not in CI (your wave-3 call) | `git diff 28504d9 5bf0369 -- .github` is empty |

Mutations caught (each by the named test, then restored): the e2e runs whatever `E2E` is; `--strict` dropped under `E2E=1`; the web tests dropped from `check` (both Makefile tests); the `.gitignore` line removed.

Also updated to say "opt-in": the Makefile comment, the `scripts/e2e_demo.py` docstring and `ponytail:` comment (after the merge, delete the SKIP scaffolding, `--strict` and the Makefile's `--strict`), the `tests/e2e` docstring, and `docs/NODE_CONTRACT.md` step 7.

```
$ make check                 # exit 0, in the worktree at 5bf0369
All checks passed!
317 passed, 2 skipped, 54 warnings in 5.60s      (was 315 passed, 2 skipped: +2 net harness tests)
ℹ tests 6 / pass 6 / fail 0                      (web, pnpm 11 with the flag)
SKIP stub e2e: set E2E=1 (orchestrator/integration only)

$ make check E2E=1           # strict SKIP on today's tree: ruff, pytest (317 passed) and web tests as above, then
e2e: API up on http://127.0.0.1:8002 (STUB=1, throwaway DB)
e2e SKIP (this is NOT a pass: intent #2 did not run):
  - backend-w2 is not merged: GET /agent/templates answers 404 and apps/api/agent/templates/*.json is absent
  - data-w2 is not merged: SynthDistilabelInputs rejects pipeline_template "structured" (packages/workflow_schema/models.py)
e2e: done in 1 s, exit 3
make: *** [check] Error 3                        # make's own exit status is 2; the e2e's 3 is the "Error 3"
```
Neither run built an image or touched a `:dev` tag (the SKIP path stops before the build).

What this changes in the rest of the report:
- `make check` no longer needs Docker or `make up`; only `make check E2E=1` does. The "retags the shared `:dev` images" note applies to `E2E=1` runs only.
- My DECISION about `make check` ending with the e2e is replaced by: **DECISION: the stub e2e runs only on `make check E2E=1`, strict; the Orchestrator runs it on NebiusHackathon after merges, expecting PASS (13-18 s on my scratch merges).** The hermetic-env DECISION stands.
- Open questions 1 and 2 are settled (CI e2e: your wave-3 call; the `.gitignore` line is in).
- Lines still saying "stub e2e" as part of `make check`, outside my paths: `README.md:111`, `CLAUDE.md:24`, `hackathon/ORCHESTRATOR.md:206`. Suggested: `make check  # ruff + unit tests + web tests; E2E=1 adds the stub e2e (orchestrator/integration only)`.
- Merge check: `hack/qa-w2` merges with no conflict onto NebiusHackathon@18a817d (scratch clone, removed afterwards).
