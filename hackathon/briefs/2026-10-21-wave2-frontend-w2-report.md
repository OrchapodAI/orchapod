# Wave 2 report: frontend-w2 (2026-10-21)

**Status: DONE.** Both brief items are done. The run page was checked live in headless Chrome against backend-w1's real API (retry and summary routes).

**Branch** `hack/frontend-w2` (worktree `.claude/worktrees/frontend-w2`). `git merge-base --is-ancestor bafad28 HEAD` passes. Nothing pushed.

| SHA | Commit |
| --- | --- |
| `3d045c7` | fix(web): wave-1 review carry-overs; nothing made up on screen |
| `26b631d` | feat(web): run page from GET /runs/{id}/summary, live cost meter, Retry node |
| `55e3926` | docs(readme): run page summary, cost meter and Retry node |

**Merge order:** after backend-w1. The run page now reads `GET /runs/{id}/summary`. On an API without that route, the page shows "The API at … has no /runs/{id}/summary route yet (404)." instead of a node list.

## 1. Wave-1 carry-overs (3d045c7)
- **YAML quoting.** `yamlValue` now JSON-quotes strings that start with `[ ] { } , ' "`. PyYAML raises a ParserError on each of these as a plain scalar (checked); the same characters mid-string (`test[:50]`, `a, b`) stay plain and load fine. This covers both `planYaml` and `buildYamlFromGraph`.
- **RunView `.catch`.** Every snapshot fetch has a catch. A failed load shows the API's sentence (from `explainError`) where "Loading…" used to stay forever, and cancel and retry errors use the same sentence. See commit 26b631d, which rewrote the fetches.
- **Palette.** The vllm-serve runtime badge now reads `api`.
- **/agent page.**
  - Warnings and errors are keyed by index.
  - Enter is ignored while an IME is composing (`nativeEvent.isComposing`, plus `keyCode 229` for Safari).
  - An always-rendered `role="status"` line shows "Nemotron is planning…" and, once the plan arrives, announces "Plan ready: <name>, N nodes, E errors." to screen readers only (`sr-only`).
- **Node forms.** Each form control has `aria-describedby="help-<key>"` pointing at its help text.
- **Drop defaults.** `defaultInputs` moved from the canvas page into `lib/nodeForms.ts`, where `formDefaults` already lived. It drops `teacher_kind`, and vllm-serve's `keep_alive_min` is now 30.
- **Nothing made up on screen:**
  - Sidebar: the counts (12/348/47/23/8), the "orbital-research · 9 members · team" block, the "$28.40 used / $250" budget widget and the "Elena M." footer are gone. The API serves none of them; the run and day budget has no read endpoint in the contracts.
  - The same made-up team is gone from 7 page breadcrumbs, and the hard-coded "EM" Owner column is gone from /workflows and /runs.
  - The CSS only those pieces used is deleted (26 lines).
- **Vast.ai/RunPod surfaces.** The sidebar no longer links /inference or /endpoints, and nothing else in the app linked to them. The pages still exist at their URLs (P2 deletion per the audit DECISION).

## 2. Run page (26b631d)
- **Per-node status from `GET /runs/{id}/summary`.**
  - The page's state is `{run: GET /runs/{id}, summary: GET /runs/{id}/summary}`. Nodes (status, usd, error) and artifacts both come from the summary, so `/runs/{id}/nodes` and `/runs/{id}/artifacts` are no longer called.
  - Events have no replay, so the page re-snapshots in four cases: on mount, when the socket opens (after a retry's reconnect), when it closes (end of run), and when an `artifact` event lands (so the node's usd updates when cost_json arrives).
  - Only the newest snapshot is applied.
- **WS events are applied once each** through `lib/runEvents.ts` `applyRunEvent` (`run_status`, `run_cost`, and `node_status` with its `error`).
  - This fixes a pre-existing bug: the old loop re-ran every event on each new one, so each later event re-fetched artifacts once per earlier artifact event.
