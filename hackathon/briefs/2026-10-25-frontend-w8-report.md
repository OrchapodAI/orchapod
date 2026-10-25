# frontend-w8 report: the run page shows what is executing (brief 2026-10-25-wave6.md, "frontend-w8"), with fix round 1

**Status:** DONE. All four items and the fix round (I1–I3, M1–M5, M7), checked in a browser against a mock of backend-w9's contract. Notes for others are in §5.
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
| 85e8f56 | docs(hackathon): frontend-w8 report |
| **fix round 1** | |
| 63e126e | fix(web): a Nebius resource labels its card whatever the provider; logs keep arrival order and ask for 2000 lines (I1, M4, M5, the `runIdOf` helper of M2) |
| b422f92 | fix(web): the Logs tab reads the history again when the socket opens, so a line stored before it opened is not lost (I2) |
| 6060ece | fix(web): only a node's status dot pulses, and nothing animates under prefers-reduced-motion (I3, and the handles of M3) |
| eeacc87 | fix(web): the canvas of a run is read-only, takes only a run id in ?run=, and keeps polling after a failure (M1, M2, M3) |
| (this file) | docs(hackathon): frontend-w8 report, fix round 1 |

Code diff over the base: 10 files (`lib/api.ts`, `lib/runEvents.ts`, `lib/types.ts`, `RunView`, `LogStream`, `NodeTimeline`, `OrchaNode`, the canvas page, the runs page, `globals.css`) and `tests/web/web.test.ts`. No new file, no new dependency.

## What the web app does now
1. **Log history.**
   - `api.runs.logs(id, nodeId?)` reads `GET /runs/{id}/logs?limit=2000[&node_id=]`. `RunView` loads it with the run, when another node is selected, and **whenever the socket opens or closes**: the socket has no replay and the first read happens before it opens, so a line stored in between was in neither. A re-read keeps the history on screen and replaces it when it arrives; only another run or node clears it (so no "Loading logs…" flash).
   - `mergeLogs(history, live)` drops a live line the history already holds, one copy per stored copy, so two real lines that look alike both show. A line's identity is its instant, node, level and text, the instant read with `apiDate` (the API stamps naive UTC, the SDK microseconds with `+00:00`). **Arrival order is kept**, since nodes keep their own clocks: only a live line older than the first stored one goes in front of it.
   - "Waiting for logs…" shows only when there are none and the run is on; "Loading logs…" while the history loads; "No logs." once the run is over. Log times use `apiDate`.
