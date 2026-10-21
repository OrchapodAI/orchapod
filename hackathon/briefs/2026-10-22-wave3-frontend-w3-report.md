# frontend-w3 report — wave 3 (2026-10-22)

**Status:** done. Items 1 and 2 of my section, plus the tf-finetune `timeout_min` cap you asked for, are built and verified.
**Branch:** `hack/frontend-w3`, base `ef00bb7` (`git merge-base --is-ancestor b6c26ff HEAD` → 0).
**Cost:** $0. No model calls; everything was proven with unit tests and a mocked API.

| SHA | Commit |
| --- | --- |
| `0411227` | feat(web): tf-finetune timeout_min caps at 85, under the 90-minute node limit |
| `ab971d6` | feat(web): eval view, dataset card and compare playground replace the legacy endpoint tab |
| `f893b06` | feat(web): template gallery with one-click Run on /agent |
| `6d7936d` | docs(readme): template cards and the run's result views |

Each commit is green on its own: I checked tsc plus the web tests at every step (13, then 20, then 21 tests).

## What was built

### 1. Eval view and the intent #2 result card
- **Where it shows.** The run view now has result tabs: on `/runs/{id}` and embedded on `/agent`. Everything comes from `GET /runs/{id}/summary`.
- **Auto-open.** When a run succeeds, the view switches once to its result: the eval if there is one, otherwise the dataset. After that, the tab is the user's choice.
- **Eval tab** (`components/runs/EvalView.tsx`), per the contract's eval_summary schema:
  - Win-rate stat, with the formula "(wins + ½ ties) ÷ N verdicts".
  - A stacked W/T/L bar with counts. Errors are counted separately and marked "left out".
  - Consistency.
  - Exact match (base → tuned), only when present.
  - Base, tuned and judge models, decoding, "n of N rows judged", and a STUB badge.
- **Where the eval numbers come from.** The headline numbers are read from judge-eval's `metrics_json` metadata. Per the contract that is the eval_summary without samples, stored in the DB, so the numbers need no storage fetch.
- **Judged samples.**
  - They come from the `eval_summary` file via `GET /artifacts/{id}/download`.
  - The fetch sends no headers, so the browser does no CORS preflight before the 307 to storage.
  - Each row is a native `<details>` element: question, reference, base vs tuned answers (with exact-match ✓/✗ when set), both judgments ("Judge, tuned shown first: picked tuned." plus the reasoning), and the context passage with its source.
  - Scraped text is rendered as text. Only `http(s)` source URLs become links; a `javascript:` URL stays plain text (tested).
  - Rows past `n_judge` show "not judged"; rows with an error show "error".
