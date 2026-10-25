# frontend-w8 report: the run page shows what is executing (brief 2026-10-25-wave6.md, "frontend-w8")

**Status:** DONE. All four items, checked in a browser against a mock of backend-w9's contract. Notes for others are in §5.
**Branch:** `hack/frontend-w8`, worktree `.claude/worktrees/frontend-w8`. Base 8b17ab0 (`git merge-base --is-ancestor 8b17ab0 HEAD` passes). Not pushed.
**Spend:** $0. No key, no model call, no e2e, no smoke.

## Commits
| SHA | What |
| --- | --- |
| 0f4307a | feat(web): the Logs tab loads the stored log history, then merges the live lines without duplicates |
| 34482cc | feat(web): each node card says where its step runs, with a Nebius resource's kind, short id and live state |
| 826a908 | feat(web): the canvas of a run: ?run=<id> colours each node by its status and links back to the run |
| 780d75d | fix(web): a log line's time reads as UTC whether it came from the history or the socket |
| 43bd865 | fix(web): the provider line of a node card spans the card, and the canvas banner is a status pill |
| (this file) | docs(hackathon): frontend-w8 report |

Code diff over the base: 9 files, +195 −55 (`lib/api.ts`, `lib/runEvents.ts`, `lib/types.ts`, `RunView`, `LogStream`, `NodeTimeline`, `OrchaNode`, the canvas page, `tests/web/web.test.ts`). No new file, no new dependency.