- **Cost meter.** A `Cost $x.xxx` pill in the header shows Run.cost_usd on load and updates live from `run_cost`. The timeline adds a node's usd (from the summary) once it is above 0.
- **Node errors verbatim.** A failed node shows its error under its row in mono, with whitespace kept and wrapped, never truncated.
- **Retry node.**
  - The button sits on each failed node and calls `POST /runs/{id}/nodes/{node_id}/retry`.
  - It is enabled only while the run is `failed` or `cancelled` (`canRetry`), and disabled while a retry is in flight ("Retrying…").
  - On 202 the page shows the returned run and marks the node pending. It then reconnects the socket, which the server closed at the terminal status, and re-syncs on open.
  - `useRunStream(runId, attempt)` detaches the old socket's handlers, so its late close cannot flip the new socket's state.
- **Artifact downloads.** The download icon links `{API}/artifacts/{id}/download` from the summary's `download_url`. The old link was an r2:// URI, which a browser cannot open.
- **Incidental fix.** `req()` in lib/api.ts spread `init` after `headers`, so any caller passing headers lost `Content-Type`. Nothing passes headers today; this will matter once the browser sends `X-Orchapod-Admin`. My check script hit exactly this bug.
- **Doc line.** README, under "Start API and frontend" (55e3926).

## Proof
| Command | Result |
| --- | --- |
| `node --test "tests/web/*.test.ts"` (repo root) | `tests 11 · pass 11 · fail 0` (6 from wave 1 plus 5 new; the YAML test was extended) |
| Each new test against the base file (file swapped to bafad28, run, restored) | workflowYaml.ts → the quoting test fails; Sidebar.tsx → the "nothing made up" test fails; api.ts → the summary/retry test fails. Without runEvents.ts or `defaultInputs`, the file fails at import. |
| `pnpm --config.verify-deps-before-run=false exec tsc --noEmit` (apps/web) | exit 0 |
| `pnpm --config.verify-deps-before-run=false build` (apps/web) | exit 0 (`ƒ /runs/[id]`, `○ /agent 4.69 kB`, 16 routes) |
| `make check` (venv active) | exit 0: ruff "All checks passed!", `232 passed, 58 warnings`, `SKIP stub e2e` (qa) |
| Live check (below) | exit 0 |

**Live check.** One foreground script:
- Setup:
  - The API runs from `git archive hack/backend-w1` on 127.0.0.1:8013. Its runs.py, run_workflow.py, ws.py, events.py and internal.py are byte-identical to what NebiusHackathon merged in bc5c59f.
  - It starts with `env -i`, so no provider keys reach it, and uses a scratch SQLite DB, the orchapod-hack Redis and an explicit test ORCHAPOD_INTERNAL_SECRET.
  - `next dev` runs from this worktree on :3013, and headless Chrome is driven over CDP on :9333.
  - All three were stopped afterwards; the ports were confirmed free.
- The run is one `unsloth-train` node. With no GPU provider configured, it fails at once with no network call.
- Output, excerpted:
```
A: failed run loaded: … | Failed | Started … | Cost $0.000 | … | train | Unsloth Train | Failed |
   no gpu provider: No provider in ['nebius', 'vastai'] has available 1xH100 capacity. Check your API keys and provider dashboards. | Retry node
   error shown verbatim: true | retry enabled: true
POST /internal/artifact cost_json usd 0.0123 → 201
B: after run_cost: … | Cost $0.012 | …                         (live, from the WS run_cost event)
C: after clicking Retry node: "Retrying…(disabled)" → "Retry node"; node re-ran (started_at changed): true | run: failed
D: final: … | Unsloth Train · $0.012 | Failed | <same error> | Retry node      (node usd from the re-synced summary)
E: /runs/00000000-…: "404 on /runs/00000000-0000-4000-8000-000000000000: Run not found"
F: sidebar: Home Agent Workflows Runs · Base Models My Models Datasets Artifacts · Cost & GPUs Settings
   links: / /agent /workflows /runs /registry /models /datasets /artifacts /cost /settings
API log: "POST /runs/37cf5cc1-…/nodes/train/retry HTTP/1.1" 202 Accepted, then GET …/summary re-syncs
```
The node fails again within milliseconds, so C never shows the pending and running states in between. Only the final state and the re-run were observable here.

