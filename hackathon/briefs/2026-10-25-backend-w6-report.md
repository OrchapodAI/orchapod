# backend-w6 report: two qa-w6 findings (startup container sweep, cancel race on SQLite)

Branch `hack/backend-w6` on f5d335f (`git merge-base --is-ancestor f5d335f HEAD`: passed). Commits, oldest first:
- `a48b1e5` fix(executor): a cancel mid-statement rolls the session back before recording the stop
- `46105b5` docs(contracts): LocalDocker labels its containers; the startup sweep terminates this API's leftovers
- `9464050` fix(executor): the startup sweep terminates the node containers a dead API left behind
- `ad424d2` fix(api): SQLite runs in WAL mode, so a read a cancel cut off cannot fail the commits after it
- `196e489` docs(contracts): a cancel that lands while the executor awaits the database still ends the run cancelled

Spend: $0. No key, no cloud call, no image built and no container started (a fake `docker` CLI everywhere; one exception under "Side effects").

## Item 2: the cancel race on SQLite (a48b1e5, ad424d2)
QA's four outcomes (PendingRollbackError with the node left pending, an HTTP 500 "database is locked", a reset connection, one clean) have two root causes. Neither is "two sessions racing".

**Root cause 1 (PendingRollbackError): a missing rollback.** A cancel that lands while the executor awaits a statement is a CancelledError inside SQLAlchemy's greenlet. SQLAlchemy counts that as an exit exception, handles it as a disconnect and invalidates the connection. Inside a flush it also rolls the flush back. Either way the session refuses to write until it is rolled back. The executor's handler wrote the cancel through it anyway: `_stop` → `db.commit()` → `PendingRollbackError: Can't reconnect until invalid transaction is rolled back`. That matches QA's trace exactly (`run_workflow.py:177`, called at `:158`). The statement a start-then-cancel hits most is the first node boundary's budget check (`budget.reserve` → `refresh(run)`, `sum(run.cost_usd)`), after the NodeRun rows are committed `pending`: hence "the node stayed pending".
- Fix: the handler runs `await db.rollback()`, re-reads the run and its NodeRuns, then records the stop.
- The one piece of state that used to ride along uncommitted was the node's resolved inputs (lineage). They are now resolved and committed with `running` at the node boundary, so the rollback loses nothing. Side effect: an unresolved ref now fails the node without a `running` event first.

**Root cause 2 ("database is locked", then the reset): a read the cancel cut off keeps SQLite's read lock.** When the cancel lands after aiosqlite has stepped a SELECT (its row is being fetched), the statement stays active. SQLAlchemy invalidates and "closes" the connection, but Python 3.12's sqlite3 `close()` (`sqlite3_close_v2`) leaves a zombie until that cursor is gone, and the CancelledError's traceback keeps the cursor alive. In SQLite's default rollback journal, a held read lock blocks every writer's COMMIT, so the executor's own record of the cancel waited out the 5 s busy timeout and failed. Then the cancel route's fallback write failed the same way (HTTP 500). Uvicorn closes the keep-alive connection after an unhandled exception, so the client's next request on it was reset: that is QA's "reset".
- Fix: SQLite runs in WAL mode (`apps/api/database.py`, a `connect` listener, SQLite URLs only), where readers never block a writer. It is a no-op for `:memory:`. Postgres is not touched; there an invalidated asyncpg connection is terminated server-side, so only root cause 1 applies.
- How it was found (scratch, below): a task factory that logs every `Task.cancel()` with its caller and the cancelled task's await chain, plus pool and statement events with timestamps. A side finding: redis-py cancels its own task through `asyncio.timeout(0)` (`can_read_destructive`) on every publish. Those cancels are benign (`asyncio.timeout` absorbs them) and are not the cause.

Tests (tests/api/test_executor.py), on a SQLite file with a connection per session, set up as the API sets up its own (`database.sqlite_wal`). The cancel is delivered deterministically at a chosen statement (`before_cursor_execute`), or while that statement's rows are fetched:
- `test_a_cancel_that_lands_mid_statement_still_ends_the_run_cancelled`, 4 cases:
  - the budget read
  - the budget read while its row is fetched
  - the flush that marks the node running
  - the first INSERT (no row exists yet, as for a run cancelled before it started)
