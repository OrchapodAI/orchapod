# Wave 3b — data-w3 report (role data-engineering)

**Status: DONE.** Both items are implemented and tested, and `make check` is green. No keys were set, so STUB and MockTransport prove the code. **Cost: $0.**

**Branch:** `hack/data-w3`, in the worktree `.claude/worktrees/data-w3`. `git merge-base --is-ancestor 1c0b746 HEAD` passes; the branch head sits on 10168de.

| Commit | What |
|---|---|
| 13e4685 | fix(data-prep): the data-w1 review minors |
| 475fcc3 | feat(data-prep): `quality_filter` (Nemotron 3.5 Lightning, guided JSON score 1–5, drop < 3) |
| 8ddc94d | test(data): intent #1 data half end to end through the real SDK |
| c4e0174 | docs(data-prep): split wording fix (one-row sources) |

Files changed: `containers/data-prep/{run.py,Dockerfile}`, the data-prep block of `packages/workflow_schema/models.py`, `docs/WORKFLOW_SPEC.md` (the data-prep line), `tests/containers/test_data_prep.py` and `tests/containers/test_synth_distilabel.py`.

## Item 1a: `quality_filter` (475fcc3)
- **Input.** `DataPrepInputs.quality_filter: bool = False`. Its description tells the planner the cost (about $0.01 per 300 rows) and that STUB skips it. The registry description mentions the option.
- **Where it runs.** It is the contract's step order: … → near dedupe → quality filter → split.
- **The call.** One call per row, `TokenFactory(on_usage=cost.add).chat([...], LIGHTNING, json_schema=SCORE, thinking=False, max_tokens=64)` at temperature 0.
  - `SCORE` is `{"score": {"type": "integer", "enum": [1,2,3,4,5]}}`, all fields required, no extra keys.
  - Rows under 3 are dropped. `quality_dropped` counts them.
- **R18 fencing.**
  - The row's turns are fenced as `<example>`, and its `context` (the scraped passage), when present, as `<passage>`.
  - Any `<passage` or `<example` tag start is stripped from that text, repeating until none is left, so a nested `</exa</example>mple>` cannot rebuild a tag.
  - The "untrusted data" line and the rubric come after the fences.
  - A grounded row adds one sentence: an answer the passage does not support scores 1.
