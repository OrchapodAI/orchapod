# qa-w1 report — wave 1 (2026-10-20)

Status: **DONE_WITH_CONCERNS** · branch `hack/qa-w1` · base 178d2e6 (verified ancestor) · commits `31c45ba`, `6c77b52` · cost $0 (no API calls) · not pushed.

**Superseded after review:** see the last section, "Rebase + minors". The branch is rebased onto NebiusHackathon `a0af5e9`; final commits are `4cb3920`, `94ba302`, `b3ece55`; the autouse `_clear_ttl_tasks` fixture described below was deleted; final numbers are `299 passed, 54 warnings`.

Concerns, in order of weight:
1. The `:latest` tag line is a GitHub `${{ }}` expression. No `actionlint`/`act` is installed and I did not download one, so it is verified structurally only (YAML parses, tests below). The first push to NebiusHackathon is the real check: watch the `containers` jobs.
2. The brief's premise for item 2 was off (see below): the fixture it describes cannot remove the warning. I fixed the root cause instead, which edits five call sites in `tests/api/test_internal.py` and `test_runs.py` (backend-w1's files) — a possible merge conflict.
3. `tests/test_harness.py::test_ci_builds_every_container` will go red in wave 2 when `containers/web-research`, `tf-finetune`, `tf-deploy` or `judge-eval` land, until their author adds the matrix entry in ci.yml. That is the intent (R4 says CI builds every `containers/*/`); step 6 of `docs/NODE_CONTRACT.md` now says so.

## Results

| Item | Result | Proof |
|---|---|---|
| 1a. CI pushes `:latest` on NebiusHackathon (R4) | done | `tests/test_harness.py::test_ci_pushes_latest_only_on_nebiushackathon` (red before, green after); mutant "gate removed" is caught |
| 1b. `huggingface_hub`, `ruff==0.17.1`, `jsonschema` in requirements-dev.txt; inline install tail dropped | done | clean venv from the two requirements files only: ruff `All checks passed!`, `160 passed, 56 warnings` |
| 2. "coroutine ... never awaited" gone from tests/api | done | `make check` output has 0 "never awaited" lines (was 3); warnings 58 → 56 |
| `make check` in the worktree | green | `All checks passed!` / `160 passed, 56 warnings in 2.42s` / `SKIP stub e2e: scripts/e2e_demo.py not written yet (qa)` (exit 0) |

Tests: 153 → 160 passed (+4 in `tests/test_harness.py`, +3 in `tests/api/test_bg_tasks.py`).

## Item 1 — CI

Changes (`31c45ba`):
- `.github/workflows/ci.yml`: install step is now `pip install -r requirements-dev.txt -r apps/api/requirements.txt`. The `containers` job's `tags:` gets a third line: `${{ github.ref_name == 'NebiusHackathon' && format('ghcr.io/{0}/{1}:latest', github.repository_owner, matrix.node) || '' }}`. Off NebiusHackathon it renders as an empty line, which docker/build-push-action drops from list inputs. Only the node images get `:latest` (R4 scope); the `orchapod-api` image does not.
- `requirements-dev.txt`: `ruff==0.17.1`, `huggingface_hub`, `jsonschema` under one comment saying CI installs only the requirements files.
- `tests/test_harness.py` (new, 4 tests, PyYAML is already a dependency): install step has only `-r`/`.txt` arguments; the three deps are listed; exactly one `:latest` tag line and it carries the NebiusHackathon gate; the build matrix equals the set of `containers/*/Dockerfile` dirs (8 today).
- Doc line: step 6 in `docs/NODE_CONTRACT.md` "Adding a new node". I put it there rather than in README (devrel is rewriting it this wave) and did not create a new docs file.

Red → green: before the change, `3 failed, 1 passed`: the install line was `pip install -r requirements-dev.txt -r apps/api/requirements.txt huggingface_hub ruff==0.17.1`; the three deps were absent; `latest == []`. After: `4 passed`. The matrix test passed on first run (it is a guard, not change-bound), so I mutation-tested all three: an extra `containers/zzz-fake/Dockerfile` fails it, deleting the `synth-distilabel` matrix entry fails it, and removing the branch gate from the `:latest` line fails it.

CI-equivalent run (uv instead of pip, scrubbed env, scratch venv built only from the two requirements files):
```
uv venv --python 3.12 <scratch>/cleanvenv
uv pip install --python <scratch>/cleanvenv/bin/python -r requirements-dev.txt -r apps/api/requirements.txt   # exit 0; ruff 0.17.1, huggingface_hub 2.2.0, jsonschema 4.26.0
ruff check apps packages containers        -> All checks passed!
python -m pytest tests -q                  -> 160 passed, 56 warnings in 4.78s
```
This is also the first evidence that the CI test job works with no inline tail (the previous qa-check found 13 container tests fail without `huggingface_hub`).

## Item 2 — "coroutine '_terminate_after_ttl' was never awaited"

