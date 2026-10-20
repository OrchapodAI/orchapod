# Wave 1 report: frontend-w1 (2026-10-20)

**Status: DONE_WITH_CONCERNS.** Both tasks are done and proven. The concerns are environment and harness issues the Orchestrator should know about before taking screenshots or merging (see "Concerns").

**Branch** `hack/frontend-w1` @ `1ee175e` (worktree `.claude/worktrees/frontend-w1`). `git merge-base --is-ancestor 178d2e6 HEAD` passes. Nothing pushed.

| SHA | Commit |
| --- | --- |
| `e85fd52` | fix(web): load postcss config as ESM (.mjs), so `next build` passes on Node ≥ 22.12 |
| `41c2903` | feat(web): palette shows only nodes with containers; forms for web-research, tf-finetune, tf-deploy, judge-eval; object inputs as JSON (R13) |
| `3db87c5` | feat(web): /agent page with chat box, plan card, live run view and report card |
| `1ee175e` | fix(web): 503 explanation keeps the server detail last |

## What was done

### 1. Palette, config forms, R13
- **Palette** (`apps/web/components/canvas/NodePalette.tsx`): hf-import, file-upload, s3-import and auto-label-cleanlab are hidden (none has a `containers/` dir). The demo path comes first: Research, Synth Data, Data Prep, Fine-tune, Deploy, Evaluate; then HF Download, Train, Distill, Quantize, Serve, Benchmarks.
  - Label, icon and colours now come from `NODE_META` (`OrchaNode.tsx`), so a new node is added in one place.
  - New runtime badge `api`.
  - lm-eval is relabelled "Benchmarks" so that "Evaluate" means judge-eval.
- **Config forms** (`apps/web/lib/nodeForms.ts`, rendered by `NodePanel.tsx`) for web-research, tf-finetune, tf-deploy and judge-eval. They carry every contract input with its default and help text from docs/contracts.md.
  - Field kinds: text, number, bool, list (one item per line) and json. A json field holds an object when the text parses as JSON, and the text as typed otherwise (refs, model ids), which covers ModelRef inputs.
  - Inputs whose default the node computes (tf-deploy `name`, judge-eval `n_judge`) show a placeholder and are only sent once filled in.
  - A dropped node starts from the form defaults.
  - Generic (non-form) fields now show object values as JSON instead of `[object Object]`.
- **R13**: `buildYamlFromGraph` moved to `apps/web/lib/workflowYaml.ts`.
  - Object and list inputs are written as JSON, which YAML reads as flow mappings and sequences.
  - Strings that a plain YAML scalar would lose or misread are JSON-quoted: empty, multi-line, `key: value`, ` #`, leading or trailing spaces, a leading indicator. Numbers typed as text (`"16"`) stay plain, so they still load as numbers.
  - Bug fixed on the way: the old serializer dropped every `    type:` line from the workflow-level `inputs:` header. The header is now kept verbatim.
  - `inputs: {}` is written for a node with no inputs; the old code wrote a bare `inputs:`, which loads as null.
- **Canvas** (`app/canvas/[id]/page.tsx`):
  - Dropped nodes no longer get `resources: {gpu: 1xH100, provider_pref: [runpod, vastai]}`. That value was never written to YAML and named the deleted RunPod.
  - The minimap colours come from `NODE_META`.
  - The panel is keyed by node id.

### 2. The /agent page (`apps/web/app/agent/page.tsx`)
- **Chat box**: textarea with `maxLength` 2000 and a character counter; Enter sends and Shift+Enter adds a line. The three canonical intents from agent_knowledge.md are example buttons. Sending calls `POST /agent/plan {intent}`.
- **Plan card** shows:
  - the plan name and node count;
  - the total estimate, in $ and minutes;
  - the rationale;
  - a node table: #, id, type, literal model ids from the inputs (refs skipped, ModelRef `.model` shown), and the per-node estimate from `by_node`;
  - warnings in an amber callout and errors in a rose one.
- **Plan card actions**:
  - **Run** is disabled while `errors` is non-empty. A 422 from `/agent/run` puts the server's `errors` into the card, so Run stays disabled.
  - **Edit on canvas** writes `planYaml(plan)`, calls `POST /workflows`, then goes to `/canvas/{id}`.
