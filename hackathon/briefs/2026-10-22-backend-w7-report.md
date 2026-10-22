# backend-w7 report (role backend) · 2026-10-22

Branch `hack/backend-w7` on 850e9f2. Commits:
- 79ee016 test(api): the budget flake;
- 375ef1b docs(contracts): Agent API and agent_knowledge;
- e538a2c feat(api): the reporter;
- ccef0af test(api): the IAM-CLI flake.

Spend: $0. No live call was made; STUB and fakes prove the code.

## Proof
- **The gate.** 50 consecutive runs of `pytest tests/api -q -p no:cacheprovider` on ccef0af (clean tree): 50 of 50 runs read `214 passed` (5.2–7.7 s each), 0 failures. Log: two batches of 25 with nothing between them.
- **Under load.** Four such loops ran in parallel for 480 s: 238 runs, 0 failures. On e538a2c, before the IAM fix, 169 of 185 runs failed, every one in the IAM-CLI test.
- **Lint and full tree.** `ruff check apps packages containers` is clean. `pytest tests` gives 867 passed.
- **Not run.** The web tests: nothing under apps/web changed, and this worktree has no node_modules.

## 1. The budget flake: neither an early assert nor a budget race
- **Reproduced at 850e9f2.** The full suite failed 9 of 15 runs. The two concurrency tests alone failed 0 of 20; test_budget.py alone failed 2 of 10.
- **What the rows showed.** At the failing assert, each run that was "neither" had its task done and its run row `failed`, but its node row was `pending` with no error. The granted run's node was also `pending`. So one session's commit was half-persisted, which a real transaction cannot do.
- **Root cause.** The in-memory test engine is a StaticPool, so every session shares one SQLite connection.
  - backend-w6's a48b1e5 starts the executor's except handler with `db.rollback()`.
  - On the shared connection, a refused run's rollback discarded another executor's UPDATEs, which were flushed but not yet committed. That executor's COMMIT then succeeded with nothing in it.
  - In isolation: two sessions, one rolls back while the other has flushed. On StaticPool the write is lost. On a file database (production's pool: NullPool for aiosqlite, QueuePool on Postgres) it lands.
  - Without the rollback, the budget test failed 0 of 15 runs. The rollback stays: the mid-statement-cancel tests fail without it.
- **Your candidates.** It is none of the four: the bill's own session, resolved inputs committed with `running`, WAL (the in-memory database has none), or the per-attempt grouping. It is a48b1e5's rollback meeting StaticPool.
- **Production is unaffected.** Every session there has its own connection, and the reservation logic is right: a mutant that drops `left()`'s re-read of the grants fails both concurrency tests (granted [1.0, 1.0, 1.0]).
- **Fix (test harness).** The two concurrency tests run on test_executor's `sqlite_file` engine through a `file_db` fixture: one connection per session, in WAL mode, as the API sets it up. After the fix: 0 of 15 runs failed, then the gate above.

## 1b. The IAM-CLI flake (platform-w7's report)
- **Cause.** `test_an_endpoint_node_without_a_token_fails_before_it_starts` set `IAM_TIMEOUT_S = 0.2` for all four cases. The two CLIs that exit normally ("exit 3" and "no token") take 0.13–0.17 s unloaded, so under load they lost to the timer ("took over 0.2 s"). This was also the 1 failure in 25 runs in my first gate attempt.
- **Fix.** No case depends on the wall clock any more:
  - a CLI that exits gets no timer (`None`);
  - the hung CLI gets a timeout of 0, which `asyncio.wait_for` raises at once (Python 3.12 cancels before the first step).
  - A mutant of the timeout branch still fails the hung case.

## 2. Reporter (spike 2 ruling)
- **(a) Model.** Super (`nvidia/nemotron-3-super-120b-a12b`) with thinking=False, in `planner.write_report`.
- **(b) One bounded call.**
  - `read_timeout=30` (`REPORT_TIMEOUT_S`).
  - `planner._SendOnce` wraps the client's http for this one call. A timeout or a dropped connection returns as a `ProviderError`, which the client's retry loop does not catch. A retry after a 429 or 5xx is refused.
  - Any failure falls back to the template. The tests cover ReadTimeout, 503 and 429: each sends one request and returns the template.
  - It lives in apps/api because packages/providers is platform's. `base.request(create=True)` already has the no-resend behaviour, but `chat()` does not expose it.
  - PROPOSAL for platform: a `chat(..., resend=False)` that passes `create=True` would replace `_SendOnce` (about 20 lines).
- **(c) The GET never waits.**
  - `routes/agent.report_later(run_id, scale)` starts one background writer per run (an in-process dict). The writer stores `agent_run.report_md` (R8) through the existing conditional update, so the report is kept only if no retry restarted the run meanwhile.
  - The executor asks for a report at every run end (the `finally` of `_run_in_own_session`, cancel included).
  - The GET also asks when a run is terminal, has no report and has no writer running. That covers a cancel before the start, the startup sweep, and a writer lost to an API restart.
  - The contract's response shape is unchanged; `ready` stays false until the report exists. The /agent page and e2e_agent already poll until `ready`.
- **(d) The report names the plan.** It starts with the template's title line `## <plan name>: <status>`, then a blank line, then the model's text, so `e2e_agent.check_report` holds for any model.
- **(e) Docs.**
  - contracts "Agent API": the GET line is rewritten (375ef1b).
  - agent_knowledge.md: in the model table, the reporter moves to Super's row.
  - Not edited (devrel's files): README.md:75, README.md:83 and docs/devpost.md:38 still say Lightning writes the report.
- **(f) data-prep's quality filter.** Unchanged (data-engineering owns it).
  - Its `read_timeout=30` is below Lightning's observed 37.2 s, and one call took 29.7 s.
  - A timed-out call is re-sent up to 3 times, and each send may bill. The row then counts as failed, and more than max(2, 10 %) failed rows fail the node.
- **Tests.** Five report tests cover:
  - the call itself: Super, thinking off, 30 s, the title, the R8 cache and the R6 ledger at Super's prices;
  - a report written as the run ends with no GET;
  - one send each for ReadTimeout, 503 and 429;
  - the template fallbacks, the retry race, and retry clearing the report.
  - Three mutants are caught: no send-once, no title, no executor hook.
  - The `launched` fixture now waits for the writers before its database closes. Without that, 4 writers logged "closed database" after their tests had passed.

## What does not work, and risks
- **The StaticPool hazard remains in other tests.** Tests that build sessions on `db.bind` (the `launched` fixture, per-request sessions) still share one connection. A rollback, or a session closed mid-transaction, in one of them discards another's flushed writes. No other test flaked in 288 sequential and 238 loaded runs. For this reason the report writer ends every session with a commit.
- **A latent twin of the IAM flake.** `test_a_hung_dependency_fails_health_within_the_timeout` (test_hardening) has the same shape: healthy checks (a real aiosqlite query and a thread hop) race a 0.2 s timer. It had 0 failures in 238 loaded runs, so I left it.
- **Cancelled runs.** Their report is written as the executor ends, so it misses a cost_json that lands later in the SIGTERM grace. The GET's summary fields stay live.
- **Retry during a write.** If a retry lands while the previous attempt's writer is still running, that report is dropped. The run-end request for the new attempt is skipped as a duplicate, so its report is written on the next poll.
- **Not changed.** The prompt still says "such as win rate" (spike 2 saw "Win rate (like)" on a dataset run). Checking a change needs a live call.

## DECISIONs for the Orchestrator
- DECISION 2026-10-22 (backend-w7): the agent report is written in the background as the run ends, or on the first poll of an ended run without one; the GET never calls a model. Nemotron 3 Super, thinking=False, one send with a 30 s read timeout, title line `## <plan>: <status>`, and the template on any failure.
- DECISION 2026-10-22 (backend-w7): tests that run sessions concurrently use a file SQLite (`sqlite_file`, one connection per session). The in-memory `db` fixture (StaticPool) shares one connection, so a rollback in one session discards another's flushed writes.
- DECISION 2026-10-22 (backend-w7): no test decides an outcome by the wall clock against a real process: a timeout of 0, or none, instead of 0.2 s.

## Fix round 1 (review: Approved, minors folded in)
Commits on `hack/backend-w7`:
- 956d709: merge of NebiusHackathon, which brings 21e3806 `chat(create=True)`;
- bd1fb70: docs(contracts), Agent API wording;
- 33353c6: fix(api), review fix round 1.

Spend: $0. The e2e was not run.

- **Minor 3.** `_SendOnce`, its `tf.http` swap and its two imports (httpx, ProviderError) are gone. So is the test's `base.time` stub. The reporter calls `tf.chat(..., create=True, read_timeout=REPORT_TIMEOUT_S, thinking=False, …)`.
  - A ReadTimeout and a 503 each send exactly one request, and the template stands in.
  - The 429 case is dropped, since create=True still retries a 429.
  - The main test asserts `create=True` and the 30 s read timeout.
  - Contract: the Agent API line now says create=True instead of "never re-sent". 429 and connect errors still retry.
- **Minor 1.** `_title` collapses the plan name to one line and caps it at 80 characters: `" ".join(name.split())[:80]`, falling back to "Agent run". The template's first line goes through `_title` too.
  - Test: the name `"qa\n## Cost\n$0.00 of $0.00 estimated"` yields exactly one heading line, `## qa ## Cost $0.00 of $0.00 estimated: succeeded`.
- **Minor 2.** Two new tests give "once" teeth:
  - two `report_later` calls make one model call;
  - a `write_report` that raises once leaves `ready` false and logs "was not written", and the next poll writes the report.
  - The `reports` fixture is now a yield-fixture that settles on teardown.
- **Minor 5.** routes/agent.py now says what the code does: `populate_existing` gives "the stored row: the writer updates it elsewhere", and the writer's commit is "the update if there was one; the transaction ends here either way". No test-harness reasons remain.
- **Minor 6.** test_hardening's hung-dependency test no longer depends on the wall clock:
  - the answering checks finish without yielding: the database check is a no-yield fake and Redis is the fixture's no-yield ping. So the timer cannot beat them (in Python 3.12, `wait_for` runs the check inline under `asyncio.timeout`).
  - Object storage hangs in its thread until the reply is in, so it can only lose.
  - It asserts 503 `["storage"]`, and that the hung call had not returned when the response arrived.
  - `redis_hangs` and `import time` are gone (unused).
- **Mutants caught** (each fails at least one test):
  - no dedupe in `report_later`;
  - no GET fallback;
  - the old `_title`;
  - no `create=True`;
  - no `wait_for` in `_answers` (the GET then waits the 30 s release and returns 200).
- **Acceptance on 33353c6.**
  - `pytest tests/api`: 10 of 10 runs read `217 passed`.
  - `make check PY=python` (no E2E) exits 0: ruff clean, `pytest tests` 885 passed, web 30 of 30. For the web tests I installed apps/web deps in this worktree; node_modules is gitignored.
  - Under load, four parallel suite loops ran 231 runs with 0 failures.
- **Rulings noted, no work.** The GET fallback is accepted. The Lightning wording in README, devpost and feedback, and tests/docs/test_submission_docs.py, go to devrel. I left planner.py's dead tf-deploy lines to the orchestrator: templates/4-nebius-docs-specialist.json still lists tf-deploy, and test_agent.py exercises those lines through a faked registry, so deleting them pulls in tests and a template.
- **Concern for qa-w7 (e2e_agent real mode).** The title holds the plan name normalised to one line of at most 80 characters, but `e2e_agent.check_report` looks for the raw `plan["name"]`. A live planner name longer than 80 characters, or with whitespace runs, would fail that check; comparing `" ".join(name.split())[:80]` fixes it. The canonical template names are 20–31 characters with no whitespace, so STUB is unaffected.
