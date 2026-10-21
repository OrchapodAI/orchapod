# qa-w6 report — wave 5 (2026-10-24), role qa

Branch `hack/qa-w6` on 04af555 (ancestor check passed). Commits, oldest first: `6c6d0f6` drill pin, `56af175` cancel token, `3488758` Linux, `2eedd44` Playwright case, `83f8941` cancel error wording. Spend: $0 (STUB, no key, no cloud call). Docker: no build, no retag of any `orchapod/*:dev` image; the scratch checks below ran stub nodes from the images that already existed (details under "Not run / side effects").

## Item 1a: the cancel after a timeout sends the run's cancel token (56af175, 83f8941)
- `poll_run(c, run_id, path, done, *, cancel_token)` (scripts/e2e_demo.py): the token is a required keyword, so a forgotten caller fails loudly. It POSTs the cancel with `X-Orchapod-Cancel-Token`. `run_plan` passes the token from start's reply, `e2e_agent.run_one` the one from `/agent/run`.
- It no longer hides a refused cancel. The old `except RuntimeError: pass` swallowed a 403 and the script then printed "so it was cancelled" over a run left running. Now only 409 (the run ended while we asked) is fine; any other status raises `run <id> did not end within 300 s, and POST /runs/<id>/cancel -> HTTP 403: …`.
- Tests (RED first: 5 failed, 65 passed): `test_poll_run_cancels_a_run_that_outlives_the_limit_with_its_cancel_token`, `test_a_cancel_the_api_refuses_is_a_failure_but_a_run_that_just_ended_is_not` (403 raises, 409 passes), `test_run_plan_cancels_with_the_token_start_returned`, and in test_e2e_agent.py `test_a_run_that_outlives_the_limit_is_cancelled_with_the_token_agent_run_returned`.
- Real API (scratch, stub stack; the unit tests only use MockTransport):

| Path | Result |
| --- | --- |
| `run_plan` with LIMIT_S=2, run mid-flight (`synth running`) | cancel 200, run `cancelled` |
| `/agent/run` reply keys | `['cancel_token', 'estimate', 'run_id', 'workflow_id']`; `poll_run` on the report path cancelled it, run `cancelled` |
| cancel without the header / with a wrong one | 403 / 403 `cancelling this run needs its cancel token (X-Orchapod-Cancel-Token …` |
| `poll_run` with a wrong token | raised `run … did not end within 2 s, and POST … -> HTTP 403 …` |
| cancel of a run that ended | 409 (the case `poll_run` tolerates) |

