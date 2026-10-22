# frontend-w7 report: the fresh-clone frictions F5 and F7, rounds 1 and 2 (brief 2026-10-22-freshclone-fixes.md, evidence 2026-10-22-qa-w10-report.md)

**Status:** DONE. Round 1 (plan card, sidebar) and round 2 (run view, page title, compare label) are done and checked in a browser; the concerns (§7) are notes for others.
**Branch:** `hack/frontend-w7`, worktree `.claude/worktrees/frontend-w7`. Base 450389e (`git merge-base --is-ancestor 450389e HEAD` passes). Not pushed.
**Spend:** $0. No key, no model call, no container, no e2e, no smoke.

## Commits
| SHA | What |
| --- | --- |
| 2ea3305 | fix(web): the sidebar links only to pages with content; the three "Coming soon" pages go |
| 548b1f3 | fix(web): /agent scrolls a new plan or error into view |
| 552a946 | docs(hackathon): frontend-w7 report |
| **round 2** | |
| b56829f | fix(web): /agent scrolls the run view into view when a run starts |
| 75af5c3 | fix(web): the page title is "Orchapod" and the description says what the agent does |
| ba68f54 | fix(web): a compared side is "tuned", not "tuned · tuned" |
| (this file) | docs(hackathon): frontend-w7 report, round 2 |

Code touched: `components/Sidebar.tsx`, `app/agent/page.tsx`, `app/layout.tsx`, `components/runs/ComparePlayground.tsx`, `components/runs/EvalView.tsx`, `lib/results.ts`, three deleted pages, `tests/web/web.test.ts`. No new file, no new dependency.

## 1. /agent: a new plan is scrolled into view (qa-w10 F5, round 1)
- Two refs (the plan card, the error callout) and two effects in `app/agent/page.tsx` call `scrollIntoView({ block: "nearest" })` when `reply` or `error` changes. The error callout is included because F5 measured it off screen too ("the 503 message of an unkeyed API at y=1039"): it is what a visitor without keys sees first.
- A card that fits ends at the bottom of the window; one taller than the page area starts at its top, so its title stays visible; one already in view does not move.
- No unit test (a DOM call, no pure function). **Browser check, one line:** at 1024×768 with the five template cards, fill the intent box, press Enter and read `getByLabel("Plan", { exact: true }).boundingBox()`: top 1028, bottom 1601 (off screen) before; top 195, bottom 768 after. The error callout: 1028 to 1091 before, 705 to 768 after. In a 1024×520 window: top 52, title in view.

## 2. Sidebar: no "Coming soon" page (qa-w10 F7, round 1)
- Datasets, Cost & GPUs and Settings were the three placeholders. Nothing else linked to them (no page, test, script, README or doc: grepped), so the pages are deleted with their links, and so is the Operate group they left empty. The sidebar is seven links in two groups; the three routes answer Next's 404.
- **Test:** reads the sidebar's links and fails for one that has no page or whose page says "Coming soon" (case-insensitive). Mutation checks 5/5. Browser: each of the seven pages loads with no "coming soon".

## 3. /agent: the run view is scrolled into view (round 2)
- One ref and one effect keyed on `runId` in `app/agent/page.tsx`: `scrollIntoView({ block: "nearest" })`, the same pattern as the plan card.
- **Round 1 said the run view is below the fold after Run; I had not measured it.** Measured now: `LogStream.tsx:30` already calls `scrollIntoView({ behavior: "smooth" })` (block "start") when its log count changes, its first render included, and that scrolls every scrollable ancestor, the page too. So once the run view has its first reads the page ends up scrolled to it by accident; until then nothing happens. What the effect fixes is that gap, which grows with the API's latency.
- No unit test (a DOM call). **Browser check, one line:** at 1024×768, press Run on the plan card with the run endpoints answering in 1.5 s and read the run view card's `boundingBox()` 300 ms later: top 784 (off screen) before, top 208 to 768 (fully in view) after. Once loaded both end at top 80 to 85 (`LogStream`'s scroll).

