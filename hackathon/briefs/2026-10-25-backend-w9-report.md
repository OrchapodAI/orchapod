# backend-w9 report (2026-10-25, round 2)

Status: DONE_WITH_CONCERNS. Branch hack/backend-w9; NebiusHackathon (22a6ee7) merged in, no conflicts. Spend $0: no model or Nebius call, no .env sourced, no e2e, no ui-smoke, no subagents.

## Commits
Round 1 (reviewed): 94ba9be contracts · 8d29c48 persisted logs · 4250007 summary `provider`/`resource` and the run header · 1dc9f5c report.
Round 2, on top of the merge 3ce7ed4:
- 8d236a5 docs(contracts): endpoint state (a) and (b), the header's two accepted cases, seeded logs, the one endpoint-name function.
- 5e532f3 refactor(api): `apps/api/services/logs.py`: `clean()` (cut, redact, cut) and `keep()` (add lines, trim to the last 5000), used by `/internal/log`. No behaviour change.
- f7867b4 feat(demo): `seed()` stores each node's `logs` artifact through the same `clean()` and `keep()`.
- b3f0c61 feat(api): the serving endpoint's state, (a) by name and (b) through the keep-alive window.
- The report commit follows. Each commit is green on its own (snapshot runs: 283, 283, 285, 288 tests incl. drills and the vllm-serve container tests; ruff clean).

## What changed in round 2
1. **Endpoint state (approved fix 1).**
   - (a) A `running` vllm-serve node with no `endpoint_url` artifact is looked up by name in `endpoints.list()` (not `find()`: it sleeps 0, 15 and 30 s on a miss). The summary then shows `{"kind": "endpoint", "id", "state"}` with PROVISIONING, IMAGE_PULLING, STARTING, RUNNING; null while Nebius lists no such name.
   - The name comes from one function, `orchapod.names.endpoint_name(run_id, node_id)` (packages/sdk-py, which both the API image and the node image ship). vllm-serve had the expression inline in `main()`, with nothing to import, so I moved it there and `containers/vllm-serve/run.py` now calls it (three lines: the import, the call, and the `import re` it left unused; ml's file, as "reuse vllm-serve's naming function" required). A test asserts `load_container("vllm-serve").endpoint_name is endpoint_name`, and the lookup test uses the node id `Serve_8B`, whose name differs from a hand-derived one.
   - (b) A registered endpoint's state is read while its artifact's `meta.expires_at` is in the future and `meta.deleted_at` is unset, whatever its node's status. Same cache, cap and STUB guard as before: all reads now go through one helper, `_read(key, fetch)` (30 s per key, 3 s, null on error, failures cached too).
2. **Seeded golden-run logs (approved fix 2).** The live fixture (d20d30f3) yields 15 lines over 6 nodes. `seed()` also clears the run's old lines, so seeding again replaces them. Export is untouched.
3. **Header label left as is**, and both accepted cases named in the contract line.

## Evidence
- `pytest tests/api -q` x5, clean env: `239 passed` five times (234 + 5 new: 2 name lookup, 1 keep-alive, 2 seed).
- `make check` (no E2E): exit 0; ruff "All checks passed!"; `1138 passed, 2 warnings`; web `pass 38 fail 0`.
- Mutation check, 17 breaks of the new behaviour (container re-derives the name, no lookup, wrong name, matches any endpoint, no 3 s cap, no STUB guard, keep-alive: read only while running / always / ignoring expiry / ignoring `deleted_at` / compared backwards, seed keeps PROGRESS / skips cleaning / does not trim / does not clear / stores nothing / wrong order): all caught. One survived at first: a hand-written f-string equals `endpoint_name` for the id `serve`, so the test now uses `Serve_8B`.
- Real client class, mocked transport: my lookups run through the actual `NebiusServerless` over `httpx.MockTransport` replies shaped like Nebius's REST (a two-page endpoint listing, `endpoints.get`, `jobs.get`): name found on page 2, ids and states right, bearer header sent. Nothing touched the real API.
- Postgres 16 (the compose one, scratch databases, all dropped): the real `seed()` stores the 15 lines over 6 nodes (218 ms; 87 ms the second time, no duplicates, no PROGRESS); a 7000-line bulk through `keep()` leaves exactly lines 2000..6999 in 343 ms.

## Decisions (for the Orchestrator to record)
1. Seeded logs leave out `PROGRESS` lines. The SDK's `logs` file holds them, but they went to /internal/progress, which stores nothing: 250 of the fixture's 263 lines are `step=N/M phase=…`, and a live run's history has none, so the seeded Logs tab shows the 15 real lines instead of burying them. One condition in `_log_lines` (scripts/seed-golden-run.py) if you want them.
2. The endpoint name's single source is `orchapod/names.py` in the SDK, not packages/providers (platform's file). NebiusServerless is untouched.
3. Seeding moves `r2://` URIs to the hosted bucket in log lines too, like the rest of the fixture (a checkpoint line reads `r2://<hosted bucket>/runs/…`).

## Concerns
1. **Hosted rollout:** the new table appears at the API's next start; `make demo` must run again on the hosted app for the golden run to get its lines. The vllm-serve node image need not be rebuilt for this change: the old image names endpoints identically; a rebuild picks up `orchapod/names.py` with the rest of the SDK.
2. By name, a still-listed (DELETING) endpoint of an earlier attempt of the same node can show for up to one 30 s cache window before the new one exists.
3. `endpoints.list()` pages through every endpoint of the project, once per 30 s per running serve node.
4. Container stdout (STDOUT events) is still not stored; a retried node briefly shows its previous attempt's Job id (round 1 notes, unchanged).