**Process note.** The first attempt of this check hung: my script's CDP calls had no timeout, and its output was piped through `tail`. It ran past 600 s, and the harness moved it to the background. I stopped it with TaskStop and killed its servers (ports confirmed free), then reran with per-call timeouts and a 240 s watchdog. The rerun completed in the foreground.

**Cost: $0.** No model calls. The API had no provider keys, so nothing was rented.

## Routes and states for the Orchestrator's screenshots
Use a free port for the web app, as before: `NEXT_PUBLIC_API_URL=http://127.0.0.1:<api> NEXT_PUBLIC_WS_URL=ws://127.0.0.1:<api> pnpm --config.verify-deps-before-run=false dev -p 3001`. The run-page states need backend-w1 merged.

**Safety for the failed-run recipe.** Start that API with `env -i HOME=$HOME PATH=$PATH DATABASE_URL=… REDIS_URL=redis://localhost:6379 ORCHAPOD_INTERNAL_SECRET=<test value> PYTHONPATH=.:apps:packages/sdk-py uvicorn api.main:app --port <api>`. Never source .env for this run: if VASTAI_API_KEY is set, the gpu node would ask vast.ai for a GPU instead of failing.

1. **/runs/{id}, failed run.** Create it with:
   - `POST /workflows {"name":"retry-demo","yaml":"name: retry-demo\nnodes:\n  - id: train\n    type: unsloth-train\n    inputs:\n      model: nvidia/Llama-3.1-Nemotron-Nano-8B-v1\n"}`
   - then `POST /runs {"workflow_id"}` and `POST /runs/{id}/start`.

   Expect: the Failed badge, the node's error in rose mono under the node, an enabled "Retry node" button and a "Cost $0.000" pill.
2. **/runs/{id}, live cost meter.** Keep the page open (its socket stays subscribed), then `POST /internal/artifact` with header `X-Orchapod-Secret: <test value>` and body `{"run_id":"<id>","node_id":"train","artifact":{"name":"cost_json","uri":"r2://orchapod-artifacts/runs/<id>/train/cost_json","kind":"metrics","metadata":{"usd":0.0123}}}`. Expect "Cost $0.012" in the header and "Unsloth Train · $0.012" on the node.
3. **/runs/{id}, Retry.** Click "Retry node". It shows "Retrying…" (disabled), then the node fails again. A real container node would show pending → running in between.
4. **/runs/00000000-0000-4000-8000-000000000000.** Expect "404 on /runs/…: Run not found". With the API stopped, any /runs/{id} shows "Can't reach the Orchapod API at …. Is it running?".
5. **Artifacts tab on a run with outputs.** The download icon points at `{API}/artifacts/{id}/download`.
6. **Sidebar, any page.** Navigation only: no counts, team, user or budget, and no Inference or Endpoints entries.
7. **/workflows and /runs.** No Owner column, and the breadcrumb is the page name alone.
8. **/agent.** Click an example, then Plan. "Nemotron is planning…" shows while planning. Warning and error lists render as before; the "Plan ready" status line is screen-reader only.
9. **/canvas/{id}.** The palette's Serve shows an `API` badge. Drop Synth Data: its generic fields have no teacher_kind. Drop Serve: keep_alive_min is 30.

## What does not work / ceilings
- **Snapshot vs. event race.** A snapshot taken just before an event, but answered after it, can briefly show the older status. The next event or snapshot corrects it, and the snapshot at socket close settles the final state. ponytail ceiling: polling the summary while the run is active would also cover a dead socket.
- **No artifact sizes.** The summary has no `size_bytes`, so the artifacts list no longer shows sizes.
- **Endpoint tab model name.** It now comes from the same node's `model_ref` meta (`model`, per contracts "vllm-serve"), falling back to "model". The old source was vllm-serve's `inputs.model`, which the summary does not carry. This legacy tab cannot appear today anyway, because vllm-serve crashes before /internal/ttl.
- **YAML 1.1 bare words and dates.** Plain strings such as yes, no, on, off, null, ~ and dates still load as bool, null or date. This is the ceiling of keeping plain scalars (numbers typed as text must stay numbers). If an LLM plan ever hits it, quote every string in `planYaml`.
- **Times are off by the timezone.** The API returns naive UTC datetimes (no `Z`), so "Started" shows UTC as if it were local time (live check: 12:32 AM for 20:32 EDT). That is backend serialization.
- **Not in the brief, left alone:**
  - tf-deploy's palette text still promises per-token serving (STATE P1, open until spike 1).
  - /cost, /datasets and /settings are "Coming soon" placeholders and still linked.
  - `explainError`'s 503 sentence says "The agent is switched off", including on the run page's retry.

