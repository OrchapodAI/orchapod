# backend-w8 report (2026-10-22)

Status: DONE_WITH_CONCERNS. Branch hack/backend-w8, base 6ba382f (ancestor check passed). Spend $0 (no network, no .env sourced, no e2e, no ui-smoke, no subagents).

## Commits
- 243269b docs(contracts): one sentence, Run state machine > Runtime (the executor's placement rule).
- 1a31a59 test(api): an autouse `no_stub` fixture in tests/api/conftest.py (see Decisions 2).
- 446b8b2 feat(executor,agent): the change itself, with its tests.
- The report commit follows.

## What changed (production: 2 files, +6/-4; contracts +1/-1; tests +61)
- apps/api/executor/run_workflow.py `_execute_node`: `local = runtime in ("cpu", "api") or config.env("STUB") == "1"`; `pick_local_docker if local else pick_provider`; `bill = None if local else ...`. Without STUB `local` is exactly the old test, so the `pick_provider` path, its `no gpu provider: ...` error and the wall-time bill are unchanged.
- apps/api/agent/planner.py `_node_problems`: the "no GPU provider ... configured" check gains `config.env("STUB") != "1" and`. Without STUB the condition is unchanged.
- Untouched, as briefed: budget.py (`gpu_nodes`, `gpu_guard`), provider_selector.py, the executor's `scale < 1` admin-only refusal, `fits`.

## Tests (the new STUB assertions failed before the change, pass after)
- tests/api/test_executor.py `test_stub_runs_a_gpu_node_on_local_docker_and_bills_nothing`, parametrized over the existing `provider` and `gpu` fixtures: without STUB the unsloth-train node lands on the GPU provider and the run costs $2.25 (30 min of H100, as today); with STUB it lands on LocalDocker, the GPU provider sees nothing, and the run costs $0.
- tests/api/test_agent.py: `test_stub_reviews_the_docs_specialist_with_no_gpu_provider_and_only_stub` (template 4, full and reduced plan, no provider: the exact old error without STUB, `[]` with it); `test_stub_plans_the_docs_specialist_clean_but_only_the_admin_runs_it` (POST /agent/plan under STUB: `errors == []`; POST /agent/run: anonymous 403, admin 201).
- tests/api/test_budget.py: the existing executor admin-only test gains a STUB twin (scale 0.1 still fails with `admin only: unsloth-train runs on a rented GPU`, before any provider).

## Evidence
- `pytest tests/api -q` x5, clean env: `223 passed` five times (baseline was 219; +4 cases).
- `make check` (no E2E; PY and PATH pointed at the shared venv): exit 0; `ruff check apps packages containers` "All checks passed!"; `904 passed, 2 warnings`; web `pass 30 fail 0`; "SKIP stub e2e".
- Ambient STUB: `env PATH=/usr/bin:/bin STUB=1 pytest tests/api tests/drills` (no docker on PATH): `236 passed`.
- Template 4 end to end under STUB (a throwaway scratch test on the drills' fixtures, deleted, not committed): reduced plan, admin, through /runs/start: six nodes succeeded, `cost_usd 0.0`, GPU provider pods `[]`, `train-4` on the local provider, no executor-billed cost_json, unsloth-train artifacts `cost_json, logs, lora_adapter, metrics_json`. tests/drills/test_docs_templates_stub.py still passes (its unsloth-train now runs on the local fake).

## Decisions (for the Orchestrator to record)
1. DECISION: under STUB=1 every node, gpu included, runs on LocalDocker with no wall-time bill; plan review skips the GPU-provider check under STUB only; gpu_guard, fits and the executor's admin-only refusal are unchanged. Deviation from the brief's wording ("the quote is $0, so billing stays $0"): I skip the executor bill for any local run, as for cpu and api, instead of computing a $0 one. Reason: the $0 bill would still write a cost_json row with uri `local-docker:<id>` and `gpu_hours` > 0 for a node that used no GPU. Net effect is the same $0. Cost if wrong: one more `cost_json` row per STUB gpu node (change `bill = None if local` back to the runtime test).
2. `no_stub` autouse fixture (tests/api/conftest.py, 4 lines): with STUB=1 in the caller's shell nine existing tests failed, and `test_provider_selection` (which fakes no local provider) reached the real Docker daemon. That happened once during my sensitivity run: `docker run` failed at image lookup (`Unable to find image 'ghcr.io/bangadpurva/unsloth-train:latest'`, exit 125); no container was created (`docker ps -a --filter label=orchapod.run_id` was empty afterwards). I did not repeat it; later ambient-STUB runs had no docker on PATH.
3. Commit trailer: the task message asked for `Claude Opus 5.5`; my role file says to use the trailer the harness attribution reminder gives, which names this session's model, `Claude Sonnet 5.5`. I used that. Reword at merge if you want the other.

## Concerns (why DONE_WITH_CONCERNS)
1. The stub stack has no `orchapod/unsloth-train:dev`, and building it is the real blocker for qa-w8. containers/unsloth-train/Dockerfile is the CUDA image (FROM pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel, a 203-pin x86_64 lock, mamba and causal-conv1d x86_64 wheels, about 20 GB). `scripts/e2e_demo.py build_images` would run it for template 4 on an arm64 Mac. The STUB path needs only the SDK and boto3: run.py imports torch, unsloth, datasets and trl lazily, inside `train()`. Suggest an ml-engineering Dockerfile target (or a small STUB-only image) that the e2e builds; I did not touch containers/ or scripts/.
2. scripts/e2e_demo.py `MUST_REGISTER` has no `unsloth-train` entry (qa-w8 adds `lora_adapter`).
3. tests/drills/test_docs_templates_stub.py: the last docstring sentence ("The Docker stub e2e cannot run them: its plan review refuses unsloth-train ...") is now false. Not edited (qa's file, "don't depend on it").
4. Admin-only is by design: the smoke's main API (full caps, anon scale 1) passes `gpu_guard`; the public-scale API (0.1) still answers 403 to /agent/run for template 4 and `fits` stays false.
5. `ruff check tests scripts` reports 23 findings (15 F811 fixture re-imports, 3 E402, 3 F401, 1 E401, 1 F841) in 7 test files; they are outside `make check`'s lint scope (apps, packages, containers), and per-file counts in the files I touched are the same as at the base (test_agent 4, test_budget 11, the others 0).