2. **Where each step runs.**
   - The card's second row reads `Nebius <Job|Endpoint> …<short id> · <state>` whenever the node has a `resource`, and otherwise `Local Docker` (the provider's name). The real contract gives vllm-serve `provider: "local-docker"` with an endpoint resource (backend-w9's `tests/api/test_executor.py:1094,1109`), which the first version read as "Local Docker Endpoint"; the resource now says where it is, whatever the provider. The state is there for a running node and, per the contract, for a registered endpoint through its keep-alive.
   - The run page now reads the summary every 5 s while the run is on (it did not poll before), so a Job's or Endpoint's state moves with no event. The header's GPU label names the provider and hides when null, and the runs table names its provider the same way (`providerName`).
3. **The canvas of a run.** "View workflow" opens `/canvas/<workflow_id>?run=<run_id>`.
   - `?run=` is read by `runIdOf`: a run id or nothing, so no other text reaches an API path. A valid one reads that run's summary every 5 s until it is over and draws each node by its status (pending grey, running blue, succeeded green, failed red; `nodeStyle`). A "Viewing run <short id> · <status>" pill links back; after a failed read it says "unavailable", and the poll is asked again after 5 s unless the reply was a 4xx.
   - The canvas of a run is **read-only**: no palette, no connecting, no Backspace delete, Save is "Save a copy", with the hint "Viewing a run: Save a copy to edit." Without `?run=` nothing changes.
   - Only the status dot pulses (`motion-safe`), and a global `prefers-reduced-motion` rule stops every CSS animation, the run page's running dots too.
4. **Tests** (web 38 → 43): `api.runs.logs`, `mergeLogs` (dedupe, twins, other node or time, older lines in front, arrival order), `providerName` with `whereRuns` (including the exact vllm-serve shape), `nodeStyle`, `runIdOf`.

## Checks
- `pnpm exec tsc --noEmit` clean; `pnpm build` compiles; `make check PY=python` (no E2E): ruff "All checks passed!", 1124 passed (2 warnings), web 43/43.
- **Mutation checks**, each reverted. Before this round: `mergeLogs` and the API call 8/8, `whereRuns` 7/7, `nodeStyle` 5/5. This round, the pure changes 10/10: the provider deciding again, "Nebius" replaced by the provider, the state dropped, a resource without a provider hidden, sorted again, live lines all in front or all behind the history, the limit dropped, `runIdOf` accepting anything or a 37th character.
- **Browser check** (scratch, outside the repo): a mock of backend-w9's contract on my own port, `next dev`, Chromium in Tokyo time, and a fake run socket whose opening the script controls. 28 checks, all PASS; against the components before the round, 13 of 26 failed. Observed:
  - I1: the serve card reads `Nebius Endpoint …z9y8x7w6 · RUNNING`, a CPU node `Local Docker`, train `Nebius Job …k8m3p7r2`; the runs table says "Nebius".
  - I2: with the socket held closed, a line stored after the first read was missing for good before the fix; now it shows (9 rows) once the socket opens, the history was read again, and the 7 rows stayed on screen meanwhile.
  - M5: two live lines arriving in the order (stamp 30, stamp 25) stay in that order; a live copy of a stored line shows once. M4: `logs?limit=2000` and `logs?limit=2000&node_id=train`.
  - I3: no card animates; the running node's dot runs `pulse`, and `none` under reduced motion; the run page's running pill dot is `dotPulse`, and `none` under reduced motion.
  - M1/M2: `?run=<not an id>` is absent (no pill, no request, editable); an unknown id (404) says "unavailable" and is asked once in 6.5 s; two 500s are asked again until the pill recovers, with one toast.
  - M3: palette hidden, "Save a copy" with the hint, `Backspace` deletes nothing, and a real drag from a node's output handle to another node adds no edge (the same drag adds one without `?run=`).

## 4. Found in the browser (not in the brief or the review)
- **`nodesConnectable={false}` alone did nothing.** React Flow hands the custom node `isConnectable`, and a `Handle` only follows it if the node passes it on; `OrchaNode` did not, so a visitor could still draw an edge on the "read-only" canvas of a run (1 edge added in a real drag). `OrchaNode` now forwards it (6060ece); the editor is unchanged, since it defaults to true.
- Earlier in the task: the provider line was cut off beside the status badge, and stored and live log lines showed nine hours apart in Tokyo time before the `apiDate` fix (780d75d, 43bd865).

## 5. Notes
1. **Contract details taken from backend-w9's branch** (read, not changed): the event and its stored copy carry the same node_id, ts, level and message; stdout and `progress` events are broadcast but never stored, so those live-only lines stay in the list; a registered endpoint keeps reporting its state through its keep-alive; the header's GPU label is the first GPU-renting node's own provider, so a plan whose only GPU node is vllm-serve reads "GPU: Local Docker" (the Nebius endpoint is on the node's card).
2. **The hosted golden run (I4, ruled):** its logs come from backend-w9 seeding `node_log` rows out of the fixture's `logs` artifacts and a reseed on the VM; there is no frontend fallback. Until backend-w9 deploys, the hosted API has neither new field and its page shows no provider lines.
3. **Beyond the brief:** the "No logs." and "Loading logs…" states, and the three browser-found fixes.
4. **For the smoke (orchestrator):** it pins none of the texts changed here (no "Waiting for logs…", "GPU:" or "View workflow"). It needs backend-w9's `/logs` route, or the run page's history call is a 404 its problem watcher would count.
5. **Commit trailer:** `Co-Authored-By: Claude Sonnet 5.5`, the one the harness gives this session and the role file (`.claude/agents/frontend.md:23`) asks for. The screenshots were deleted, as asked.
