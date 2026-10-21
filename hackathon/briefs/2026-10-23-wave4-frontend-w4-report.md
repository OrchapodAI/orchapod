# frontend-w4 report (wave 4, items 1–2)

**Status: DONE.** Branch `hack/frontend-w4` on base e3c289b (`git merge-base --is-ancestor e3c289b HEAD` OK). Resumed after the 03:00Z restart: the two uncommitted files (lib helpers + tests) were checked with `git diff`, kept and finished. No dev server left running (3100–3120 and 3187/3188 free). Cost: $0 (no model call, no cloud). No new npm dependency.

## Commits
| SHA | What |
| --- | --- |
| 9a6df5d | feat(web): error toasts, honest error and empty states, OG image and social metadata |
| cfe6313 | feat(web): the loss chart fills from the fine-tune's loss_curve on load; live events append |
| 97ebd87 | feat(web): /agent demo-mode banner, no-templates state, and template cards that honour `fits` |
| cd67eba | docs(readme): the /agent demo banner and `fits`, and the run page's loss chart |
| de37137 | test(web): a loss-curve row wins over a live event at the same step and keeps its valid_loss |
| c38e119 | refactor(web): runTemplate needs no cap guard; its Run button is already disabled |

Each feature commit was verified on its own (index exported to a temp dir: tsc clean, web tests green: 23, 25, 27).

## Proof
- `make check` (worktree root, venv): rc=0. Output: `All checks passed!` (ruff) · `551 passed, 126 warnings` (pytest) · web `ℹ tests 27 ℹ pass 27 ℹ fail 0` · `SKIP stub e2e: set E2E=1` (orchestrator only).
- `npx tsc --noEmit -p .` (apps/web): exit 0. `next build`: exit 0, 17/17 static pages, `○ /opengraph-image` static; the prerendered /agent head carries og:title/description/site_name/type, og:image (1200×630 PNG, alt) and the twitter `summary_large_image` tags.
- Browser check, throwaway (not committed): headless Chromium through the Playwright 1.63 already installed in qa-w3's tests/ui (read-only use), `next dev` on 127.0.0.1:3188 with the API URL set to :3187, where nothing listens. Every API call and the run WebSocket are fulfilled by Playwright routes, so no other service was reached. **50 passed, 0 failed**, including "no page or console errors" on every page (deliberate 4xx/5xx `Failed to load resource` lines allowed only in the failure cases). It also replays qa-w3's selectors (below).
- Mutations against the new tests: **9/9 caught**: fits undefined treated as over the cap; full instead of reduced estimate; golden-run link without its filter; banner without the cap clause; toast without the reason; no file fallback for the loss curve; event overriding a curve row (this one was missed first, hence de37137); train_loss ignored; live events not appended.