- RED before the fix, per case: 3 × PendingRollbackError (the two messages above); the fetch case `sqlite3.OperationalError: database is locked` (WAL absent). GREEN after.
- `test_cancel_during_provision_terminates_the_pod_once_it_exists` also pins the resolved inputs of a cancelled node.
- Mutations, each red and then restored:
  - no WAL pragma: 1 failed (the fetch case)
  - no rollback: 4 failed
  - no re-read after the rollback: 3 failed
  - resolution left uncommitted in `_execute_node`: the lineage pin fails

Full stack (scratch, not committed): uvicorn on 127.0.0.1:8091, a fresh SQLite file, STUB=1, the compose Redis for pub/sub, a refused R2 endpoint, a fake stateful `docker` CLI on PATH. The loop is: POST /runs, start, then cancel at once with the token; summaries are read 5 s later.

| code | cancel replies (100) | final states | executor log |
| --- | --- | --- | --- |
| f5d335f (before) | 84 × 200 cancelled, 7 × 500 (database is locked), 7 × reset, 2 × unreadable | 30 clean; **52 node left pending**; **7 runs stuck `running`**; 2 cancelled without node rows | 61 × "crashed" (PendingRollbackError), 18 × database is locked |
| HEAD | **100 × 200 cancelled** | 46 node `failed` "cancelled"; 54 cancelled before the first commit (no node rows, as for a cancel before start) | 0 PendingRollbackError, 0 locked, 0 crashed |

Still in the HEAD log: SQLAlchemy logs `ERROR sqlalchemy.pool.impl.NullPool: Exception closing connection … CancelledError` (about 25–35 per 100 instant cancels) when a cancel lands in NullPool's close at the end of a commit. It is harmless: the close is already queued in aiosqlite's thread and completes, and every run above ended correctly.