- **Dataset tab** (`components/runs/DatasetCard.tsx`). This is the intent #2 result card.
  - It reads the **last data-prep node** (synth's raw output is also named `dataset`, so it is skipped).
  - Shows a "Download dataset (JSONL)" link to `GET /artifacts/{id}/download`.
  - Shows rows, train/eval/test counts, and what was dropped (exact and near duplicates, low quality, unreadable).
  - Has one card per entry in `fields`: distinct values, nulls, min → max, and a bar chart of the top values. A field where every value is unique shows "Every value is different." instead of bars.

### 2. Template gallery, legacy endpoint tab removed, compare playground
- **Template gallery on `/agent`** (from `GET /agent/templates`). It replaces the hard-coded example intents.
  - Each card shows title, intent and estimate ("$0.15 · ~5 min").
  - **▶ Run** (aria-label "Run template: <title>") turns the template into the plan card (plan, rationale, estimate) and posts it to `/agent/run`. The embedded run view and the report card then follow, as for a planned intent.
  - **Use intent** fills the text box so Nemotron plans it instead.
  - Error state: an amber "Templates unavailable" box with the reason (for example "The API at … has no /agent/templates route yet (404).").
  - backend-w2 merged during my wave. The merged route returns exactly the shape I coded against (`{slug, title, intent, rationale, plan, estimate}`), and I used its three template files as test fixtures.
- **Legacy endpoint tab deleted.** This removes:
  - `EndpointCountdown` (Vast.ai `/inference/extend` and its preview call, now gone from `lib/api.ts`).
  - `TryItChat` (the browser called the endpoint directly, using `meta.api_key`).
  - The API-key display and copy button, the OpenAI snippet that embedded the key, and the "Open endpoint" header link.
  - A guard test now fails if any web source reads `.api_key`, sends an `Authorization` header or calls `/inference/extend`.
- **Compare tab** (`components/runs/ComparePlayground.tsx`). It appears when the run has at least two usable ModelRefs.
  - Where the models come from: the eval's base and tuned first, then any `model_ref` / `base_model_ref` artifacts, de-duplicated. An endpoint's `expires_at` is kept from its artifact.
  - judge-eval's own llama-server refs (`api_key_env ""`) are left out, because that server stops with its container. So intent #3 has no Compare tab.
  - The UI: two selects (Model A, Model B), one prompt, and Compare/Stop. Output streams side by side through `POST /compare` (SSE `{i, delta}`, then `{i, done, usd}`). Each side ends with "done · $x".
  - Each ref is sent with exactly its four ModelRef keys, so no key or token is ever sent.
  - Endpoint expiry is shown read-only: "Endpoint expires at …". There is no extend button.
  - Error state: a "Couldn't compare" box (a 404 until backend-w3 lands, or the server's 422 detail for a refused pair).
- **tf-finetune `timeout_min`:** max 85 in `nodeForms` (it matches `TFFinetuneInputs le=85`). The node panel renders `max=85` with a red border above it. Help text: "At most 85, so the node cancels its job before the run's 90-minute node limit stops it."

**Doc line:** README "Locally, from the Agent" (6d7936d). It names template one-click runs and the eval, dataset and compare views. I put it on line 143 because devrel-w3 edits lines 144–145; a dry-run merge is clean.

## Proof
- `. .venv/bin/activate && make check` in the worktree → exit 0:
  - ruff: "All checks passed!"
  - pytest: "395 passed, 2 skipped, 55 warnings"
  - web: "ℹ tests 21 · ℹ pass 21 · ℹ fail 0"
  - "SKIP stub e2e: set E2E=1".
- The 9 new web tests (tests/web/web.test.ts):
  - timeout_min max 85.
  - GET /agent/templates.
  - `compare()` posts the body and parses SSE frames split mid-JSON across chunks, plus comments.
  - A refused pair returns a readable 422.
  - Artifact content is fetched with no headers.
  - The eval reads metrics_json plus the samples URL.
  - The dataset card reads the last data-prep node, never synth's.
  - ModelRefs: order, de-duplication, kept expiry, llama-server refs left out.
  - No token in the browser.
- `next build` → compiled; 16 routes generated.
- **Headless UI check: 60/60.** A scratch script (not committed) at `/private/tmp/claude-501/-Users-hari-Desktop-hackathon/066c0f1b-32ee-4418-ae97-33bd3cc37ec5/scratchpad/uicheck/check.mjs` runs a mock API on :8093, a mock storage origin on :8094 and `next dev` on :3093, then drives headless Chromium through every state below, reading text only. Final run: "60 passed, 0 failed", with no page errors. It covered:
  - The eval numbers, sample details and link safety.
  - The dataset card for intent #1 and intent #2.
  - The compare stream and its exact request body.
  - One-click Run of the movie template to its dataset card and report.
  - Templates 404, samples blocked by storage CORS, compare 404 and compare 422.
- Dry-run merges (`git merge-tree --write-tree`) are clean against NebiusHackathon (10168de, with backend-w2 and data-w2) and against hack/devrel-w3, qa-w3, backend-w3, ml-w3, data-w3 and platform-w3.

## Routes and states for the screenshots
Real data needs STUB runs: intent #2 works now; the intent #1 eval needs ml-w3's judge-eval, and Compare needs backend-w3's /compare.
1. `/agent`: the gallery of 3 cards. States: "Loading templates…", loaded, and "Templates unavailable" (API down or old).
2. `/agent` → ▶ Run on "Synthetic movie likes, shares and subscribes": the plan card with the template plan, the embedded run view, which opens on **Dataset** when the run succeeds (rows, counts, Download, field cards), and the report card below.
3. `/runs/{id}` of an intent #1 run: opens on **Eval** (win rate, W/T/L, consistency, models and judge line). Expand one sample to show both judgments and the context. States: samples loading, and "Couldn't load the judged samples" (storage unreachable).
4. `/runs/{id}` of an intent #3 run: Eval with the "Exact match base → tuned" line; no Compare tab.
5. `/runs/{id}` → **Compare**: Model A/B selects with "Endpoint expires at …", a prompt, two columns streaming, then "done · $x". Error state: "Couldn't compare".
6. `/canvas/{id}` → a tf-finetune node panel: Timeout (minutes) with a red border at 90, and the help text.

Selectors for qa-w3's Playwright smoke:
- Template Run button: role button, name "Run template: <title>".
- Tabs: role button, name `/^eval$/i`, `/^dataset$/i`, `/^compare$/i`.
- Compare prompt: label "Prompt"; submit button "Compare".
- Download: role link "Download dataset (JSONL)".

## What does not work yet / limits
- **Compare** shows the 404 state until backend-w3's `POST /compare` lands. If a stream ends without `done`, that side shows "stopped before done". The contract has no mid-stream error event; if backend-w3 adds `{i, error}`, it is a one-line change to show it.
- **Downloaded file name:** the browser saves the dataset as `dataset`, without `.jsonl`, because the `download` attribute is ignored across origins. Fix in backend: add `ResponseContentDisposition` to `presigned_download_url`.
- **Unreachable storage host:** presigned URLs use `ORCHAPOD_R2_ENDPOINT`. Inside compose that is `http://minio:9000`, which a browser cannot resolve. This already affects the artifact download links; it is fine when the API runs on the host (localhost:9000).
- **Hosted samples need storage CORS:** in the hosted app, the samples fetch needs a CORS rule on the Nebius Object Storage bucket (GET from the web origin). MinIO allows any origin by default. If that rule is missing, the eval numbers still render and the samples show the readable error.
- **Out of scope, not changed:** the hidden legacy `/inference` page (off-nav, P2 deletion) still posts a user-typed `hf_token` and shows an `api_key="orchapod"` snippet.

## Open questions
1. **ml-w3:** I render `exact_match.base` / `.tuned` as fractions from 0 to 1 (shown as %). Please confirm they are not counts. judge-eval must also call `io.write_metrics` with the eval_summary minus `samples`, **including the `base`/`tuned` ModelRefs**, as the contract says. The eval tab and Compare's model list read them from there.
2. **Product:** should `/` redirect to `/agent` (the gallery) instead of `/workflows`, so judges land on the templates? It is a one-line change; I left it.
3. **platform-w3 (hosting):** include the bucket CORS rule from the limits above.

## DECISION candidates for STATE.md
- DECISION 2026-10-22: the eval view reads its numbers from judge-eval's `metrics_json` (DB) and fetches only the samples from the `eval_summary` file. Eval, Dataset and Compare are tabs of the run view (and so also on /agent), and a succeeded run opens its result once. — frontend-w3
- DECISION 2026-10-22: the legacy endpoint tab (countdown + Vast.ai extend, Try-it chat with `meta.api_key`, key snippet) is deleted. The compare playground replaces it (POST /compare, keys server-side), and Serverless endpoint expiry is read-only. — frontend-w3

## Files
- apps/web: `app/agent/page.tsx`, `components/Callout.tsx` (moved out of the agent page), `components/canvas/NodePanel.tsx`, `components/runs/{RunView,EvalView,DatasetCard,ComparePlayground}.tsx`; `components/runs/{EndpointCountdown,TryItChat}.tsx` deleted; `lib/{api,types,nodeForms,results}.ts`
- tests/web/web.test.ts
- README.md (1 line)