## Item 1: D6 polish
- **Error toasts**: one component, `components/Toaster.tsx` (in the root layout; bottom right, `role="alert"`, Dismiss, 8 s, at most 3, a repeated text shows once). `lib/api.ts` `toast()` / `toastError(what)` (a window event; a no-op outside the browser) raise `"<what>: <explainError(err)>"`. Used where a failure had no display of its own: list loads on /runs, /workflows, /artifacts, /models and /registry (before: unhandled rejections that left "No runs yet" etc. on screen); the canvas load, Save, Run and Start; clipboard copy; the loss-curve file. Inline errors that exist (the /agent Callouts qa-w3 depends on, RunView's header, EvalView, Compare) are unchanged.
- **Empty states**: no templates (/agent); no runs (/runs, now pointing to the Agent's templates); no artifacts (/artifacts, plus a link to the Agent; the run page's artifacts tab says when a finished run produced none); and the honest "Couldn't load …" states above.
- **Loading states**: canvas (was endless "Loading…" on a failed load), /runs subtitle, /artifacts count, and "Loading the loss curve…".
- **OG image + metadata**: `app/opengraph-image.tsx` (next/og, which ships inside Next; its bundled font, so the build needs no network). layout.tsx: description = the Devpost tagline, Open Graph + Twitter card, `metadataBase` from `NEXT_PUBLIC_SITE_URL` (default http://localhost:3000). The document title is unchanged.
- **Demo-mode banner** (/agent, `role="note"`): "Demo mode. Every run shows its estimated cost before you press Run: $low to $high for the templates below. Public runs are capped per run and per day; a template above the per-run cap links to its golden run instead." Worded from GET /agent/templates (the reduced estimates one-click Run posts) and `fits`; it has no endpoint of its own. The last clause appears only when some `fits` is false. The generic sentence shows while loading or if templates fail.

## Item 2: `fits` and the loss chart
- `fits?: boolean` on AgentTemplate (undefined = runnable; checked against backend-w3's branch: `fits = reduced.estimate.usd <= run_cap(scale)`). `fits === false` → Run disabled, `aria-describedby` → "about $X — above the public demo's per-run cap; watch the golden run" (X = reduced estimate). "watch the golden run" links to `/runs?q=<plan name>`, and /runs now reads `q` into its filter. The golden run's workflow is named after the plan (`real-estate-compliance-llama-3b` in backend-w3's scripts/golden-run.json).
- Loss chart: on load, `lossSources(summary)` finds each tf-finetune / unsloth-train node's curve, in its metrics_json meta (tf-finetune, run.py:140) or else in the file behind the artifact's download link: unsloth-train's `train_metrics_json` has no meta (run.py:177), and write_metrics cuts meta above 16 KB to `{truncated: true}`. The file is fetched once, when the chart tab opens. `lossPoints` merges the curve rows (`{step, train_loss, valid_loss}` or `{step, loss}`) with live `progress` events for steps the curve lacks, sorted by step. The curve's own point wins over an event at the same step. A valid-loss line and legend appear when present. A run with no training node says so.
- Tests (tests/web/web.test.ts, 5 new tests; 22 → 27): capNote (false/true/undefined), demoNote, toastError, lossSources (meta / unsloth file / truncated meta / no trainer), lossPoints (tf rows, unsloth rows + events with dedupe, events alone, curve precedence).

## Routes and states for the Orchestrator's screenshots
- `/agent`: banner; a `fits: false` card (anonymous scale 0.1 gives real-estate's reduced $0.88 > $0.30 cap) with Run disabled, the note and the golden-run link; an empty template list.
- `/runs`: API down → toast + "Couldn't load runs"; empty → "No runs yet" + Agent link; `/runs?q=real-estate-compliance-llama-3b` → only the golden run.
- `/artifacts`, `/workflows`, `/models`: API down → toast + "Couldn't load …"; `/artifacts` empty → Agent link. `/registry`: API down → one toast.
- `/canvas/<unknown id>`: reason + "← Workflows" (+ toast); Save/Run failures → toasts.
- `/runs/<golden run id>` → chart tab: train + valid loss from the seeded tf-finetune metrics (2 checkpoints in the STUB fixture); a data-only run → "This run has no training node…"; artifacts tab of a finished run with none.
- Link previews: `/opengraph-image` (1200×630).

## qa-w3 compatibility (add, don't rename)
No accessible name, heading or route was renamed. Re-checked in the browser run: `getByLabel("What should Orchapod build?")`; `button "Plan"` (exact); the plan name appears exactly once; the plan card's "2 nodes", single `title="Estimated cost and wall time"` matching `^\$0\.15 · ~\d+ min$`, and `▶ Run`; runFromGallery's XPath finds exactly one `/run/i` button per template card (the golden-run link is a link, not a button); the run page's `logs` tab. qa's smoke runs with ORCHAPOD_ANON_SCALE=1, so `fits` is true there; at the anonymous scale the real-estate card's Run is disabled by design.

## For the Orchestrator (cross-team / DECISION)
1. **platform-w4**: apps/web/Dockerfile should pass `NEXT_PUBLIC_SITE_URL=https://app.<domain>` as a build arg, next to NEXT_PUBLIC_API_URL/_WS_URL. Without it the hosted og:image and twitter:image URLs point at http://localhost:3000. Worth a line in docs/HOSTING.md or .env.example. I did not message platform-w4: agent names stopped resolving after the restart, and the hosting files are theirs.
2. DECISION candidate: the golden-run link is a filtered run list (`/runs?q=<plan name>`), not a fixed run id. It keeps working after D8's `--export` re-seed, as long as the golden run was launched from the template. A direct link would need a known id (e.g. a build arg) and was not worth a config value now.

## Not done / ceilings
- Two fine-tune nodes in one run share one chart line (`ponytail:` in lib/results.ts).
- The chart keeps its old dark-on-light colours. Pages keep the single document title (they are client components). Toasts are for errors only.
- A metrics artifact that lands after the chart tab is open refetches the file curves once more (rare; cheap).
- `make check E2E=1` and qa's `make ui-smoke` were not run (orchestrator/qa).