- **Run**: `POST /agent/run {intent, plan}`, then the live run view.
  - The run page body was extracted, otherwise unchanged, into `components/runs/RunView.tsx`; `/runs/[id]` is now a 9-line wrapper.
  - On /agent, RunView is embedded, and its back link reads "Open run page ↗".
- **Report card**: polls `GET /agent/runs/{id}/report` every 5 s until `ready`, and stops on a 404.
  - It shows the status, $ spent against $ estimated, and the run error if there is one.
  - Once ready, it shows the markdown as pre-wrapped text (no new dependency).
- **Error state**: `req()` errors now carry `status`, `path` and the parsed `body`. `explainError()` in `lib/api.ts` turns each failure into one sentence:
  - network failure → "Can't reach the Orchapod API at …";
  - route missing → "… has no /agent/plan route yet (404)";
  - 402 → over budget;
  - 422 → the server's detail;
  - 502 → "Token Factory did not answer after retries";
  - 503 → kill switch on or NEBIUS_API_KEY missing.
  - No fixtures and no mock servers.
- Other changes:
  - The sidebar links "Agent".
  - `.btn:disabled` is styled (half opacity, not-allowed cursor); before this, disabled buttons looked enabled.
  - The default API/WS URL is `localhost:8001` in `next.config.ts`, `lib/api.ts` and `lib/ws.ts`, following the 8001 DECISION. 8000 is complychip2's.

### Also fixed (blocked the brief's proof)
`pnpm build` failed on the base commit with "Your custom PostCSS configuration must export a `plugins` key".
- Cause: `postcss.config.js` uses `export default` in a package without `"type": "module"`. Next 15.3 `require()`s `.js` configs, and Node's require(esm), unflagged since 22.12, returns the namespace object, so Next finds no `plugins` key.
- Fix: renamed the file to `.mjs`, the form Next and Tailwind v4 document. The CI web job, which runs Node 22, most likely fails the same way today; I can't see CI from here.

### Docs and tests
- Doc lines:
  - README.md, after the frontend start block: `/agent`, the `NEXT_PUBLIC_API_URL` default 8001, and `pnpm test`.
  - docs/WORKFLOW_SPEC.md: object inputs are written as JSON (R13).
- Tests: `tests/web/web.test.ts`, run with Node's built-in runner on TypeScript (Node ≥ 22.18 strips the types), so there is no new dependency. `pnpm test` in apps/web runs the same thing.

