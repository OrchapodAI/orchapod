# Wave 1 report — data-w1 (data-engineering) · 2026-10-20

**Status: DONE.** Merge it after backend-w1 or together with it, because data-prep calls backend's new `io.write_metrics`.
Branch `hack/data-w1`, based on 178d2e6 (`git merge-base --is-ancestor 178d2e6 HEAD` passes). Commit: **a623fe6** `feat(data-prep): contract v1 — r2 routing, hf config/split, qa/structured, dedupe, test split`. Nothing pushed. Spend: **$0** (no API calls).

## What changed (4 files, +414 −125)
- `containers/data-prep/run.py` (rewritten, 210 lines). It implements contracts "Data nodes → data-prep":
  - **Loading**
    - `r2://` is tested first. Before this fix, `or` bound looser than `and`, so r2 URIs reached the Hugging Face loader.
    - Objects are read as UTF-8 JSONL unless the name ends in `.csv`, so extensionless artifacts load. A malformed JSONL line counts as `skipped` instead of crashing the node.
    - `hf://<id>` and `<org>/<name>` go to `load_dataset(repo, name=hf_config, split=hf_split)`, so `test[:50]` works.
    - With `STUB=1`, a Hugging Face load becomes 20 fixed rows in the requested format and makes no network call. r2 and local loads run their normal path.
  - **Formats**
    - `chatml`, `alpaca`, `sharegpt` (a `system` turn now stays `system`; before, it became `assistant`) and `qa` (`question` → user, `answer` → assistant, verbatim) become `{"messages": [...], **other keys}`.
    - `structured` keeps each dict row as it is.
  - **Validation:** chat rows must pass the Token Factory rules:
    - roles are system, user or assistant, and system appears only first;
    - there is at least one user turn;
    - the last turn is the assistant's;
    - every content is a non-empty string.
    Rows that fail are dropped and counted in `skipped`.
  - **Dedupe:**
    - Exact: canonical JSON of the cleaned row.
    - Near (chat only): char 5-gram Jaccard ≥ 0.9 on the normalised first user turn (lowercase, collapsed whitespace). The first occurrence is kept.
  - **Split:** seed 42, stratified by `source_url`:
    - Each source's rows are shuffled and spread evenly over one global order. That order is cut into train, eval and test.
    - Global counts are `round(n·train)`, `round(n·test)` (capped), and eval takes the rest.
  - **Outputs:** `dataset`, `train_jsonl`, `eval_jsonl` and `test_jsonl` are always written (empty if need be).
    - `dataset` holds every cleaned row and `test_jsonl` holds full rows (so it keeps `context` and `source_url`).
    - Train and eval chat rows are reduced to `{"messages"}`; structured rows are unchanged.
    - The `stats_json` output is gone (nothing read it).
  - **Metrics:** `io.write_metrics` gets exactly the contract keys: `total, train, eval, test, skipped, exact_dupes, near_dupes, quality_dropped (0 until wave 2), avg_length_chars, max_length_chars, fields`.
    - `fields` exists for structured data only (null otherwise). Per field it gives `{distinct, nulls, top[[v, c] ×≤10]}`, plus `min`/`max` for numeric and ISO-8601 fields.
  - **Fatal errors:** an unknown format, a missing `dataset` and 0 rows after cleaning each do `log.error` and then exit 1.
- `packages/workflow_schema/models.py` (data-prep block, its `DataFormat` enum and the pydantic import line):
  - `DataFormat` gains `qa` and `structured`.
  - `DataPrepInputs` adds `hf_config`, `hf_split` and `test_split` (≥ 0), with a validator requiring train + test ≤ 1.
  - `DataPrepOutputs` = `dataset, train_jsonl, eval_jsonl, test_jsonl`.
  - The registry description is updated.
- `tests/containers/test_data_prep.py` (new, 22 tests).
- `docs/WORKFLOW_SPEC.md` (one line): the data-prep entry now describes inputs, formats, cleaning, split and outputs.