## Item 1: local node containers leaked across an API shutdown (46105b5, 9464050)
- LocalDocker (platform's `packages/providers/local_docker.py`): **only the labels changed**, three lines in `docker run`: `--label orchapod.run_id=<ORCHAPOD_RUN_ID>` and `--label orchapod.control_url=<ORCHAPOD_CONTROL_URL>`.
- The sweep (`run_workflow.sweep`, R9): after failing the runs left mid-flight, `_containers_left` lists `docker ps -a --no-trunc --filter label=orchapod.run_id` and selects each container that meets all three conditions:
  - its control_url label equals this API's `ORCHAPOD_CONTROL_URL`
  - its run is terminal (succeeded, failed, cancelled) or unknown to this database
  - the first half of the sweep is not already terminating it
- Every termination (the recorded pods as before, plus these) is scheduled together in the background with the existing `_terminate` (`docker stop -t 30`, then `docker rm -f`), so the sweep still returns before any of them starts.
- A container without the labels is never listed or parsed; a missing docker CLI returns at once; a hung `docker ps` is killed after 10 s (`DOCKER_PS_TIMEOUT_S`). Each container swept is logged at WARNING.
- Nebius side: no orphan sweep by name prefix. The `ponytail:` note on `sweep` says so: dev and hosted may share one Nebius project, so such a sweep would delete the other's live jobs and endpoints; it needs a per-deployment part in those names first.

Tests (a fake `docker` on PATH; the real LocalDockerProvider runs its stop/rm through it):
- `test_the_startup_sweep_stops_this_apis_containers_of_runs_that_are_over_or_unknown` covers six containers:
  - the running node's recorded pod: stopped once
  - a cancelled run's container: stopped and removed
  - an unknown run's container: stopped and removed
  - a pending run's container: kept
  - another API's container (another URL): kept
  - an unlabelled line: kept

  It also pins the `ps` filter.
- `test_a_docker_that_hangs_never_holds_up_the_api_start` (a fake `docker` that sleeps; the sweep finishes and logs).
- `test_node_containers_carry_their_run_and_api_for_the_startup_sweep` (tests/providers/test_local_docker.py, the `docker run` argv).
- `test_startup_sweep_fails_orphaned_runs` now runs against the fake CLI too, so no test reads the real daemon.
- Mutations, each red and then restored (8):
  - no control_url check
  - no dedupe of the recorded pod
  - pending runs swept
  - unknown runs not swept
  - no label filter
  - no `ps` timeout
  - listing after the terminations start
  - no labels on `docker run`

Full stack (scratch): start a run with the fake `docker run` taking 3 s, cancel 0.5 s later (`200 cancelled`), SIGTERM the API alone. QA's leak reproduces: one container left, labelled with the run and the API's URL. I then added another API's container and an unknown-run container, and restarted the API on the same DB and port:
- the log shows `startup sweep: terminating container … of run … (cancelled)` and `… (unknown here)`
- stop and rm were issued for both
- only the other API's container remains
- the run reads `cancelled` with its node `failed` "cancelled"

## Proof
- `ruff check apps packages containers`: `All checks passed!`
- `pytest tests -q --deselect tests/providers/test_local_docker.py::test_a_container_that_fails_at_once_keeps_its_exit_code_until_terminate`: `863 passed, 1 deselected`. The baseline at f5d335f was 857 passed; the 6 new tests are 4 parametrized cases (3 + 1), the sweep, the hang and the label.
- Each commit on its own: a48b1e5 / 46105b5 / 9464050 / ad424d2 / 196e489 → 859 / 859 / 862 / 863 / 863 passed (+1 deselected).
- `pytest tests/docs tests/test_harness.py`: 39 passed.

## Not run
- `make check` as a whole. Its pytest step includes the real-daemon test above, which builds a throwaway image (excluded per this brief). The web step needs `node_modules`, which this worktree lacks; `apps/web` is untouched.
- `make check E2E=1`, `make ui-smoke`: orchestrator-only. Both will now run the label sweep at each stub API's start; it reads `docker ps` and stops only containers labelled with that API's own URL.
- Postgres: the race was not reproduced there. By the analysis above, root cause 1 applies and is fixed; root cause 2 is SQLite-only.

## Side effects
- My first two full `pytest tests` runs (before I excluded it) ran the existing real-daemon test `test_a_container_that_fails_at_once_keeps_its_exit_code_until_terminate`. It built `orchapod-test/exit1:<hex>` (alpine, `CMD false`), ran one container that exited at once, and removed both. Checked afterwards: no `orchapod-test` image or container remains.
- A scratch check (`python -c` on an in-memory DB without `engine.dispose()`) hung at interpreter exit and was moved to the background by the 300 s limit. I killed its process group (my own command's, `kill -TERM -91671`). The hang predates this branch (same exit 142 under a 20 s alarm on f5d335f's code; both exit 0 with `dispose()`).
- Scratch APIs: 127.0.0.1:8091 only, process groups started and stopped by my driver. Nothing is left listening or running. Scratch files are under the session scratchpad (`stack/`).

## Open questions
1. `.gitignore` has `*.db` but not `*.db-wal` / `*.db-shm`. A SQLite file API (the default `./orchapod_dev.db`) can now leave these while a connection is open or after a crash. A two-line addition for whoever owns `.gitignore`.
2. Residual: a second cancel that lands in the handler's own database work (a double-click within milliseconds) still interrupts it. The route's fallback then marks the run cancelled, but the node is not failed, so Retry refuses. The fix would be to record the stop in a shielded task with its own session (as the gpu bill does). Not done.
3. A cancel that beats the executor's first commit leaves a cancelled run with no NodeRun rows (54 of 100 instant cancels above). This matches a cancel before start and is unchanged by this branch; Retry is then impossible, and Run again works.
4. A second API started on a port another API holds (a misconfiguration) runs its sweep before its bind fails. The existing DB sweep has the same ceiling.
5. hackathon/STATE.md: the backend backlog line (PendingRollbackError, startup sweep) can close.

## DECISIONs for the Orchestrator to record
- The startup sweep also terminates LocalDocker containers labelled with this API's `ORCHAPOD_CONTROL_URL` whose run is terminal or unknown to its database. It is scoped by a second label, `orchapod.control_url`, beyond the brief's `orchapod.run_id`: this Mac runs several orchapod APIs at once (dev 8002, stub e2e 8003+, other agents' stacks), each with its own database, and "unknown" alone would stop their live containers.
  - Ceiling: a stub e2e's leftover is swept by the next API on the same port.
  - Contracts change (46105b5) needs your approval.
- No Nebius-side orphan sweep by name prefix (dev and hosted may share one project); the `ponytail:` note is on `sweep`.
- SQLite (dev, tests, stub e2e) runs in WAL mode; Postgres is untouched.
- The executor's stop handler always rolls back and re-reads before recording the stop. Resolved inputs are committed with `running` (lineage survives the rollback). An unresolved ref fails the node without a `running` event.
- Contracts line 196e489: a cancel that lands while the executor awaits the database still ends the run `cancelled`.