## Open questions
1. Backend: add `size_bytes` to the summary's artifacts, so the run page can show dataset sizes again?
2. qa-w2: tests/web imports only `node:` modules and type-only lib files, so it needs no node_modules. Keep new lib logic in plain .ts files with `import type` only.

## Merge notes
- Dry run against today's NebiusHackathon (c75c119, with backend-w1, data-w1 and devrel-w1 merged): `git merge-tree --write-tree --name-only NebiusHackathon hack/frontend-w2` reports one conflict, `README.md`. Every apps/web and tests/web file merges cleanly.
- To resolve: take NebiusHackathon's README (devrel wins), drop my paragraph, and end its line 64 with: "; a failed node shows its error verbatim and a Retry node button, and per-node status comes from `GET /runs/{id}/summary`". Devrel's line 64 and line 141 already name the run page's cost and cost meter.
- No changes outside apps/web, tests/web and that README line.

## DECISIONS to record
- The run page reads `GET /runs/{id}` plus `GET /runs/{id}/summary`; `/runs/{id}/nodes` and `/runs/{id}/artifacts` are no longer called by the UI. It re-snapshots on mount, on socket open and close, and on each `artifact` event.
- The sidebar shows navigation only until the API serves counts, team or budget. Made-up team, owner and budget values are removed everywhere on screen.
- Drop defaults for nodes without a form live in `lib/nodeForms.ts` `defaultInputs`.

## Pre-merge fixes (d91ac0c, after review)
1. **Re-snapshot on status events.** RunView now also re-snapshots on `run_status` and `node_status`; the events still apply at once. A page opened before the executor committed its NodeRun rows now fills in instead of staying on "Waiting for nodes…". This also narrows the snapshot-vs-event race listed under ceilings: the executor commits before it broadcasts, and only the newest snapshot applies.
2. **A failed retry re-syncs.** A 409 from Retry (retried elsewhere, or "still stopping") calls `load()`, so the node and button state refresh.
3. **Dead code deleted:** `api.runs.nodes`, `api.runs.artifacts` and the `NodeRun` interface, with their imports.
4. **"Started" in local time.** It now goes through `apiDate()` in lib/api.ts, which appends `Z` to naive UTC strings and keeps strings that already carry a zone. Without that guard, a timezone-aware backend would produce "…+00:00Z", which is an Invalid Date.
   - New test: it fails on this EDT machine with a bare `new Date()` (1 fail), and passes with the fix.
   - Other pages (/runs and /workflows `timeAgo`) still read these datetimes as local time; they were not touched.

**Proof:**
- `node --test "tests/web/*.test.ts"`: 12 pass, 0 fail.
- `tsc --noEmit`: exit 0.
- Live check rerun against NebiusHackathon's API (same setup as before): A–F as before. C now also caught the intermediate state, `Retrying…(disabled)` → `Running · no retry button` → `Failed · Retry node`.
- "Started" read 8:54:16 PM at 8:53 PM EDT local; before the fix it showed 12:32 AM for a run started at 8:32 PM.

**Untouched, as asked:** no admin token reaches the browser, and EndpointCountdown and `meta.api_key` are left for wave 3.

**Process note.** The rerun's teardown hung again and was backgrounded; I stopped it. uvicorn's graceful stop waits on the page's open WebSocket handler, which sits in Redis `listen()`, and that kept the output pipe open. The leftover test API on :8013 was killed with SIGKILL, and the ports were confirmed free.