No Dockerfile was touched (R19). `quality_filter` is left out (wave 2), and with it the per-batch `log.progress`, since data-prep has no batches without the filter.

## Proof
1. `make check` (venv on, in the worktree):
   - Ruff passes ("All checks passed!").
   - **175 passed**, against 153 at base (22 new).
   - The stub e2e is skipped because qa has not written it yet.
2. TDD: before any implementation, all 22 new tests failed (`22 failed in 0.57s`).
3. Mutation check: I re-introduced each bug and ran the data-prep tests. Every mutant is caught:

| Re-introduced bug | Result |
| --- | --- |
| old r2 routing (`or`/`and` precedence) | 5 failed |
| extension required | 5 failed |
| no STUB short-circuit | 1 failed |
| no near dedupe | 1 failed |
| split not stratified | 1 failed |
| `hf_split` ignored | 1 failed |
| train rows keep extra keys | 1 failed |
| system allowed anywhere | 1 failed |

4. Real-process runs against the compose MinIO, with the real SDK and boto3:
   - Setup: wrapper `scratchpad/prep_check/run_prep.py` shims only `io.write_metrics`, because backend-w1's version has not landed yet.
   - Run 1 (`STUB=1`, intent #3 wiring: `hf://openai/gsm8k`, `main`, `test[:50]`, `qa`, test 0.1) gave 20 rows: 18 train / 0 eval / 2 test, with no network.
   - Run 2 (`r2://orchapod-artifacts/runs/data-w1-check/prep_stub/dataset`, extensionless, no STUB, 0.8/0.1) gave 16 / 2 / 2.
   - Run 3 (structured movie rows, intent #2 shape) gave 27 / 3 / 0, with `fields` for all 5 fields.
   - 12 objects were uploaded under `runs/data-w1-check/`.

## Notes for the Orchestrator
- **Merge order:** data-prep calls `io.write_metrics` (contract; backend-w1's SDK). Until that lands, a real run writes all four outputs and then raises AttributeError at the end.
- **DECISION to record: what "stratified by source_url" means.** I read it as proportional: every source contributes to train, eval and test, so test questions come from passages that also fed training. That fits closed-book intent #1 (the tuned model should know the domain). If ml or the Orchestrator wants test questions from unseen sources (a grouped split), it is a small change in `split()`.
- **DECISION to record: the TF chat rules are the validation gate for every output,** not only for train and eval. Rows judge-eval cannot use (last turn not the assistant's) never reach `dataset` or `test_jsonl`.
- **The defaults leave eval empty:** with train 0.9 and test 0.1 there is no eval split. This matches the contract; judge-eval plans use 0.8 / 0.1, and tf-finetune treats an empty `eval_jsonl` as no validation file.
- **Frontend (wave 2):** the canvas data-prep form (`apps/web/app/canvas/[id]/page.tsx` defaults) does not yet expose `qa`/`structured`, `test_split`, `hf_config` or `hf_split`. The planner sees them through `NODE_REGISTRY` already.
- **Near-dedupe ceiling:** it is O(n²) over kept rows, and the `ponytail:` comment in the code records it. Measured worst case: 1k rows ≈ 0.8 s, 5k ≈ 18 s, 15k ≈ 140 s. The upgrade path is prefix filtering or MinHash LSH if HF-scale inputs matter.
- **STUB ignores split slices:** it returns 20 fixed rows whatever `hf_split` asks for.
- **CSV loading is unchanged** (pandas; empty cells become NaN). It is not on the demo path.
- **`cost_json`/`metrics_json` are not listed in `DataPrepOutputs`.** They are SDK-level outputs of every node, so backend decides whether a shared base model lists them.
- **Dev MinIO state:** it had no buckets. I created `orchapod-artifacts` (what the API's `ensure_bucket` does on startup) and left the 12 small check objects under `runs/data-w1-check/`. Nothing was deleted.
