# frontend-w6 report: the web app after R24, R25, ml-w6 and backend-w7 (brief 2026-10-22-frontend-w6.md), with fix round 1

**Status:** DONE_WITH_CONCERNS. All four tasks and the three fix-round items are done; the concerns (§5) are decisions for the Orchestrator, not failures.
**Branch:** `hack/frontend-w6`, worktree `.claude/worktrees/frontend-w6`. Base 97b749c (`git merge-base --is-ancestor 97b749c HEAD` passes). Not pushed.
**Spend:** $0. No key, no model call, no container.

## Commits
| SHA | What |
| --- | --- |
| 5477e1e | feat(web): palette lists the golden path first and drops tf-deploy; every description is true today |
| 2f7e210 | feat(web): quantize takes lora_adapter and judge-eval tuned_lora; tf-deploy's help says it is retired |
| 8eb7bbd | feat(web): the /agent report card gives up 60 s after the run ended, and its title renders as a heading |
| bccf186 | docs(hackathon): frontend-w6 report |
| **fix round 1** | |
| ebee7aa | fix(web): a Retry node starts the report card's 60 s wait over |
| 11464dd | fix(web): the palette is the registry's visible node types, nothing exempt (distill-sft and lm-eval leave) |
| b1011a9 | feat(web): unsloth-train and vllm-serve get forms, so the golden path can be built by hand |
| 282bf06 | style(web): the palette's header comment states the rule, not a list of hidden types |
| (this file) | docs(hackathon): frontend-w6 report, fix round 1 |

Diff of the code commits: `NodePalette.tsx`, `nodeForms.ts`, `runEvents.ts`, `app/agent/page.tsx`, `tests/web/web.test.ts`. No new file, no new dependency.

## What changed
1. **Palette** (`components/canvas/NodePalette.tsx`).
   - It is now exactly the registry's visible node types (Orchestrator ruling: "hidden" means off the demo path): web-research, synth-distilabel, data-prep, unsloth-train, vllm-serve, judge-eval, then tf-finetune, quantize, hf-download. Nine items.
   - distill-sft and lm-eval are off the palette (nothing exempt), and their dead `defaultInputs` cases are deleted. tf-deploy went in round 1. All three keep their `NODE_META` (tf-deploy its form too), so an old workflow still renders: checked in the browser, a workflow with all three shows "Deploy", "Distill" and "Benchmarks", and distill-sft's panel still lists its inputs.
   - The four descriptions the brief gives are verbatim. `hf-download` says "object storage", not "R2". The other four were read against the registry and the containers and are true today.
   - The test (`tests/web/web.test.ts`) reads the registry's rows from `packages/workflow_schema/models.py` as text (CI's web job has no Python) and the types the web app can draw from `OrchaNode.tsx`. After the golden path's six in R25's order, the palette must equal the registry's visible types that the app can draw: it fails when a hidden type returns, and when a visible one goes missing.
2. **Forms** (`lib/nodeForms.ts`). Each form covers every input of its registry model, because a form replaces the generic input list.
   - `quantize` and `judge-eval` (round 1): `lora_adapter` and `tuned_lora`, optional, no default, the contract's words. tf-deploy's help says it is retired.
   - `unsloth-train` (11 inputs) and `vllm-serve` (9 inputs) (fix round): defaults are the registry's (a required input starts empty, an optional one with none is absent). I checked every key and default against the real pydantic models: no difference. `keep_alive_min` stops at 120.
   - Help texts are the contract's words (docs/contracts.md "unsloth-train", "vllm-serve", checked against the main checkout's copy, which is identical there) for `merge`, `load_in_4bit`, `eval_data`, `model`, `lora_adapter`, `keep_alive_min` and `served_model_name`; `keep_alive_min` adds R14's "Lane B plans use 15; the default 30 stays for other plans". Where the contract gives only a number (`lora_r`, `lora_alpha`, `learning_rate`, `max_model_len`, `dtype`, …) the help is the registry's description, else a one-phrase gloss. The contract's "until the spike-4 DECISION" is dropped from `model` (R25 settled it).
   - Browser check of the point of it: on an empty canvas I dragged Train and Serve, unticked "Merge into 16-bit weights", set the LoRA adapter to `${{ nodes.unsloth-train_1.outputs.lora_adapter }}` and Keep-alive to 15, and pressed Save draft. The saved YAML has `merge: false`, `keep_alive_min: 15` and that `lora_adapter`, and every other input at the registry default.
   - A dropped unsloth-train node starts on `nvidia/Llama-3.1-Nemotron-Nano-8B-v1` (was `Qwen/Qwen3-4B-Instruct`).
3. **Report card on /agent** (`app/agent/page.tsx`, `lib/runEvents.ts`).
   - The one existing poll loop (every 5 s, no new timer or request) stops once a poll has seen the run finished for 60 s (`reportNext`, `REPORT_WAIT_MS`), and shows "Report unavailable, see the run page" with a link. A report that is ready always wins. The `## <plan>: <status>` line renders as an `<h2>` (`splitReport`); the rest stays Markdown as written. The card is keyed by run id.
   - **Fix round:** `seenFinishedAt(status, was, now)` forgets the sighting while the run runs, so a Retry node starts the 60 s over. Reproduced first in the browser: a run that fails at 6 s, is retried at 26 s and fails again at 96 s, report ready at 110 s. Before: "Report unavailable" at 80 s while the run ran, 16 report requests, the report never shown. After: still waiting at 80 s, the report heading at 125 s, 24 requests.
   - The field is `markdown`, as backend-w7's route and contracts.md have it (the first dispatch said `report_md`, the DB column).