- **Errors**, per the data-node shared rule:
  - `auth`, `bad_request` and `quota` are fatal: `log.error(str(e))`, then exit 1, with no outputs.
  - `rate_limit`, `server` and `bad_output` (after the client's retries) keep the row unscored and count in **`failed_calls`**, a new metric. A reply without a 1–5 integer (including `true` and `9`) counts as `bad_output`.
  - If the filter drops every row, the 0-rows fatal error says so.
- **STUB and format.** STUB skips the filter and logs "STUB: quality filter skipped". `format: structured` warns and keeps its rows.
- **Only `true` or `"true"` turns it on**, so a form's `"false"` never starts paid calls.
- **Image.**
  - Adds `COPY packages/providers /app/packages/providers` and `pip install "httpx==0.28.*"`.
  - `pandas` and `pyyaml` leave the explicit pip list: run.py imports neither, and `datasets` still pulls both in.
  - Built for real; `import run` works in the image (httpx 0.28.1, datasets 5.1.0).
- **Speed.** Calls run one at a time. The `ponytail:` comment names the ceiling (300 rows ≈ 2 min) and the thread-pool upgrade.

## Item 1b: data-w1 review minors (13e4685, c4e0174)
1. **Unhashable role.** `tf_valid` now requires a string role, so a list or dict role is invalid instead of raising TypeError. The fix is in the shared predicate, so every caller is covered.
2. **CSV.** It is read with the stdlib `csv` module instead of `pandas.read_csv(keep_default_na=False)` (DECISION 1).
   - Every cell stays text, so a blank alpaca `input` stays `""` and `"NA"` stays `"NA"`.
   - Numeric answers (`4`) are no longer coerced to int, which used to drop them.
   - A ragged row (extra cells) is skipped instead of crashing the node.
   - pandas is absent from CI and the venv, so the CSV path was untestable before.
3. **Small n.**
   - The `split` docstring, the `test_split` description and WORKFLOW_SPEC now say that each split is rounded, so a few rows can leave test empty (n=5 at 0.9/0.1 → 4/1/0), and that a source needs about 1/share rows to reach eval and test.
   - Measured: one-row sources stay in train only while they are at most 2 × train − 1 of the rows (60 % at 0.8). Beyond that, the excess spills into eval and test.
   - A requested test split that rounds to 0 now logs a warning naming the cause. Otherwise judge-eval would fail later with a bare "no test rows".
   - Tests pin the n=4/5/12/20 sizes and one-row sources.
4. **Log before near dedupe.** "N rows loaded, M valid and distinct" is logged before near dedupe, which can take minutes.
5. **Test gaps closed:**
   - missing dataset (fatal);
   - CSV;
   - eval/test composition (each 5-row source's held-out row is in exactly one of eval and test);
   - small n and one-row sources;
   - the fixture now serves its input from its own directory, under the URI's last segment, as `io.download_input` names it.

## Item 2: intent #1 data half end to end in STUB (8ddc94d)
`test_intent1_data_half_through_the_real_sdk` replaces the old STUB chain test. Here is what it does:
- It reads `apps/api/agent/templates/1-real-estate-compliance.json` and runs its three data nodes with their template inputs: research, then synth, then prep.
- Every node goes through the **real `orchapod.io`**: `read_inputs` from `ORCHAPOD_NODE_INPUTS`, plus `write_output`, `write_metrics` and `download_input`. Only the S3 calls (an in-memory bucket) and the control-plane POST are replaced.
- Each node gets the URIs its upstream node registered. Refs are resolved with the executor's `_REF` pattern.

It asserts:
- 20 passages from 20 URLs;
- every synth row's `(context, source_url)` is a corpus passage;
- prep's outputs: `dataset` == synth rows, and train/eval/test **16/2/2** (0.8/0.1/0.1);
- train and eval rows are `{"messages"}` only and TF-valid;
- test rows keep `context` and `source_url`;
- the registered kinds, and the metrics carrying `stub: true`.

**Why a second case exists.**
- **Gap:** the STUB teacher answers one pair per passage, so every source has one row, and the split's `source_url` stratification is invisible.
- **Second case:** synth alone gets a five-pair MockTransport teacher, as a live one would. That gives 100 rows: **80/10/10**, and every source puts exactly 4 rows in train and 1 in eval or test.
- **Mutation check:** a `split()` that ignores `source_url` fails only this case.

## Proof (commands and output)
- **`make check`** (worktree head c4e0174): exit 0.
  - `ruff`: "All checks passed!"
  - pytest: `537 passed, 126 warnings` (baseline 510 passed; warnings unchanged).
  - web: `pass 12, fail 0`.
  - The stub e2e prints `SKIP` (E2E=1 is orchestrator-only).
- **Mutation check:** each guard was removed in turn, and a test failed every time. 16 mutations, all caught:

| Mutation | Caught by |
|---|---|
| fence not stripped | the fence test |
| `>= 3` changed to `> 3` | the drop test |
| `thinking=False` removed | the request-body test |
| auth not fatal | the fatal test |
| bool score accepted | the failure test |
| a truthy `"false"` runs the filter | the "false" test |
| no STUB skip | the STUB test |
| failed-call rows dropped | the failure test |
| unhashable role crashes | the TF-rules test |
| ragged CSV row kept | the CSV test |
| no empty-test warning | the warning test |
| rubric moved before the fences | the fence test |
| split ignores `source_url` | the intent #1 five-pair case |
| synth drops `source_url` | both intent #1 cases |
| train keeps `context` | both intent #1 cases |
| web-research fetches 1 page per query | both intent #1 cases |

- **Real containers.**
  - Setup: images built from this worktree under private tags, now removed. They ran the template's three data nodes in STUB against compose MinIO with the real SDK (scratchpad script `intent1_containers.py`).
  - research: exit 0 in 1.4 s. 20 passages from 20 pages. cost_json: tavily/search, 5 calls, $0.
  - synth: exit 0 in 1.0 s. 20 grounded rows from 20 calls, `stopped: exhausted`.
  - prep, with `quality_filter: true`: exit 0 in 1.1 s.
    - Log: "20 rows loaded, 20 valid and distinct", then "STUB: quality filter skipped …", then 16 train / 2 eval / 2 test.
    - Test rows keep `context, messages, source_url`; train rows keep `messages` only.
    - metrics: `{"stub": true, "total": 20, "train": 16, "eval": 2, "test": 2, …, "quality_dropped": 0, "failed_calls": 0, …}`.
  - prep_nokey (real mode, no `NEBIUS_API_KEY`, filter on): exit 1 in 0.9 s. The last line is `[ERROR] token_factory auth None: NEBIUS_API_KEY is not set`, and cost_json is still written.

## DECISIONs to record
1. **CSV is read with the stdlib `csv` module, not pandas.** The brief's `keep_default_na=False` would have fixed only the NaN problem.
   - Gain: no NaN; numeric answers are kept; ragged rows are skipped instead of crashing; the path is testable in CI.
   - Cost: a structured CSV's numeric columns arrive as strings, so the stats card shows no min/max for them. That path is off the demo path; intent #2 reads synth's JSONL.
2. **data-prep metrics add `failed_calls`.** It is the count the data-node shared rule already requires, as R18 did for web-research. Please add it to the contract's data-prep metric list.
3. **A failed scoring call keeps its row.** The row is counted and logged as a warning. Dropping it instead would turn a Lightning outage into "0 rows, fatal". A user who asked for the filter sees `failed_calls` > 0 if it degraded.
4. **The quality filter scores the row together with its passage,** so a grounded answer the passage does not support scores 1. Prompt and schema details are in Item 1a.
5. **An empty requested test split logs a warning; data-prep does not guarantee a test row.** Guaranteeing one is a small change to `split()` if wanted.

## For the Orchestrator and other agents
- **Ruling wording (LOG, 2026-10-20).** It says "(every source in every split)". That holds only for sources with about 1/share rows (≥ 10 rows at 0.1). One-row sources stay in train while they are at most 2 × train − 1 of the rows.
- **Template suggestion (backend owns `apps/api/agent/templates`).**
  - Intent #1's prep could set `"quality_filter": true`: about $0.013 and 1–2.5 min for 300 rows (estimate, not measured).
  - For backend-w3's reduced-scale "Run it yourself": test_split 0.1 needs at least 6 rows to reach data-prep. In STUB that means `max_pages` ≥ 6, since each page gives one row.
- **Shared fence helper.** The same 4-line `fence()` now lives in synth (`passage|reference`) and data-prep (`passage|example`), and judge-eval (ml-w3) needs one too. It could move to packages/providers (platform) if you want one copy.
- **Spike 2 should check three things on Lightning:** `chat_template_kwargs.enable_thinking=false`, a `json_schema` with an integer `enum`, and `max_tokens` 64.
  - If Lightning ignores the flag, every reply truncates. Every call then fails as `bad_output`, rows are kept unscored, and `failed_calls` equals n, which is visible but not useful.
- **The shared `orchapod/data-prep:dev` image is stale** (it predates this branch). `make check E2E=1` rebuilds it after the merge. The intent #2 path is unaffected.
- **MinIO leftovers.** 13 small check objects remain under `runs/data-w3-check-1792548526/`. Nothing was deleted.
- **Frontend (optional).** A `quality_filter` toggle on the data-prep form would expose the option. Structured rows skip the filter, so the intent #2 stats card is unchanged.

## Not done or open
- Live Lightning scoring is unverified (no keys): the score distribution, latency, and whether `enum` and `thinking=False` are accepted.
- Remaining review minors outside the brief's list:
  - `fields.top` can push a text-heavy structured dataset's metrics past 16 KB;
  - the `DataFormat` enum alignment in models.py;
  - unpinned `datasets`.
- Sequential scoring takes about 0.4 s per row, so 15k rows would hit the 5,400 s node timeout. The thread-pool upgrade is marked `ponytail:` in the code.