## What changed
1. **Log history.**
   - `api.runs.logs(id, nodeId?)` reads `GET /runs/{id}/logs[?node_id=]` (the contract's default of the last 500 lines). `RunView` loads it with the run and again whenever another node is selected (the selection follows the running node), and the socket, which has no replay, adds the new lines.
   - `mergeLogs(history, live)` drops a live line the history already holds, one copy per stored copy, so two real lines that look alike both show. A line's identity is its instant, node, level and text; the instant is read with `apiDate`, because the API stamps naive UTC and the SDK microseconds with `+00:00`. The rest is in time order: a page open longer than the 500-line window has older live lines, which a plain "history then live" would have put after the newest.
   - "Waiting for logs…" shows only when there are none and the run is on. While the history loads it says "Loading logs…", and once the run is over, "No logs." (a finished run is not waiting for anything).
   - `LogLine` moved to `lib/types.ts`; log times now use `apiDate` (§4).
2. **Where each step runs.**
   - Each node card gets a second row: "Local Docker", or for a Nebius resource its kind, a short id and, while the node runs, the live state: `Nebius Job …k8m3p7r2 · IMAGE_PULLING`, `Nebius Endpoint …z9y8x7w6 · RUNNING`. Nothing before the node has run, and nothing on an API without the fields (they are optional in the type).
   - **The run page did not poll before** (it snapshots on mount and on events). A Job's state changes with no event, so `RunView` now reads the summary every 5 s (`POLL_MS`) while the run is on, and stops when it is over.
   - The header's GPU label names the provider ("GPU: Nebius") and stays hidden when it is null, which is how the new `RunOut.gpu_provider` reads.
3. **The canvas of a run.**
   - "View workflow" opens `/canvas/<workflow_id>?run=<run_id>`. With `?run=` the canvas reads that run's summary every 5 s until it is over and draws each node by its status: pending grey, running blue and pulsing, succeeded green, failed red (`nodeStyle`, which `OrchaNode` now draws from instead of its own inline map).
   - The statuses are derived for display, so Save never writes one into the YAML, and a summary that arrives before the nodes still finds them. A "Viewing run <short id> · <status>" pill in the topbar, in the run's status colour with the pulsing dot, links back to `/runs/<id>`.
   - Without `?run=` nothing changes: no banner, no ring, no request.
4. **Tests** (web 38 → 42): `api.runs.logs` (URL, node filter, encoding), `mergeLogs`, `providerName` with `whereRuns`, `nodeStyle`. Mutation checks, each reverted: `mergeLogs` and the API call 8/8 (no dedupe, one stored copy hiding every live copy, no ordering, key without the node, key on the raw string, naive UTC read as local, no node filter, node id not encoded), `whereRuns` 7/7, `nodeStyle` 5/5.

## Checks
- `pnpm exec tsc --noEmit` clean; `pnpm build` compiles (`/canvas/[id]` stays dynamic, so `useSearchParams` needs no Suspense); `make check PY=python` (no E2E): ruff "All checks passed!", 1124 passed (2 warnings), web 42/42.
- **Browser check** (scratch, outside the repo): a mock of backend-w9's contract on my own port, `next dev`, Chromium in Tokyo time, the run page's WebSocket faked inside the browser so I could send `log` events. The run goes through six phases; every process it started was killed. Observed:
  - Header: no GPU label at phase 0, "GPU: Nebius" after. "View workflow" links to `/canvas/w1?run=…`.
  - Cards at phase 1: `Local Docker` for the CPU and API steps, `Nebius Job …k8m3p7r2 · IMAGE_PULLING` for train, nothing for the pending ones. With no event, the next poll turned the state to `RUNNING`, then `Nebius Job …k8m3p7r2` once train was done, and `Nebius Endpoint …z9y8x7w6 · PROVISIONING` then `· RUNNING` for serve.
  - Logs: 7 stored rows on open; one duplicate and two new live lines made 9 rows, not 10. Selecting train fetched `?node_id=train` and showed its 4 lines. An empty node said "Waiting for logs…" while the run was on and "No logs." once it had finished.
  - Canvas at phase 4: four green, serve blue and pulsing, evaluate grey, banner "Viewing run 00000000 · running"; after the run finished, all green and "· succeeded", and no more summary reads. Without `?run=`: 0 banners, 0 rings, 0 requests.
- Screenshots, untracked and not committed: `/Users/hari/src/orchapod-hack/.claude/worktrees/frontend-w8/screenshots-frontend-w8/` (`final-run-page-train-logs.png`, `final-run-page-serve-provisioning.png`, `final-canvas-run-phase4.png`, `final-canvas-run-done.png`).

## 4. Found in the browser, fixed (not in the brief)
- **The provider line was cut off.** Beside the status badge it truncated to "Nebius Endpoi…", hiding the live state. The card is a two-column grid now and the line a second row that wraps (43bd865).
- **One timeline showed two clock times.** `LogStream` formatted with `new Date(line.ts)`, which reads a naive stamp as local time. With the old formatting the stored lines read `10:00:xx` and the live ones `19:00:xx` in Tokyo time. `apiDate` is the app's one reader of API datetimes (780d75d).
- **The banner looked like plain text**, so it is a status pill (43bd865).

## 5. Notes
1. **Coded to the brief's contract; two details to confirm at merge:** the notation of `ts` in `GET /logs` (either the SDK's or naive UTC works), and `resource.id` (a Job's `gpu_pod_id`, a vllm-serve's `endpoint_id`). The web side shows the last 8 characters of an id longer than 14.
2. **The hosted golden run:** the hosted API today answers `gpu_provider: "local-docker"` for it and has neither new field, so its page shows no provider lines until backend-w9 deploys. Its Logs tab will say "No logs.", but all six of its nodes have a `logs` artifact with a download link (the SDK's JSONL, kept at exit; checked on the hosted summary), so its logs exist: reading those when the stored history is empty would put the golden run's real logs on its page for the video. About 25 lines and a test; not done, as it is outside the brief. Say so and I will add it.
3. **Beyond the brief:** the "No logs." and "Loading logs…" states, and the three fixes in §4.
4. **For the smoke (orchestrator):** it pins none of the texts changed here (no "Waiting for logs…", "GPU:" or "View workflow"). It needs backend-w9's `/logs` route: without it the run page's history call is a 404, which its problem watcher would count.
5. **Commit trailer:** `Co-Authored-By: Claude Sonnet 5.5`, the one the harness gives this session and the role file (`.claude/agents/frontend.md:23`) asks for.