Root cause (differs from the brief): the tests do not create real TTL tasks. `test_internal.py` and `test_runs.py` use `patch("asyncio.create_task")`, which hands the coroutine to a bare MagicMock that never runs or closes it. `_ttl_tasks[...] = task` stores that mock, whose parent mock holds the coroutine in `call_args`, so it survives until interpreter exit and prints `sys:1: RuntimeWarning: ...` after pytest's summary (outside pytest's count). The two `/inference/deploy` tests do the same with `deploy_model.<locals>._run`; those two warnings were counted in the 58, surfaced in unrelated tests/containers tests when the GC ran, and were not in the brief.

Experiments before changing anything:
- Literal fixture from the brief (cancel `_ttl_tasks`, clear it): `153 passed, 59 warnings`. The exit line disappears but the coroutine is freed during the run and the warning lands in the summary instead. Cancelling cannot reach a coroutine a mock is holding.
- A real TTL task left pending with no cleanup: no warning at all. pytest-asyncio cancels leftover tasks when it closes the loop.
So the coroutine has to be closed, not the task cancelled.

Changes (`6c77b52`), all under `tests/api/`:
- `conftest.py`: `no_bg_tasks` fixture. It replaces `asyncio.create_task` with a stub that calls `coro.close()` and returns a MagicMock. Plus an autouse `_clear_ttl_tasks` fixture (the brief's fixture): at teardown it cancels, awaits and clears `api.routes.internal._ttl_tasks`. The module docstring says never to patch `create_task` by hand.
- `test_internal.py` (3 sites) and `test_runs.py` (2 sites): `with patch("asyncio.create_task"):` → `no_bg_tasks` parameter, block dedented, unused `patch` imports removed. No assertion changed.
- `test_bg_tasks.py` (new, 3 tests): the fixture closes the coroutine it is handed (`CORO_CLOSED`); a TTL task left behind by one test is cancelled and `_ttl_tasks` is empty in the next (relies on file order, noted in a comment).

Red → green: first run `E fixture 'no_bg_tasks' not found` and `assert {'leak': <Task cancelled ...>} == {}`; with the stub fixture lacking `close()`: `AssertionError: assert 'CORO_CREATED' == 'CORO_CLOSED'`. Mutation on the real suite (`coro.close()` replaced by `pass`): `1 failed, 159 passed, 61 warnings` and 3 "never awaited" RuntimeWarnings (`_terminate_after_ttl`, `deploy_model._run`, the test's own `job`). Restored: green.

Warning count (full suite, same machine; raw outputs were in the scratchpad):

| | before | after |
|---|---|---|
| pytest summary | 58 warnings | 56 warnings |
| "never awaited" lines | 3 (exit-time `_terminate_after_ttl` + 2 × `deploy_model._run`) | 0 |
| passed | 153 | 160 |

Stable over 3 full runs and 3 `tests/api`-only runs (0 lines each).

The 56 that remain, with owners (none touched, not in this brief):
- 32 `pydantic/fields.py:617` `datetime.utcnow()` from model `default_factory` in `apps/api/models/db.py` — backend.
- 9 `tests/api/conftest.py` `seeded_node_run`: `started_at=datetime.utcnow()` — qa/backend; one-line fix (`datetime.now(timezone.utc).replace(tzinfo=None)`). I left it to avoid a conflict with backend-w1's conftest edits; say the word and it goes in.
- 14 sqlmodel "use `session.exec()`" in `routes/internal.py` (8), `model_registry.py` (4), `runs.py` (2) — backend.
- 1 starlette/anyio alias in site-packages — third party.

## For the Orchestrator

DECISION candidates:
1. tests/api convention: never `patch("asyncio.create_task")` by hand; use `no_bg_tasks`. backend-w1 is writing retry/cancel/executor tests and will probably patch it again; the warning returns at merge (no red). Tell backend-w1, or swap at merge.
2. CI builds every `containers/*/` from a static matrix and `tests/test_harness.py` enforces it. The alternative is a dynamic matrix (a job listing `containers/*/Dockerfile` into `fromJSON`); I did not do it because I cannot validate workflow changes locally.

Open questions:
- Commit trailer: `.claude/agents/qa.md` requires `Co-Authored-By: Claude Opus 5.5`; this session's harness reminder says `Claude Sonnet 5.5`. I followed qa.md (project rule) and used that one trailer.
- GHCR packages must be public for Serverless Jobs to pull (STATE.md human action, owner Purva); `:latest` is useless until then.

Observed, out of scope:
- `scripts/build-and-push-containers.sh` still defaults to `ghcr.io/${GITHUB_ORG:-orchapod}` (contracts remove GITHUB_ORG; R4 prefix is `ghcr.io/bangadpurva`) and builds 6 of the 8 nodes (no hf-download, synth-distilabel). Owner: platform's ORCHAPOD_IMAGE_PREFIX item.
- STATE.md line ~110 (venv recipe) can drop the `huggingface_hub ruff` tail after this merges. The shared venv has no `jsonschema` yet (I did not touch the shared venv): `uv pip install -r requirements-dev.txt` when data-w1 reaches synth in wave 2.
- ci.yml tags `:${{ github.ref_name }}` is an invalid docker tag for refs containing `/` (PR refs like `12/merge`, `hack/*` branches). Pre-existing and harmless while only NebiusHackathon is pushed.
- The brief cites `apps.api.routes.internal._ttl_tasks`; tests import `api.routes.internal` (pytest `pythonpath = . apps packages/sdk-py`). Those are two different module objects if both are ever imported, so the fixture uses the one the app under test uses.
- Pre-existing F401s in `tests/api/test_internal.py` and `test_runs.py` (4, identical at HEAD) are outside `make check`'s lint scope; untouched. The one in conftest (`import pytest`) disappeared because `no_bg_tasks` uses it.

Likely merge conflicts: `tests/api/conftest.py` (fixtures inserted between `db` and `client`), `tests/api/test_internal.py` / `test_runs.py` (five dedented blocks), `docs/NODE_CONTRACT.md` (one line after step 5).

Reproduce: `cd .claude/worktrees/qa-w1 && . /Users/hari/src/orchapod-hack/.venv/bin/activate && make check` (expect 160 passed, 56 warnings, no "never awaited").

## Rebase + minors

Branch `hack/qa-w1` is rebased onto NebiusHackathon `a0af5e9` and fast-forwardable (verified with `git merge-base --is-ancestor`). The tip moved twice while I worked (`f592fd5` → `ee9db49` → `a0af5e9`, docs-only each time), so I rebased twice. New commits, not pushed: `4cb3920` ci (was `31c45ba`), `94ba302` tests/api (was `6c77b52`), `b3ece55` review minors. Against the tip, only my 8 files differ.

**Rebase.** No textual conflicts: backend's hunks in `tests/api/conftest.py` (the `INTERNAL_SECRET` import and the `X-Orchapod-Secret` header in `client`) and my fixtures (inserted above `client`) do not overlap. I read the merged file to check it semantically: both are present. `docs/NODE_CONTRACT.md` step 6 still sits after step 5 and before the new local-runs paragraph.

**`patch("asyncio.create_task")` in backend's new tests: none to convert.** The only `create_task` calls are `tests/api/test_executor.py:306` and `:325`, real `asyncio.create_task(ex.run_workflow(...))` tasks that the tests cancel and await. Switching them to `no_bg_tasks` would close the coroutine and break the two cancel tests, so they stay.

**Minors folded in (`b3ece55`):**
- `tests/test_harness.py`: install check is `run.split()[-1].endswith(".txt")` (helper inlined, it had one caller); dependency check is a substring check for `ruff==`, `huggingface_hub`, `jsonschema` on the file text; `:latest` check collects every `:latest` line from every job's `with.tags`. I kept `latest and` in front of `all(...)`: a bare "every line contains NebiusHackathon" passes vacuously when the tag is deleted, which is the very regression R4 guards against. Matrix-equality test unchanged.
  - Mutation re-run, each caught by the intended test: inline package appended to the install line; each of the 3 deps removed in turn; `:latest` line deleted; branch gate removed; an ungated `:latest` added to the `api` job. Restored: 4 passed. Accepted looseness: the install check only looks at the last argument (an inline package before the last `-r` file would pass), and a commented-out dependency line would pass the substring check.
- Deleted the autouse `_clear_ttl_tasks` fixture, its two order-coupled tests, and conftest's `import asyncio`. Mutation with it gone: `no_bg_tasks` without `coro.close()` gives `1 failed, 298 passed, 59 warnings` and 4 "never awaited" lines, so `no_bg_tasks` alone is the fix.
- `seeded_node_run` now calls `api.models.db.utcnow` (backend added it in wave 1: naive UTC, as the columns store it) instead of a second expression of mine; the `datetime` import is gone. 12 warnings removed.
- Matrix test kept. Wave-2 node authors add their matrix line (`docs/NODE_CONTRACT.md` step 6 says so).

**Proof, on `b3ece55` with the shared venv:**
```
$ python -m pytest tests -q 2>&1 | grep -c "never awaited"
0
$ make check          # exit 0
All checks passed!
299 passed, 54 warnings in 2.58s
SKIP stub e2e: scripts/e2e_demo.py not written yet (qa)
```

**Warning count.** NebiusHackathon: 294 passed, 66 warnings, and 1 "never awaited" line (`sys:1: ... '_terminate_after_ttl'`, printed at exit and never part of pytest's count; measured from a clean `git archive` export, so the 66 matches yours). Branch: 299 passed (+4 harness, +1 `test_bg_tasks`), 54 warnings, 0 "never awaited". The 12 fewer are exactly the `seeded_node_run` `utcnow()` hits.

The 54 left, none in my files: 52 sqlmodel "use `session.exec()`" deprecations, all backend code (36 raised from `test_executor.py`'s executor calls via `sqlalchemy/ext/asyncio/session.py`, 7 + 3 in `routes/internal.py`, 4 in `model_registry.py`, 2 in `runs.py`); 1 starlette/anyio alias and 1 botocore `utcnow()` (both third party). The earlier "mostly `datetime.utcnow`" note in STATE.md no longer holds: backend's `utcnow()` helper and this fix removed the project-owned ones.