## Proof (worktree, HEAD 1ee175e)
| Command | Result |
| --- | --- |
| `node --test "tests/web/*.test.ts"` (repo root) | `tests 6 · pass 6 · fail 0` |
| same, with the pre-R13 serializer restored | `pass 4 · fail 2`: the R13 and buildYamlFromGraph tests fail. The API tests fail at import without the new `lib/api.ts` code. |
| `pnpm exec tsc --noEmit` (apps/web) | exit 0 |
| `pnpm build` (apps/web) | exit 0. Route table: `○ /agent 4.59 kB`, `ƒ /canvas/[id] 9.07 kB`, `ƒ /runs/[id] 286 B`. Before e85fd52: exit 1 (PostCSS `plugins` error). |
| `make check` (venv active) | exit 0: ruff "All checks passed!", "153 passed, 57 warnings", stub e2e SKIP (qa's script not written yet) |
| Round trip against the real API | See below |
| `next start` and `next dev --turbopack` smoke | `/agent` 200 with the form, the 3 examples, `maxLength="2000"` and the sidebar link; `/canvas/x` 200; no PostCSS errors. The server was stopped inside the same command. |

Round trip against the real API:
- Setup: `planYaml` output posted to a throwaway API (`uvicorn api.main:app` on 127.0.0.1:8011 with a scratch SQLite DB, stopped afterwards).
- The posted plan carried the intent #2 `row_schema` object, a prose string containing `: `, ` #` and a newline, a list containing `: `, a ref and a float.
- `POST /workflows` → 201, and `graph_json` inputs are exactly the plan inputs.
- `POST /agent/plan` on today's API → `404 {"detail":"Not Found"}`, which is the state /agent explains.

Cost: **$0** (no model calls, no keys).

## Routes and states to screenshot
**Ports first.** 8000 is complychip2. **8001 is currently held by another project too**: "complychip-ED local 3D map API" (uvicorn from `/Users/hari/Desktop/complychip-ed`, PID 78167). I identified it with one read-only `GET /openapi.json` and sent it nothing else. A bare `pnpm dev` now targets 8001, so /agent would POST to that app. For screenshots, point the web app at a free port.

A. **/agent error state (no API needed):**
1. `cd .claude/worktrees/frontend-w1/apps/web && NEXT_PUBLIC_API_URL=http://127.0.0.1:8011 NEXT_PUBLIC_WS_URL=ws://127.0.0.1:8011 pnpm dev -p 3001`
2. Open http://localhost:3001/agent and click "Generate synthetic data of movie likes, shares and subscribes", then **Plan**.
3. Expect a rose callout: "The agent couldn't plan this / Can't reach the Orchapod API at http://127.0.0.1:8011. Is it running?"

B. **/agent 404 state, palette and forms (needs our API on 8011):**
1. From the worktree root: `DATABASE_URL=sqlite+aiosqlite:////tmp/orchapod-shot.db PYTHONPATH=.:apps:packages/sdk-py uvicorn api.main:app --host 127.0.0.1 --port 8011`. Redis is not needed for this.
2. /agent, then Plan → "The API at http://127.0.0.1:8011 has no /agent/plan route yet (404)."
3. /workflows/new, YAML tab, enter a name, Create → `/canvas/{id}`. The palette is on the left: 12 items, none of HF Import, File Upload, S3 Import or Auto-Label.
4. Drag Research, Fine-tune, Deploy and Evaluate onto the canvas and click each one to see its typed form with help text.
5. Expect Save to return 422 "Unknown node type: web-research" until wave 2 registers the new types.

C. **Plan card, run view and report card** need the wave-2 Agent API. By the brief, there is nothing to show before then.

## Concerns and open questions
1. **Port 8001 collision** with complychip-ed (above). Our API cannot bind 8001 while that server runs. Hari's call: stop it, or move ours, in which case the web default, the DECISION and contracts' ORCHAPOD_CONTROL_URL default all follow.
2. **The web tests are not in `make check` or CI**, both of which qa owns.
   - Ask qa to add `node --test "tests/web/*.test.ts"` to `make check` and `pnpm test` to the CI web job.
   - Node ≥ 22.18 is needed; CI's `node-version: 22` resolves to it.
3. **pnpm 11 here vs pnpm 9 in CI.** pnpm 11's pre-run deps check fails on sharp's ignored build script (`ERR_PNPM_IGNORED_BUILDS`), so `pnpm exec` and `pnpm build` abort.
   - In my worktree I answered pnpm's own generated stub with an untracked `apps/web/pnpm-workspace.yaml` containing `allowBuilds: {sharp: false}`.
   - I did not commit it, because pnpm 9 in CI could treat the file as a workspace root.
   - Others on pnpm 11 need the same file, or `pnpm --config.verify-deps-before-run=false …`.
   - DECISION candidate: pin `packageManager` in package.json, or commit the file after a pnpm 9 check.
4. **The new node types are not registered yet.** They render and serialize, but `POST`/`PUT /workflows` (including the agent's Edit on canvas) returns 422 "Unknown node type" until wave 2 adds them to `NodeType` and `NODE_REGISTRY`. If data or ml rename inputs, `lib/nodeForms.ts` is the one place to change.
5. **Other port-8000 defaults outside apps/web**: `infra/docker-compose.dev.yml` (the api service publishes 8000, and the web service gets `NEXT_PUBLIC_API_URL=:8000`) belongs to platform. The CI web job's build env belongs to qa.
6. **Not touched (pre-existing):**
   - RunView never handles a failed `GET /runs/{id}` and shows "Loading…" forever.
   - Canvas drop defaults still carry synth `teacher_kind` and vllm-serve `keep_alive_min: 60`; those inputs change with data/ml in wave 2.
   - The report markdown is not rendered as markdown. Add a renderer once the report format settles.

## DECISIONS to record
- The web app defaults to API/WS `localhost:8001`, following the 8001 DECISION. See concern 1 for the live conflict.
- Web unit tests use Node's built-in test runner on TypeScript (`tests/web/*.test.ts`), with no test-framework dependency.
- "Evaluate" in the UI means judge-eval. lm-eval stays in the palette as "Benchmarks" (it has a container) but is off the demo path.
- `apps/web/postcss.config.mjs` replaces `postcss.config.js`.
