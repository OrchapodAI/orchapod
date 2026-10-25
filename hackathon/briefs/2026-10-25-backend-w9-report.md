# backend-w9 report (2026-10-25, round 3)

Status: DONE_WITH_CONCERNS. Branch hack/backend-w9, NebiusHackathon (22a6ee7) merged in. Spend $0: no model or Nebius call, no .env sourced, no e2e, no ui-smoke, no subagents.

## Commits
- Round 1: 94ba9be contracts · 8d29c48 persisted logs · 4250007 summary `provider`/`resource` and the run header.
- Round 2 (after the merge 3ce7ed4): 8d236a5 contracts · 5e532f3 `services/logs.py` · f7867b4 seeded logs · b3f0c61 endpoint state (a) by name and (b) through the keep-alive window.
- Round 3: 3ae2786 contracts · b23117a redaction, cleaning, field limits (I1, M3, M4) · b1a11ff Nebius reads and a superseded endpoint (I2, M6, M7).
- The report commit follows. Each round-3 commit is green on its own (snapshot runs with drills, docs and the vllm-serve container tests: 314, 331, 334; ruff clean).

## Rounds 1 and 2 in brief
`GET /runs/{id}/logs` over table `node_log` (cut at 2000 chars, R22-redacted, the last 5000 per run); the summary's per-node `provider` and `resource` (a Job, or vllm-serve's endpoint found by `orchapod.names.endpoint_name` while it runs and read through the keep-alive window; state cached 30 s, capped 3 s, null on error, never under STUB); `RunOut.gpu_provider` = the first GPU-renting node's provider; `make demo` seeds the golden run's log lines (PROGRESS left out) through the same `clean()` and `keep()`.

## What changed in round 3
- **I1: `redact_text` scans.** `_PAIR` consumed a whole value, so a pair inside a non-secret value was never looked at. It now loops over `_PAIR.search`: after a non-secret pair it resumes at the value (`m.start(3)`), after a secret one it splices `[redacted]` and continues at `m.end()`; no recursion. Two passes follow for what no key names: `(?i)\b(bearer|basic)\s+[\w.~+/=-]{8,}` and `(?<=://)[^/\s@:]*:[^/\s@]+(?=@)`. All eight shapes of the review (and a nested JSON line, `redis://:pw@…`, a `Basic` header) come out redacted and stay so when applied twice.
- **I2: a pool of its own and one read in flight per key.** Reads run on `ThreadPoolExecutor(2, "nebius-read")`. A read that outlives the 3 s stays the key's one flight: the next poll after a cache lapse waits for it again (shielded) instead of starting another; `_landed` frees the key when it ends, keeps an answer that came late, and asks the future for its exception so none is "never retrieved". A failure is cached as before.
- **M3: `clean()`** drops NUL and turns a lone surrogate into `?`. Found on the way: a lone surrogate broke the insert on SQLite too (the probe raised `UnicodeEncodeError`), so it was a 500 anywhere, and only NUL was Postgres-specific.
- **M4:** `max_length` 128 (`node_id`), 64 (`ts`), 16 (`level`) on `LogEvent` (422 beyond) and on `NodeLog` (VARCHAR on Postgres).
- **M6:** the keep-alive read uses `internal._live()` and `_expiry()`, so a deleted or superseded registration is not read.
- **M7:** the faked Nebius (`Serverless`, `nebius`) lives in `tests/api/conftest.py`; test_redact no longer imports it from test_executor. The fixture also resets `_flights` and the guard still fails any test that reaches the real client.

## Evidence
- `pytest tests/api -q` x5, clean env: `259 passed` five times (239 + 20 new: 12 redaction shapes, 1 prose/recursion, 1 NUL and surrogate, 3 limits, 3 pool and flight).
- `make check` (no E2E): exit 0; ruff "All checks passed!"; `1158 passed, 2 warnings`; web `pass 38 fail 0`. No new lint finding in a touched test file.
- Mutation check, 17 breaks (scan skipping values, no Bearer pass, no URL pass, Bearer minimum 1, secret not spliced at the value, default executor, a read per lapse, late answer dropped, key never freed, failure uncached, NUL kept, surrogate kept, each of the three request limits, the table limit, superseded endpoints read): all caught.
- Redaction cost, measured: 6 ms on 2,000 characters of `a:a:a:…` (the worst case, quadratic), 91 ms at 8,000, 1.4 s at 32,000; hence `clean()` cuts first.
- Postgres 16 (compose, scratch database, dropped): `node_log.node_id/ts/level` are VARCHAR 128/64/16; Postgres refuses NUL and a 129-character `node_id` natively; through the route NUL gives `ab`, a lone surrogate `x?y`, a 65-character `ts` a 422; 16 writers x 100 lines on one run with keep 500 leave exactly 500 (ids strictly increasing, no error) while a second run alongside keeps its 200.

## Concerns
1. **False positives, as specified:** `Bearer`/`Basic` followed by any 8+ word characters is redacted, so prose such as "basic configuration" becomes `basic [redacted]`. Cheap to narrow (require a digit or a symbol) if that costs more than the leak it prevents.
2. **A URL password needs a colon:** `user:pw@host` is covered; a token alone as userinfo (`https://TOKEN@host`) is not.
3. **Two pool threads:** two hung keys hold both; a third read queues, its poll gives up at 3 s with null, and it runs when a thread frees.
4. Unchanged from round 2: the hosted API gains the table at its next start and `make demo` must run again for the golden run's lines; by name, a still-listed (DELETING) endpoint of an earlier attempt can show for one cache window; `endpoints.list()` pages the whole project once per 30 s per running serve node; container stdout is not stored; a retried node briefly shows its previous Job id.