## Item 1b: the preempted-Job pin is `Pod.error` (6c6d0f6)
- Pin: `("failed", "FAILED ContainerFailed: exit code 143, see <hidden>", [("train", "failed", <same>)])` (was `exit 1`).
- How: the drills' gpu provider (`Nodes.wait`) now ends with `job_ends()`: the real `NebiusProvider.wait` reads a recorded `GET /jobs/<id>` reply (`COMPLETED` for exit 0, else `FAILED` + `stateDetails` code and a message built from the node's exit code and a console link). So the text is what the provider builds and the executor shows, not a string typed into the fake. The retry then reads `COMPLETED` and the run succeeds as before.
- Also fixed: the fake had no `quote()`, so since backend-w5's gpu billing the drill logged `ERROR gpu time of nebius train-1 not billed` (swallowed). It delegates to `NebiusProvider().quote`. `NEBIUS_IAM_TOKEN=iam-drill` joins the drills' env fixture (it is not in the executor's FORWARD list, so no node sees it).
- Sensitivity (each mutation made, test red, file restored): provider without `pod.error` -> `exit 1`; `HIDDEN` regex off -> the URL shows; executor ignoring `pod.error` -> `exit 1`.
- The Job's `code`/`message` wording is a fake (shape from tests/providers/test_nebius.py); Nebius's real text for a reclaimed Job is unconfirmed until G2.

## Item 1c: Playwright case for the 409 -> "Save a copy" flow (2eedd44)
`canvas: an edit of a workflow that has runs is refused (409) and saved as a copy; the original stays` in tests/ui/smoke.spec.ts, after the cap test (5 tests now, was 4).
- Setup through the public-scale API (`E2E_PUBLIC_API_URL`): a one-node web-research workflow and a run that is created and never started ($0, no container, but the workflow has a run). Every call of the page is routed there with `page.route` (as the cap test does for the templates).
- Flow: open `/canvas/<id>`, click the node, set Max pages 5 -> 7, press "Save draft" -> the PUT answers 409 and `#read-only-note` reads "This workflow has runs, so it is read-only"; press "Save a copy" -> URL `/canvas/<other id>`, crumb "<name> (copy)", the note empty, Max pages 7 in the copy, and "Save draft" on the copy saves ("Saved ✓"). Through the API: the original is still version 1 with its YAML and Max pages 5; the copy is named "<name> (copy)" with 7. The only page "problem" allowed is the browser's console line for the 409.
- Screens for D7: `/canvas/<id>` after the 409 (note + "Save a copy"), then the copy.
- Proof, on a private stack (scripts/e2e_ui.py's own helpers with the image build patched out; nothing started a container): the case passed on 8 fresh stacks, 1.6 s each, also cold (`.next` removed), and 5 of them together with the cap test.
- Sensitivity (each made, case red, restored): page ignores the 409 (`Expected: "This workflow has runs…" Received: ""`); Save a copy posts the original YAML instead of the edit (`Expected "7" Received "5"`); API without the read-only rule (`Expected 409, Received 200`).
- Type-check: `tsc --noEmit --strict` exit 0; a probe copy with two type errors exits 2 (the check bites).
- The primary API (full scale) is anonymous too, so the 409 does not depend on the scale; the public-scale API is used because the brief says so, and it keeps the case off the primary's rate buckets.

## Item 2: e2e on Linux (3488758)
- **The brief's premise was half wrong.** LocalDocker already passes `--add-host=host.docker.internal:host-gateway` on every platform (packages/providers/local_docker.py:129), and the e2e scripts start no container themselves. What Linux lacked is a listener the docker0 gateway reaches: the stub API bound 127.0.0.1 (the old `ponytail:` note in `start_api`). Docker Desktop forwards the name to 127.0.0.1, a Linux daemon does not.
- Fix: `bind_host(platform=sys.platform)` is `0.0.0.0` on Linux, `127.0.0.1` elsewhere; `listen_on_free_port(start, host)` takes it; `start_api` binds it (the URL stays 127.0.0.1). Also the preflight message: "start Docker Desktop, or the daemon on Linux". Both APIs of the UI smoke use `start_api`, so they follow.
- Tests: `test_the_stub_api_listens_where_the_node_containers_can_reach_it` (linux -> 0.0.0.0, darwin and win32 -> 127.0.0.1, and `start_api` binds what `bind_host` says; a spy, because a real 0.0.0.0 bind makes macOS ask Hari to accept incoming connections) and `test_node_containers_get_host_docker_internal_on_linux_too` (tests/providers/test_local_docker.py: the flag in the `docker run` argv, plus `ORCHAPOD_CONTROL_URL` and `ORCHAPOD_R2_ENDPOINT` rewritten to `host.docker.internal`). Sensitivity: deleting the flag fails the second; `start_api` ignoring `bind_host` fails the first (3 cases).
- **NOT verified on Linux** (this Mac is the only host I have). Known gap for the hosted VM: infra/cloud-init.yaml runs `ufw default deny incoming` with 22/80/443 open. A container reaching a host listener over docker0 is INPUT traffic, so ufw very likely drops it, and the nodes of a stub run would fail to post logs and artifacts. Run `sudo ufw allow in on docker0` on the VM first (or platform adds it to cloud-init); published ports such as MinIO's 9000 are forwarded, not delivered to the host, so they should not be affected. All of this is unverified: the VM does not exist yet.

## Proof
- Baseline at 04af555: `make check` exit 0, `850 passed, 2 warnings`, web 30/30.
- At 83f8941: `make check` exit 0, ruff `All checks passed!`, `857 passed, 2 warnings in 20.51s`, web `tests 30, pass 30, fail 0`, `SKIP stub e2e …`. 857 = 850 + 3 (cancel commit: two in demo, one in agent; the old poll_run test was changed in place) + 4 (Linux commit: three bind cases, the LocalDocker flag).
- Each commit is green on its own: `pytest tests` at 6c6d0f6 / 56af175 / 3488758 / 2eedd44 / 83f8941 -> 850 / 853 / 857 / 857 / 857 passed.
- `ruff check scripts tests/e2e tests/drills tests/providers/test_local_docker.py`: clean.

## Orchestrator: what to run after the merge
1. `make check` -> `857 passed`, web 30/30.
2. `make check E2E=1` -> e2e_demo PASS and `e2e_agent`: `3 PASS, 0 FAIL`. A healthy run never reaches the cancel, but every run now reads `cancel_token` from start and `/agent/run`; both carry it (checked on the real stub API).
3. `make ui-smoke` -> **5 passed** (was 4). Only the new case: `make ui-smoke UI_ARGS="-g canvas:"` (it still builds the images first).
4. Type-check, from the main checkout: `cd tests/ui && ../../apps/web/node_modules/.bin/tsc --noEmit --strict --target ES2022 --module ESNext --moduleResolution Bundler --skipLibCheck --lib ES2022,DOM --types node --typeRoots ../../apps/web/node_modules/@types smoke.spec.ts playwright.config.ts` -> exit 0.
5. D7, on a Linux host: `make up`, `sudo ufw allow in on docker0` if ufw is on, then `python scripts/e2e_demo.py --stub`.

## Not run / side effects
- Not run, by instruction: `make check E2E=1`, `make ui-smoke`.
- Scratch checks (files in the scratchpad, not committed): the 5 cancel paths and the `/agent/run` check above, and the Playwright case on private stacks. They ran stub nodes (synth-distilabel, data-prep) from the existing `orchapod/*:dev` images through APIs on 8003/8004 and `next dev` on 3100 (never 8000-8002); every PID came from the repo's own helpers and was stopped by them; no port is left listening.
- One container leaked: a cancel that landed while a `prep` container was being created, then SIGTERM of the API a second later, left `orchapod/data-prep:dev` running. I confirmed it was mine (its `ORCHAPOD_RUN_ID` was my scratch run) and stopped and removed that one by name. Nothing else was touched.

## Findings outside my scope (apps/, for backend)
1. A cancel within milliseconds of start, on the throwaway SQLite DB. Of 9 such cancels: 6 answered 200 with the run `cancelled`, but the executor logged `PendingRollbackError` from `_stop` (apps/api/executor/run_workflow.py:177, called at :158) and the node stayed `pending`; 1 answered 200 cleanly; 1 answered HTTP 500 `database is locked`; 1 reset the connection. The e2e cancels after 300 s, so it does not hit this. Postgres untested.
2. A cancel that lands mid-provision, followed at once by an API shutdown, left the container running once (the lifespan only disconnects the event bus, so a teardown still in flight, `_terminate_when_up`, most likely dies with the process; my guess, not traced). The stub API's DB is throwaway, so no later sweep could have found it. Rare, failure path only.

## Open questions and stale docs
1. README.md:121 is stale after this merge: it says the stub e2e's API "listens on 127.0.0.1 … not on Linux; there, run the app below with `STUB=1` instead". Devrel: keep the `TODO(D8)` until the first Linux run.
2. `make ui-deps` installs no Playwright browser, and no doc or script does (`git grep "playwright install"` is empty): a fresh clone (D7) fails at the first test with "Executable doesn't exist". Needs `pnpm -C tests/ui exec playwright install chromium` (plus `--with-deps` on Linux, root). The Makefile is outside this brief; say if I should add it to `ui-deps`.
3. hackathon/STATE.md: qa-w6 can be marked done; "ui-smoke 4/4" becomes 5.

## DECISIONs for the Orchestrator to record
- A refused cancel in the e2e scripts is a failure (any status but 409), not a silent pass; the token is a required keyword of `poll_run`.
- Item 2 is the bind address, not the flag: the stub API listens on 0.0.0.0 on Linux (key-less STUB API, for the minutes it lives; the trade-off is in `bind_host`'s `ponytail:` note). The flag is pinned in a test.
- The drills' gpu fake is the real `NebiusProvider.wait` over a recorded job reply; the pin is that provider's `Pod.error`.
- The 409 case runs against the public-scale API by routing all page calls there.
