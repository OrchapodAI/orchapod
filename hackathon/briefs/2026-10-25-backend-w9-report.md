# backend-w9 report (2026-10-25)

Status: DONE_WITH_CONCERNS. Branch hack/backend-w9, base 8b17ab0 (ancestor check passed). Spend $0: no model or Nebius call, no .env sourced, no e2e, no ui-smoke, no subagents.

## Commits
- 94ba9be docs(contracts): the binding lines frontend-w8 codes against (summary fields, GET /runs/{id}/logs, what /internal/log stores, RunOut.gpu_provider, one sentence in Events).
- 8d29c48 feat(api): persisted logs: table `node_log`, `redact_text`, `receive_log`, `GET /runs/{id}/logs`.
- 4250007 feat(api): the summary's `provider` and `resource` (live state), and the run header's provider.
- The report commit follows.

## What changed (apps/ +147/-22, tests/ +256/-14, docs +4/-3)
- apps/api/models/db.py: `NodeLog` (`node_log`: int id, run_id, node_id, ts, level, message; index (run_id, id)). The node's own `ts` string is stored, so a live event and its stored line compare equal. No foreign key to run: a late line of a run this database lacks still answers 204 (an existing test posts one), where Postgres would 500.
- apps/api/services/redact.py: `redact_text(text)`: the value of a secret-looking `key=value`, `key: value` or `"key": "value"` in free text becomes `[redacted]`, by redact()'s own key rule (it calls `_secret`), so `NEBIUS_API_KEY=…`, `Authorization: Bearer …`, `x-amz-security-token=…` go, `max_tokens=512` and `api_key_env=NEBIUS_API_KEY` stay. A key starts only at a word start, so it is linear.
- apps/api/routes/internal.py `receive_log`: cut at 2000 chars, redact, cut again ("[redacted]" can be longer than a short secret: Postgres testing found a 2006-char line), insert, trim, commit, then publish. The trim is a select of the id at offset 5000 (the newest line beyond the last 5000) and a delete of ids up to it; it deletes nothing below the cap. The event and `NodeRun.error` carry the same text as the store.
- apps/api/routes/runs.py: `GET /runs/{id}/logs`; summary nodes gain `provider` and `resource`; `_live_state` (30 s cache per id, failures cached too, 3 s `wait_for` around `asyncio.to_thread`, never under STUB or for a `stub-*` id) over one lazily built `NebiusServerless` (so the IAM token the CLI signs is reused); `RunOut.gpu_provider` from `_gpu_providers` (first GPU-renting node by `started_at`; one query for the whole `GET /runs` list). `_run_out` takes the provider as a required argument.
- NebiusServerless, budget.py, the executor: untouched.

## Evidence
- `pytest tests/api -q` x5, clean env: `234 passed` five times (223 at the base + 11 new: 4 log, 1 redact_text, 6 summary and header). With tests/drills: 247.
- `make check` (no E2E; PY and PATH on the shared venv): exit 0; ruff "All checks passed!"; `1135 passed, 2 warnings`; web `pass 38 fail 0`.
- Mutation check: I broke 17 behaviours in turn (off-by-one trim, no delete, redaction off, no 2000 cut, no second cut, error or event left raw, newest-first, node filter ignored, TTL 0, failure not cached, no timeout, STUB fetching, fetching for every node, header = last GPU node / any node / the column); every one failed the test named for it. Files restored byte-identical.
- Postgres 16 (the compose one) in throwaway databases, since dropped (only `orchapod` and `postgres` remain): `create_all` makes `node_log` (integer id, uuid, varchar) and `ix_node_log_run_id_id`, twice with no error; the routes through the ASGI app on asyncpg gave the same answers as SQLite (trim to the last 5, node filter, unknown run 404, an unknown run's line 204, summary, header, GET /runs). 6000 sequential POSTs past the cap: mean 4.6 ms, p99 9.4 ms; the trim lookup is an `Index Only Scan Backward` at 0.6 ms with 5000 rows; `GET /logs?limit=2000` 30 ms (294 KiB).
- Next-start upgrade: a SQLite file and a Postgres database holding every table except `node_log` (plus a run row) gain the table and index through `create_all`; the row survives.

## Decisions (for the Orchestrator to record)
1. "Same R22 redaction" for a log line means R22's key rule applied to the pairs inside its text (`redact()` walks dicts and cannot see a string's keys). It also covers the live event and `NodeRun.error`, which was raw before and is public through the summary. Cost if wrong: a false positive such as `token: expired` shows `token: [redacted]`.
2. Messages are cut at 2000 chars from the head. The SDK's excepthook posts `ExcType: message` on one line, so the cut costs a long message its tail; `NodeRun.error` now shares that cut.
3. `RunOut.gpu_provider` is derived when read, not stored: it also corrects runs that already ran (the hosted golden run's header becomes "nebius"). `Run.gpu_provider` the column is still written by the executor and still read by /inference.
4. The `no_nebius` autouse guard in tests/api/conftest.py: the nebius CLI is installed on this Mac, so an unfaked test with a running Nebius node would have signed a real token. `pytest.fail` is not an `Exception`, so the summary cannot swallow it (checked with a probe test, deleted).

## Concerns (why DONE_WITH_CONCERNS)
1. **A serving endpoint's state is null in practice.** The brief's source for an endpoint id is the `endpoint_url` artifact, which vllm-serve registers just before it exits, and `state` is read only for a running node. While serve spends its ~9 minutes provisioning there is no resource at all, and after it the node is done. frontend-w8's example "Nebius Endpoint · RUNNING" will rarely show. Two fixes, both outside this brief: read the state of a not-running node's endpoint until the artifact's `expires_at`/`deleted_at` (one condition in `run_summary`), and for the provisioning window have the API look the endpoint up by its deterministic name (`orchapod-<run_id[:8]>-<node_id>`) with `endpoints.list`.
2. The golden run `d20d30f3` ran before this table: its lines were broadcast and dropped. Its per-node `logs` artifacts (the last 5000 lines each, JSONL in the bucket) still hold them. `scripts/seed-golden-run.py` exports those artifacts but does not carry `node_log` rows, so a seeded or re-exported golden run shows an empty Logs tab until it does (qa/orchestrator).
3. Container stdout (the executor's STDOUT events, e.g. a Python traceback on a LocalDocker node) is not stored, as briefed: only what /internal/log accepts. A history load shows the SDK lines but not those.
4. The header on a STUB run of a GPU template reads "GPU: local-docker" (unsloth-train ran there), and on a plan whose only GPU-renting node is vllm-serve it reads "local-docker" too (the container's provider; the GPU is the endpoint). Only plans with no GPU-renting node give null. Say if you want "local-docker" hidden.
5. A retried node keeps its previous attempt's `gpu_pod_id` until it provisions, so for a second or two its resource can show the old Job.