4. **Template gallery**: checked in round 1, no code change (§4).

## Tests
- `tests/web/web.test.ts`: 30 → 35. New: palette, forms, polling rule, report title, and (fix round) the restart after a Retry node. Extended: the dropped-node defaults, the forms test (now also unsloth-train and vllm-serve), the palette test (set equality).
- `make check PY=python` (no E2E) on the final code: ruff "All checks passed!", pytest 895 passed (2 warnings), web 35/35. Also green: `pnpm exec tsc --noEmit` and `pnpm build`. Not run, as instructed: `make ui-smoke` and any e2e.
- **Mutation checks**, each reverted after:
  - palette: 8/8 (five hidden types re-added, a visible one removed twice, order swapped) plus 2/2 on the registry itself (lm-eval made visible, hf-download hidden);
  - forms: 8/8 in round 1 and 12/12 for the two new forms (defaults, `max`, the contract's words, missing inputs);
  - report: 8/8 for the rule and the title, and 3/3 for `seenFinishedAt` (no reset, overwrite at every poll, no memory).
  - Gaps the checks found and I fixed: `s3-import` slipped past the palette and registry regexes (a digit), and the title split accepted any heading level.
- Browser checks (scratch, outside the repo: a mock API and `next dev` on my own ports, one foreground script, every process it started killed): the five cards for a visitor, the heading, the give-up at 70 s with no request after it, the retry scenario above, the palette, the forms, the by-hand golden path and an old workflow. No console or page error. The smoke's strict locators still resolve to one element each. The screenshots (round 1 and this round) were deleted at the Orchestrator's request.

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
1. **Applied: the palette is the registry's visible types, nothing exempt.** This replaces round 1's decision to keep distill-sft and lm-eval.
2. **DECISION: the commit trailer is `Co-Authored-By: Claude Sonnet 5.5`**, on every commit of both rounds. The dispatch and the fix round ask for Opus 5.5; my instructions say to use the trailer of the harness's attribution reminder, which names this session's model (Sonnet 5.5), and a trailer naming another model would misattribute the work. Rewrite the trailers if you want Opus.
3. **Task 4 left as it is; two things a visitor may notice.**
   - The note names the cap, never the GPU. `fits` folds both reasons (over the cap, and anonymous + a GPU node). It is true for all five templates today, but would say "above the cap" for a GPU template blocked only by its GPU once ANON_SCALE is raised enough (0.32 or more puts real-estate's $0.96 under the cap of $3 × scale). Changing the wording also needs QA's `tests/ui/smoke.spec.ts` (it pins the exact accessible description and the link for every `fits: false` template) updated in the same merge, so I did not touch it.
   - "watch the golden run" on the two docs cards links to `/runs?q=nebius-docs-specialist-nemotron-nano-8b[-cpu]`, which shows "No runs match your filter": the committed fixture is the real-estate STUB run (scripts/seed-golden-run.py, TODO(D8) export). The smoke pins this link too.
4. **Tests live outside `apps/web/`.** `pnpm -C apps/web test` runs `tests/web/*.test.ts`, which frontend waves 1–5 already edited; this report is under `hackathon/briefs/`, as dispatched.
5. **Existing bug, found while building the golden path by hand, not fixed (outside the fix list):** a node dropped from the palette lands offset by the canvas's page position. `app/canvas/[id]/page.tsx` `onDrop` passes `clientX - bounds.left` to `rfInstance.screenToFlowPosition`, which React Flow 12 already makes relative to the pane, so it subtracts twice. Measured: dropped at page (772, 372), the node's box was at (300, 320), exactly the pane's offset (472, 52) away, so a node dropped within 472 px of the canvas's left edge starts partly clipped by it, and I also saw one land on top of another node. The fix is one line: `screenToFlowPosition({ x: e.clientX, y: e.clientY })` and drop the `bounds` lines. Say so and I will do it with a browser check.
6. **For QA:** `smoke.spec.ts:42`'s `untilDone` does not know "Report unavailable" (it waits for the report or a failure text).
7. **STATE.md:** this closes the frontend item "Deploy palette text promises per-token serving — align with spike 1's answer".

## 6. Noticed, not changed
- `app/workflows/new/page.tsx`: its starter YAML ends in an `lm-eval` node (hidden in the registry) after an `unsloth-train` on `Qwen/Qwen3-4B-Instruct`, and its example prompt "Distill Qwen3-4B into a 1.7B model for edge deployment, quantize to GGUF" asks for distill-sft, which the planner behind from-prompt never plans.
- After Retry node on /agent, a report card that is ready (or gone) is not reset until the page reloads (a retry clears the report in the API); only a card still polling restarts its wait, which is what the fix round covers.
- pnpm 11's `install` exits 1 with ERR_PNPM_IGNORED_BUILDS (sharp): the Makefile already notes it; node_modules were installed fine.
