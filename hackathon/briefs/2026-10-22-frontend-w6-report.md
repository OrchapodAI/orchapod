# frontend-w6 report: the web app after R24, R25, ml-w6 and backend-w7 (brief 2026-10-22-frontend-w6.md)

**Status:** DONE_WITH_CONCERNS. All four tasks are done or checked; the concerns (§5) are decisions for the Orchestrator, not failures.
**Branch:** `hack/frontend-w6`, worktree `.claude/worktrees/frontend-w6`. Base 97b749c (`git merge-base --is-ancestor 97b749c HEAD` passes). Not pushed.
**Spend:** $0. No key, no model call, no container.

## Commits
| SHA | What |
| --- | --- |
| 5477e1e | feat(web): palette lists the golden path first and drops tf-deploy; every description is true today |
| 2f7e210 | feat(web): quantize takes lora_adapter and judge-eval tuned_lora; tf-deploy's help says it is retired |
| 8eb7bbd | feat(web): the /agent report card gives up 60 s after the run ended, and its title renders as a heading |
| (this file) | docs(hackathon): frontend-w6 report |

Diff over the three code commits: 5 files, +118 −22 (`NodePalette.tsx`, `nodeForms.ts`, `runEvents.ts`, `app/agent/page.tsx`, `tests/web/web.test.ts`). No new file, no new dependency.

## What changed
1. **Palette** (`components/canvas/NodePalette.tsx`).
   - tf-deploy is off the palette. Its `NODE_META` and form stay, so an old workflow still renders (checked in the browser).
   - Order: web-research, synth-distilabel, data-prep, unsloth-train, vllm-serve, judge-eval, then tf-finetune, quantize, hf-download, distill-sft, lm-eval.
   - The four descriptions the brief gives are verbatim. `hf-download` now says "object storage" instead of "R2", which is not what a hosted run writes to.
   - The other six descriptions were read against the registry and the containers and are true today.
2. **Forms** (`lib/nodeForms.ts`).
   - `quantize` has a form now. A form replaces the generic input list, so it carries all six inputs of QuantizeInputs (`model`, `method`, `precision`, `bits`, `keep_f16`, `lora_adapter`). Otherwise template 3's `keep_f16` would have vanished from its panel. Dropped-node defaults are unchanged.
   - `lora_adapter` (quantize) and `tuned_lora` (judge-eval) are optional, have no default and are sent only once filled in. Their help is the contract's wording (docs/contracts.md "quantize", "judge-eval"), minus the backticks and the `(none; ml-w6: …)` wrapper.
   - tf-deploy's two help texts start "Retired, kept for old workflows only". judge-eval's tuned-model help no longer says "usually tf-deploy's".
   - A dropped unsloth-train node starts on `nvidia/Llama-3.1-Nemotron-Nano-8B-v1` (was `Qwen/Qwen3-4B-Instruct`), so it matches its palette text and the registry default.
3. **Report card on /agent** (`app/agent/page.tsx`, `lib/runEvents.ts`).
   - Check result: it already polled every 5 s while `ready` is false, also after the run ended, but never stopped.
   - New: the same single loop stops once a poll has seen the run finished for 60 s (`REPORT_WAIT_MS`) and shows "Report unavailable, see the run page" linking to `/runs/<id>`. A report that is ready always wins. The rule is the pure `reportNext(ready, endedAt, now)`; the page calls it, so the test covers what runs.
   - No second poller: no new timer, no new request. The deadline is read from the `status` the existing poll already returns.
   - The first line `## <plan>: <status>` renders as an `<h2>` (`splitReport`); the rest stays Markdown as written. Only that line: the API collapses the plan name to one line precisely so it cannot forge headings.
   - `<ReportCard key={runId}>`: a second run on the page starts with fresh state, so a "gone" or a stale report cannot carry over.
   - The field is `markdown`, which is what backend-w7's route (33353c6) and contracts.md return. The dispatch said `report_md`, which is the DB column.
4. **Template gallery**: checked, no code change (§4).

