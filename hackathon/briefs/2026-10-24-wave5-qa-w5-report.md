# qa-w5 report — wave 5 (2026-10-24), role qa

Branch `hack/qa-w5` on 5354f75 (ancestor check passed). Commits: `e43af10` item 1, `a102114` item 2. Item 3 is not started (it waits on backend-w5). Spend: $0. No stack, container, image tag, port or cloud call: only `make check` and read-only lookups.

## Item 1: the vllm-serve SKIP layer is deleted, a missing piece fails (e43af10)
Every SKIP-SITE(ml-w4) site of the marker is gone; `git grep` for the tag, `skip_reasons`, `ui_pending`, `E2E_PENDING`, `E2E_STRICT` and `SKIP_SITES` finds nothing outside three old briefs (wave 2 and 3 qa reports, this wave's brief).

| File | Deleted or changed |
| --- | --- |
| scripts/e2e_agent.py | `PENDING`, `VLLM`, the marker comment, `skip_reasons`, the SKIP branch of `run_one`, the `--strict` flag, exit code 3, `import re`; `run_all(c, which)` has no `strict`; the summary line reads `3 PASS, 0 FAIL: ...` (it was `3 PASS, 0 SKIP (not passes), 0 FAIL`) |
| scripts/e2e_ui.py | `ui_pending` -> `ui_node_types(c) -> set[str]` (any plan error of a canonical intent raises); `playwright_env(web, api, public, environ)` loses `pending` and `strict`; `E2E_PENDING`, `E2E_STRICT`, `--strict`, the "cannot run yet" lines |
| tests/ui/smoke.spec.ts | `STRICT`, `PENDING`, `pending()`, its call in the golden path, and the fixture test with its constants; `playwright test --list` shows 4 tests (it was 5) |
| Makefile | both SKIP-SITE comments; `UI_ARGS=--strict` note |
| tests/test_harness.py | the `"--strict" not in dry_run` assertion; the test is renamed `test_make_check_e2e_1_runs_both_stub_e2es` |
| tests/e2e/test_e2e_agent.py, test_e2e_ui.py | the SKIP tests, `SKIP_SITES` and the marker test (11 items out); new: a missing piece (the old vllm-serve errors; a missing judge-eval) is a FAIL that names it, a planner answering with another plan fails, `ui_node_types` raises on any plan error (6 items in) |
| docs/NODE_CONTRACT.md | step 7: the SKIP sentence and `UI_ARGS=--strict` |

Decisions to record:
1. **`--strict` is gone, not restored.** The brief says to restore it in `check E2E=1`, and the marker says to delete the flag from e2e_agent.py. They conflict. With no SKIP path the script is strict by construction, so `check E2E=1` runs `e2e_demo.py --stub && e2e_agent.py --stub` and a missing piece FAILs. Passing the flag now fails: `python scripts/e2e_agent.py --stub --strict` -> `error: unrecognized arguments: --strict`, exit 2.
2. **`UI_ARGS` stays** in the `ui-smoke` recipe as a plain pass-through (`make ui-smoke UI_ARGS="-g golden"`): hackathon/LOG.md (qa-w4 run) shows the Orchestrator uses it for `-g`. Only the `--strict` meaning went.
3. **The fixture test went** (the marker says so). Its two exact assertions left with it: the joined deltas of one side (still unit-tested: tests/web/web.test.ts "a compare side appends deltas") and the `75%` win-rate text (`Math.round(x * 100)%` in apps/web/components/runs/EvalView.tsx; the golden path now checks the eval view on real STUB data but not that number).

Stale after this merge, for the Orchestrator to edit: the two qa rows of hackathon/STATE.md (D3 e2e_agent: "`--strict` returns with ml-w4's vllm-serve"; D4 Playwright smoke: "golden path SKIPs until ml-w4"). CLAUDE.md's "strict stub e2e" is true again.

Proof (worktree, venv):
- Baseline `make check` at 5354f75: ruff clean, `700 passed, 2 warnings`, web 27/27.
- `make check` at a102114: exit 0, ruff `All checks passed!`, `695 passed, 2 warnings in 17.51s` (700 - 11 + 6), web `tests 27, pass 27, fail 0`, then `SKIP stub e2e: set E2E=1 (orchestrator/integration only)`. e43af10 alone: tests/e2e + tests/test_harness.py `77 passed`.
- `make -n check E2E=1` ends in `python3 scripts/e2e_demo.py --stub && python3 scripts/e2e_agent.py --stub`.
- Spec, from a scratch copy using the existing tests/ui install (nothing installed): `playwright test --list` -> 4 tests, `Total: 4 tests in 1 file`; `tsc --noEmit --strict --noUnusedLocals` -> exit 0 (a canary error is caught).
- In-process planner under the e2e's env (STUB=1, full scale, no keys): `real-estate-compliance errors=[] estimate=$1.621`, `movie-engagement errors=[] $0.15`, `maths-quantize errors=[] $0.096`, `nebius-docs-specialist errors=[] $0.766`. So the plan step of `e2e_agent.py --stub` cannot FAIL on a missing piece in this tree.
- NOT run, by instruction: `make check E2E=1`, `make ui-smoke` (they retag the shared `orchapod/*:dev` images). Orchestrator, after the merge, expect `e2e_agent.py --stub`: `3 PASS, 0 FAIL` and `make ui-smoke`: 4 passed (not 5).

## Item 2: CI frees disk before the 20 GB images (a102114)
- `.github/workflows/ci.yml`, `containers` job, after checkout and before login and buildx: `jlumbroso/free-disk-space@54081f138730dfa15788a46383842cd2f914a1be # v1.3.1`, with `if: contains(fromJSON('["unsloth-train", "distill-sft"]'), matrix.node)`. The other ten cells skip it. 6 lines, defaults of the action.
- Pin checked with `git ls-remote --tags https://github.com/jlumbroso/free-disk-space.git`: v1.3.1 = 54081f13... (lightweight tag, so a commit). v1.3.2 (3f13feab...) and v2.0.0 (ceedf095...) also exist; I did not evaluate them.
- I chose this over excluding unsloth-train: the excluded node would still need the same disk step in a manual workflow, so it is the larger diff. The matrix is unchanged, so `test_ci_builds_every_container` and the build-script test keep enforcing it.
- distill-sft is included beyond the brief: its base is `nvcr.io/nvidia/pytorch:24.10-py3` (the 22 GB NGC image of ml-w4's report) plus unsloth and vllm, the same disk problem. Drop it from the list if you would rather not widen the scope.
- New test `test_ci_frees_disk_before_building_the_20gb_images`: the step exists, comes before the build, is pinned to 40 hex, and has an `if` naming unsloth-train. Red before the edit, green after.
- NOT proven: nothing here runs GitHub Actions. The first CI run on NebiusHackathon shows whether the freed disk is enough. Fallback: drop unsloth-train from the matrix and build it from a manual `workflow_dispatch` (with the same step).
- Open: both cells also run `cache-to: type=gha,mode=max`; a 20 GB image may flood the repo's 10 GB cache and evict the other nodes' caches (slower builds, not failures). If CI slows down, give those two cells an empty `cache-to`.

## Item 3: the preempted-Job drill (waiting, untouched)
The pin is tests/drills/test_failure_drills.py:304-306: `("failed", "exit 1", [("train", "failed", "exit 1")])`. It changes when:
1. platform-w5 merges: `Pod.error` does not exist in packages/providers/base.py at 5354f75; its `wait()` sets `"<STATE> <code>: <message>"` (test string `FAILED ContainerFailed: exit code 1, see <url>`).
2. backend-w5 builds the node error from `pod.error`.
3. The drill's fake provider (`Nodes.wait`, same file, line 71) sets `pod.error` on a non-zero exit the way NebiusProvider does, and the pin takes backend-w5's final wording.
Orchestrator: tell qa when both are merged; it is a one-line pin plus the fake's `pod.error`, tests only, no apps/ edit.