## 4. Page title and description (qa-w10 F7, round 2)
- `app/layout.tsx`: `title: "Orchapod"` and `description: "Orchapod — one sentence to a tuned, evaluated model on Nebius Token Factory and AI Cloud"`. `og:description` and the Twitter card inherit the description; `openGraph.title` stays "Orchapod.ai". Read in a browser from the served HTML: `<title>Orchapod</title>`, the meta description and `og:description` are the sentence (before: "Orchapod — LLM Fine-tuning Platform" and the long tagline).
- **Nothing else in `apps/web`, the README or the OG image text says "LLM Fine-tuning Platform"** (grepped case-insensitively over the whole repo minus the briefs). The one other hit is outside my path: `apps/api/main.py:51`, `description="Control plane for the Orchapod.ai LLM fine-tuning platform."`, which the API's `/docs` page shows.
- The existing web test that keeps made-up text off the pages now also fails for the old title (mutation 2/2: layout.tsx, the OG image).
- README, Devpost and the OG image keep the longer tagline ("Describe the specialist model you want in one sentence. …"); the page description is now the shorter sentence you gave.

## 5. A compared side is "tuned", not "tuned · tuned" (qa-w10 F7, round 2)
- In the seeded golden run (what a judge sees) the base side is the Hugging Face id and the tuned side is the LoRA adapter, which vllm-serve serves as `tuned`: label "tuned", model "tuned". `refName(label, model, sep)` in `lib/results.ts` names a side by its label and adds the model only when it differs. The dropdown and the eval footer use it; the result panes apply the same comparison.
- Before and after, read in a browser from the golden run's own data:

| Where | Before | After |
| --- | --- | --- |
| compare dropdown | `base · meta-llama/Llama-3.2-3B-Instruct`, `tuned · tuned` | `base · meta-llama/Llama-3.2-3B-Instruct`, `tuned` |
| compare result panes | `base meta-llama/Llama-3.2-3B-Instruct`, `tuned tuned` | `base meta-llama/Llama-3.2-3B-Instruct`, `tuned` |
| eval footer (`EvalView`) | `base meta-llama/Llama-3.2-3B-Instruct · tuned tuned` | `base meta-llama/Llama-3.2-3B-Instruct · tuned` |

- **Test (one, the label logic is pure):** it runs `modelRefsOf` on the golden run's refs and checks `refName` for a model that differs, a ref labelled by its artifact (`deploy.model_ref`), a missing model and the eval line's separator. Mutation checks 5/5. The eval footer is the one place beyond the line you named; it had the same word twice.

## 6. Gate
- Web tests 36 → 38 (round 1 added the sidebar test, round 2 the label test); `pnpm exec tsc --noEmit` clean; `pnpm build` compiles; `make check PY=python` (no E2E): ruff "All checks passed!", 1123 passed (2 warnings), web 38/38; `pytest tests/docs`: 27 passed.
- Browser checks are a scratch script (a mock API, `next dev` on my own ports, Chromium; every process it started was killed). The screenshots of both rounds were deleted, as asked.

## 7. Concerns and notes
1. **Commit trailer:** `Co-Authored-By: Claude Sonnet 5.5`, the one the harness gives this session and the role file (`.claude/agents/frontend.md:23`) asks for.
2. **For backend:** `apps/api/main.py:51` still says "LLM fine-tuning platform" on `/docs`.
3. **`LogStream.tsx:30` moves the page, not only its log pane:** `scrollIntoView` on the tail sentinel, on every new log line, scrolls every scrollable ancestor. On /agent the page therefore jumps back to the run view as lines arrive, even if a visitor scrolled up to the plan. Scrolling the pane alone (`el.scrollTop = el.scrollHeight` on the log container) would stop that. Not changed: it is not in the brief, and the pane's own scroll to the tail is what the run page needs.
4. **For the smoke (orchestrator):** nothing it pins changed. It finds the plan card by its `Plan` label, never reads the page title, the dropdown or the pane headers, and its playground step counts the two "done" lines.
