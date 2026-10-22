# frontend-w7 report: the fresh-clone frictions F5 and F7 (brief 2026-10-22-freshclone-fixes.md, evidence 2026-10-22-qa-w10-report.md)

**Status:** DONE. Both items are done and checked in a browser; two small web items from the same report are left for the Orchestrator (§4).
**Branch:** `hack/frontend-w7`, worktree `.claude/worktrees/frontend-w7`. Base 450389e (`git merge-base --is-ancestor 450389e HEAD` passes). Not pushed.
**Spend:** $0. No key, no model call, no container, no e2e, no smoke.

## Commits
| SHA | What |
| --- | --- |
| 2ea3305 | fix(web): the sidebar links only to pages with content; the three "Coming soon" pages go |
| 548b1f3 | fix(web): /agent scrolls a new plan or error into view |
| (this file) | docs(hackathon): frontend-w7 report |

Code touched: `components/Sidebar.tsx`, `app/agent/page.tsx`, three deleted pages, `tests/web/web.test.ts`. No new file, no new dependency.

## 1. /agent: a new plan is scrolled into view (qa-w10 F5)
- Two refs (the plan card, the error callout) and two effects in `app/agent/page.tsx` call `scrollIntoView({ block: "nearest" })` when `reply` or `error` changes: 9 lines added, 3 removed.
- The error callout is included because F5 measured it off screen too ("the 503 message of an unkeyed API at y=1039"), and that is what a visitor without keys sees first.
- A card that fits ends at the bottom of the window; one taller than the page area starts at its top, so its title stays visible; one already in view does not move. A one-click template Run sets the same state, so its plan card scrolls into view as well.
- **No unit test:** there is no pure function in it, only a DOM call. **Browser check, one line:** at 1024×768 with the five template cards, fill the intent box, press Enter and read `getByLabel("Plan", { exact: true }).boundingBox()`: top 1028, bottom 1601 (off screen) before; top 195, bottom 768 (fully in view) after. The error callout: 1028 to 1091 before, 705 to 768 after. In a 1024×520 window, where the card is taller than the page area: top 52, title in view.
- The check is a scratch script (a mock API, `next dev` on my own ports, Chromium; every process it started was killed); the plan reply is intent #1's six-node plan. Screenshots, untracked and not committed: `/Users/hari/src/orchapod-hack/.claude/worktrees/frontend-w7/screenshots-frontend-w7/` (`before-plan-card.png`, `after-plan-card.png`, `before-error-callout.png`, `after-error-callout.png`).

## 2. Sidebar: no "Coming soon" page (qa-w10 F7)
- Datasets, Cost & GPUs and Settings were the three placeholders (15 lines each). Nothing else linked to them (no page, test, script, README or doc: grepped), so by the brief's rule the pages are deleted with their links, and so is the Operate group they left empty. The sidebar is now seven links in two groups: Home, Agent, Workflows, Runs; Base Models, My Models, Artifacts. The three routes answer Next's 404.
- **Test** (`tests/web/web.test.ts`): reads the sidebar's links and fails for one that has no page or whose page says "Coming soon" (case-insensitive). Mutation checks, 5/5 caught: a link to a deleted page, a link to a route that never existed, a placeholder page and its link restored, "Coming soon" typed into /artifacts, "COMING SOON" typed into /models.
- Browser: the sidebar lists exactly those seven; each of the seven loads (HTTP 200) with no "coming soon" in its text; `/datasets`, `/cost` and `/settings` give 404.

## 3. Gate
- Web tests 36 → 37; `pnpm exec tsc --noEmit` clean; `pnpm build` compiles; `make check PY=python` (no E2E): ruff "All checks passed!", 1123 passed (2 warnings), web 37/37; `pytest tests/docs`: 27 passed.

## 4. Concerns and notes
1. **Commit trailer:** `Co-Authored-By: Claude Sonnet 5.5`, the one the harness gives this session and the role file (`.claude/agents/frontend.md:23`) asks for.
2. **Not scrolled:** after Run, the run view (and the report card under it) renders below the plan card, which at 1024×768 is below the fold again. The brief asks only for the plan card; the same one-line effect on `runId` would cover it. Say so and I will add it.
3. **Two other F7 items live in `apps/web`, not in this brief:** the page title is still "Orchapod — LLM Fine-tuning Platform" (`app/layout.tsx:10`), and the stub compare and eval show "tuned · tuned" because the label and the served model name are both "tuned" (`components/runs/ComparePlayground.tsx:49`, `components/runs/EvalView.tsx:73`).
4. **For the smoke (orchestrator):** nothing it pins changed: it finds the plan card by its `Plan` label (the ref does not touch it) and never opens the removed pages or the sidebar.
