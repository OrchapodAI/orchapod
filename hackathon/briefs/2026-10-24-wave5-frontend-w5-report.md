# frontend-w5 report: wave 5 (2026-10-24 brief, queued line "frontend-w5")

**Status:** DONE. The four items in the dispatch, a README line, and the D7 screenshot prep below.
**Branch:** `hack/frontend-w5`, worktree `.claude/worktrees/frontend-w5`. Base b4813b8; `git merge-base --is-ancestor b4813b8 HEAD` passes. Not pushed.
**Spend:** $0. No key was used, no model was called and no container ran: the browser check stubs the executor.

## Commits (oldest first)
| SHA | What |
| --- | --- |
| aeb14d9 | feat(web): keep the run's cancel token in sessionStorage and send it on Cancel |
| 8e9fe6f | feat(web): /runs names and filters runs by RunOut.workflow_name |
| 9986dbb | feat(web): canvas Save on a workflow with runs offers "Save a copy" |
| 9fff34c | fix(web): /inference no longer asks for a HuggingFace token |
| 9295425 | docs(readme): visitors cancel only the runs they started; Save a copy on a workflow with runs |
| 8a0a7a5 | style(web): the cancel catch and capNote comments say what the code does |

## What was built
1. **Cancel token** (`apps/web/lib/api.ts`, `components/runs/RunView.tsx`).
   - `api.runs.start` and `api.agent.run` store the reply's `cancel_token` in sessionStorage under `orchapod:cancel-token:<run_id>`.
   - They return the reply without the token, so no page or React state ever holds it.
   - `api.runs.cancel` sends the token as `X-Orchapod-Cancel-Token`, and sends no header when this tab has none.
   - The token never goes to localStorage, a URL or a log.
   - If storage is switched off (Safari's SecurityError), the run still starts, and Cancel stays disabled.
   - **Run page (also embedded on /agent):** while a run is provisioning or running:
     - In the starter's tab, Cancel is enabled.
     - In any other tab, Cancel is disabled and shows "Only the tab that started this run can cancel it" (the button's `aria-describedby`).
   - Any failed cancel is now a toast (before, it was the header alert). A 403 reads "Couldn't cancel the run: Only the tab that started this run can cancel it (403)." (`explainError`).
2. **workflow_name** (`app/runs/page.tsx`, `lib/types.ts`).
   - /runs no longer calls GET /workflows, which returns only the newest 500.
   - The Workflow column, the filter (including `?q=` from the golden-run link) and the CSV export all read `run.workflow_name`.
   - The golden-run href is unchanged: `/runs?q=<plan name>`, which the smoke test pins.
   - `Run.workflow_id` is now `string | null`, as RunOut has it. That surfaced one grouping spot on /workflows, now null-safe (one line).
3. **Save a copy** (`app/canvas/[id]/page.tsx`, `api.workflows.copy`).
   - A 409 on Save (a workflow with runs is read-only to visitors) fills an always-mounted `role="status"` note: "This workflow has runs, so it is read-only".
   - The Save button becomes **Save a copy**. It POSTs the edited YAML as "<name> (copy)" and opens `/canvas/<copy id>`.
   - The page remounts on the new id, so the copy starts with a normal "Save draft". The original is untouched.
4. **hf_token removed** from `app/inference/page.tsx` (state, field and body) and from `DeployRequest`.
   - "Advanced options" now shows only when serving, where its one remaining field (served model name) lives.
   - The page is still hidden from navigation.
5. **Doc line.** README "The public app" (one line) states the cancel-token rule and Save a copy. backend-w5 does not touch README.

## Tests (tests/web/web.test.ts: 27 → 29)
- New: "a run's cancel token stays in this tab's sessionStorage by run id and leaves only as Cancel's X-Orchapod-Cancel-Token". It covers:
  - start and /agent/run both keep the token, under the right keys;
  - the callers never see `cancel_token`;
  - localStorage stays empty;
  - the header is sent, and no header goes out without a token;
  - no token appears in any URL;
  - storage switched off still starts the run.
  - The storage fakes work on Node 22 (CI, no Web Storage) and Node 26 (getters restored after the test).
- New: "canvas Save on a workflow with runs gets the API's 409 …; Save a copy posts the edited YAML as "<name> (copy)"".
- Extended: `explainError` has the 403-on-cancel sentence, and the static "no token reaches the browser" test now also fails on `hf_token` or `hfToken`.
- Mutation check: 9 of 9 caught. The mutations:
  - no header;
  - token kept in localStorage;
  - token left in the reply;
  - no try/catch on write;
  - no try/catch on read;
  - agent.run keeps no token;
  - copy keeps the original name;
  - 403 not readable;
  - hf_token back in the type.

## Proof
- `make check` on 8a0a7a5: rc 0, `All checks passed!`, `795 passed, 2 warnings`, web `pass 29 fail 0`, `SKIP stub e2e`.
- Each commit on its own (an exported snapshot): `node --test` passes 28/28/29/29 and `tsc --noEmit` exits 0 for aeb14d9, 8e9fe6f, 9986dbb and 9fff34c.
- `next build`: rc 0. gitleaks over b4813b8..HEAD: `6 commits scanned … no leaks found`.
- **Browser check against backend-w5's real API (f1139a9): 24 passed, 0 failed.**
  - Setup:
    - backend-w5's tree was exported with `git archive` to the scratchpad and run on :3190 with STUB=1 and a scratch SQLite database;
    - `executor.launch` was stubbed, so started runs stay provisioning and nothing runs;
    - Redis and MinIO came from our compose project;
    - the web app ran under `next start` on :3191;
    - both process groups were stopped by PGID, and nothing listens on 3190–3191 afterwards.
  - Checks:
    - the canvas Run stores a token of 40 or more characters, and localStorage stays empty;
    - in the starter's tab Cancel is enabled; in another tab it is disabled, with the note;
    - the API answers 403 without the token;
    - a tampered token gives the 403 toast;
    - the real token cancels the run (API status `cancelled`);
    - `RunOut.workflow_name` holds the workflow's name;
    - on the canvas, the data-prep dataset input was edited and saved: a 409, then Save a copy, which opens "fw5-check (copy)" carrying the edit (`gsm8k-w5-edit`); that copy saves fine, and the original is unchanged;
    - `/runs?q=fw5-check` makes no GET /workflows;
    - /inference has no HF token or password field;
    - an /agent one-click template enables Cancel, also after "Open run page ↗" in the same tab;
    - neither token appears in any request URL or console line.
  - The harness lives in the scratchpad (`run_check.py`, `pw/check.mjs`; not committed).
- Dry merges:
  - `git merge-tree NebiusHackathon hack/frontend-w5`: clean.
  - With hack/backend-w5 the only conflict is `apps/api/routes/internal.py`, the known backend-w5 vs NebiusHackathon one (take backend's side, per its report). backend-w5 changes none of apps/web, tests/web or README.

## Routes and states changed (screenshots, 1440x900 at 2x, git-ignored)
Folder: `/Users/hari/src/orchapod-hack/.claude/worktrees/frontend-w5/tests/ui/test-results/frontend-w5/`
- `/runs/{id}`, provisioning or running:
  - `run-cancel-starter.png`: the starter's tab, Cancel enabled.
  - `run-cancel-other-tab.png`: another tab, Cancel disabled with the note.
  - `run-cancel-403-toast.png`: a rejected token, the toast.
- `/agent`, embedded run view after a one-click template: `agent-run-cancel.png` (Cancel enabled).
- `/canvas/{id}` of a workflow with runs:
  - `canvas-409-save-a-copy.png`: after Save, the note and "Save a copy".
  - `canvas-copy-saved.png`: `/canvas/{copy}` named "fw5-check (copy)" after "Saved ✓".
- `/runs?q=<name>`: `runs-filter-workflow-name.png` (names from RunOut.workflow_name).
- `/inference` (hidden): `inference-no-hf-token.png` (Advanced open, served model name only).
- Unchanged names the smoke selects by: "Plan", "▶ Run", "Run template: <title>", the golden-run href, the run page tabs, "Cancel" and "Save draft". The one new accessible name is "Save a copy", shown only after a 409.

## D7 screenshot prep
- `run-view.png` (golden run mid-run) must be taken in the tab that started the run. Any other tab shows Cancel disabled with "Only the tab that started this run can cancel it".
- `canvas.png` ("Edit on canvas" from a fresh plan) has no runs, so the topbar shows the normal "Save draft". The canvas of the golden run's own workflow shows the read-only flow once Save is pressed.
- Capture from `next build && next start`, as docs/video-script.md says. The build is green.

## DECISIONs to record
1. **Cancel token in the browser.**
   - Key: sessionStorage `orchapod:cancel-token:<run_id>`, written only inside lib/api (start, agent.run) and stripped from the replies.
   - Without a token, Cancel is disabled with "Only the tab that started this run can cancel it".
   - Cancel failures are toasts.
2. **Read-only canvas.** A 409 on Save switches the button to "Save a copy" (POST "<name> (copy)" with the edited YAML, then navigate). Nothing checks for runs before Save.
3. **/runs** reads only `GET /runs?limit=500` and names runs by `workflow_name`. GET /workflows is no longer on that page.

## Open questions and limits
1. **Merge order:** backend-w5 first. On today's NebiusHackathon API, start returns no token, so with frontend-w5 alone Cancel is disabled in every browser.
2. **Substring filter.** `/runs?q=<plan name>` matches by substring, so the golden-run link also lists runs of "<plan name> (copy)" workflows, and pending runs a visitor creates from the golden workflow's canvas (POST /runs succeeds; the start is refused). Should `q` from the link match exactly? Not built; a few lines.
3. **Canvas Run uses the stored YAML** (unchanged behaviour). On a read-only workflow, a visitor's edits run only through Save a copy, then Run on the copy.
4. **A new tab loses Cancel**, even for the starter (sessionStorage is per tab, by the brief's rule). A copy of a copy is named "<name> (copy) (copy)".
5. **Stale docstring for backend.** `list_workflows` in apps/api/routes/workflows.py says the runs page names runs from that list.
6. **For qa.** The smoke test selects nothing that changed. scripts/e2e_demo.py's cancel still needs the token (already a qa follow-up in STATE).