## Tests
- `tests/web/web.test.ts`: 30 → 34. New: the palette (order, and nothing the registry hides), the forms, the report polling rule, the report title. Extended: the dropped-node defaults test.
- The palette test reads the registry's `"hidden": True` rows from `packages/workflow_schema/models.py` as text, because the web job of CI has no Python. I compared that parse with the real `NODE_REGISTRY`: both give the same seven types (auto-label-cleanlab, distill-sft, file-upload, hf-import, lm-eval, s3-import, tf-deploy).
- `make check PY=python` (no E2E): ruff "All checks passed!", pytest 895 passed, 2 warnings, web 34/34. Also green: `pnpm exec tsc --noEmit` and `pnpm build` (both run in CI's web job).
- **Mutation checks**, each reverted after: palette 6/6 (tf-deploy, s3-import, hf-import, auto-label-cleanlab, file-upload back in; order swapped), forms 8/8, report rule and title 8/8.
  - Two survivors were real gaps and are fixed: `s3-import` slipped past both regexes (`[A-Z_]` and `[a-z-]` skip digits; the parse of the registry also missed it until I compared it with the real one), and the title split accepted any heading level.
- Not run, as instructed: `make ui-smoke` and any e2e.

## Visual check (scratch, not the repo's e2e)
- A mock API on :8917 and `next dev` on :3917, driven by Chromium from one foreground script in the scratchpad; every process it started was killed and the ports are free. Screenshots are untracked and not committed, in `/Users/hari/src/orchapod-hack/.claude/worktrees/frontend-w6/screenshots-frontend-w6/` (7 PNGs):
  1. `1-agent-templates-visitor.png`: five cards at ORCHAPOD_ANON_SCALE 0.1.
  2. `2-report-waiting.png`, `3-report-ready-heading.png`: the heading.
  3. `4-report-unavailable.png`: the message and link.
  4. `5-…`, `6-…`, `7-canvas-*.png`: palette order, the quantize and judge-eval forms, the retired tf-deploy node.
- Results: heading is an `h2` with no `## ` left; the card gave up at 70 s (run ended at ~6 s, first poll to see it ~10 s) with the link `/runs/<id>`, and made 0 report requests in the 12 s after. 16 requests in 70 s: 14 ticks of 5 s, the first, and one duplicate that React StrictMode's double effect run makes in `next dev` (not in production, and as before my change). No console or page errors.
- The smoke's strict locators still resolve to one element each: `getByText("<plan>: succeeded")` is the `h2`, `getByText("$0.00 spent of $0.15 estimated")` is unchanged, and the failure regex matches nothing.

## 4. Template gallery (task 4): checked, they say why
The five real templates as GET /agent/templates returns them (computed in-process from the base's planner, `fits` as the route computes it), through the page's own `capNote` and `demoNote`:

| Template | Reduced estimate | Rents a GPU | Visitor (scale 0.1, cap $0.30) | Admin |
| --- | --- | --- | --- | --- |
| Llama 3B real-estate | $0.96 | vllm-serve | Run disabled: "about $0.96 — above the public demo's per-run cap; watch the golden run" | Run |
| Movie likes | $0.03 | no | Run | Run |
| Maths GGUF | $0.02 | no | Run | Run |
| Nemotron Nano docs specialist | $2.32 | unsloth-train + vllm-serve | Run disabled, same note with $2.32 | Run |
| Nemotron Nano docs, CPU judge | $1.93 | unsloth-train | Run disabled, same note with $1.93 | Run |

The browser run shows the same cards. I changed nothing, for the reasons in §5.3.

## 5. Concerns and decisions for the Orchestrator
1. **DECISION: distill-sft and lm-eval stay on the palette.** The brief's order list names them, but the registry marks both `hidden` ("off the demo path"), and the brief also asks for a test that fails when "any type the registry hides" returns. I kept the explicit list and exempted exactly these two in the test (they have containers and run on a hand-built canvas). To drop them: delete two lines in `NodePalette.tsx` and the exemption in the test.
2. **DECISION: commit trailer is `Co-Authored-By: Claude Sonnet 5.5`.** The dispatch asked for Opus 5.5; my instructions say to use the trailer of the harness's attribution reminder, which names this session's model (Sonnet 5.5). Rewrite the three trailers if you want Opus.
3. **Task 4 left as it is; two things a visitor may notice.**
   - The note names the cap, never the GPU. `fits` folds both reasons (over the cap, and anonymous + a GPU node). The note is true for all five templates today, but it would say "above the cap" for a GPU template that is blocked only by its GPU, once ANON_SCALE is raised enough (0.32 or more puts real-estate's $0.96 under the cap of $3 × scale). Changing the wording also needs QA's `tests/ui/smoke.spec.ts` (it pins the exact accessible description and the link for every `fits: false` template) updated in the same merge, so I did not touch it.
   - "watch the golden run" on the two docs cards links to `/runs?q=nebius-docs-specialist-nemotron-nano-8b[-cpu]`, which shows "No runs match your filter": the committed fixture is the real-estate STUB run (scripts/seed-golden-run.py, TODO(D8) export). It resolves once the docs golden run is exported; the smoke pins this link too.
4. **Tests live outside `apps/web/`.** `pnpm -C apps/web test` runs `tests/web/*.test.ts`, which frontend waves 1–5 already edited; this report is under `hackathon/briefs/`, as dispatched. Nothing else outside `apps/web/` changed.
5. **STATE.md:** this closes the frontend item "Deploy palette text promises per-token serving — align with spike 1's answer".

## 6. Noticed, not changed
- `app/workflows/new/page.tsx`: the example prompt "Distill Qwen3-4B into a 1.7B model for edge deployment, quantize to GGUF" asks for distill-sft, which the planner behind from-prompt never plans.
- `vllm-serve` and `unsloth-train` have no form, so a node dropped from the palette cannot set `lora_adapter` or `merge` (a node from an agent plan shows every input it carries). Forms for them would finish the golden path by hand.
- After Retry node on /agent, a report card that is ready (or gone) is not reset until the page reloads; this was so for "ready" before my change.
- pnpm 11's `install` exits 1 with ERR_PNPM_IGNORED_BUILDS (sharp): the Makefile already notes it; node_modules were installed fine.
