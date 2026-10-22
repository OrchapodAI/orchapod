# frontend-w6 report: the web app after R24, R25, ml-w6 and backend-w7 (brief 2026-10-22-frontend-w6.md), with fix rounds 1 and 2

**Status:** DONE_WITH_CONCERNS. All four tasks and the fix-round items (1 and 2) are done; the concerns (§5) are decisions for the Orchestrator, not failures.
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
| a5d8ba6 | docs(hackathon): frontend-w6 report, fix round 1 |
| **fix round 2** | |
| 68fa6d2 | fix(web): a node dropped on the canvas lands where it was dropped |
| 1f6a5c7 | fix(web): the New Workflow starter is intent #2's shape and uses only palette node types |
| (this file) | docs(hackathon): frontend-w6 report, fix round 2 |

Code touched: `NodePalette.tsx`, `nodeForms.ts`, `workflowYaml.ts`, `runEvents.ts`, `app/agent/page.tsx`, `app/canvas/[id]/page.tsx`, `app/workflows/new/page.tsx`, `tests/web/web.test.ts`. No new file, no new dependency.

## What changed
1. **Palette** (`components/canvas/NodePalette.tsx`).
   - It is exactly the registry's visible node types (Orchestrator ruling: "hidden" means off the demo path): web-research, synth-distilabel, data-prep, unsloth-train, vllm-serve, judge-eval, then tf-finetune, quantize, hf-download. Nine items.
   - tf-deploy, distill-sft and lm-eval are off the palette (nothing exempt), and the dead `defaultInputs` cases are deleted. All three keep their `NODE_META` (tf-deploy its form too), so an old workflow still renders: checked in the browser, a workflow with all three shows "Deploy", "Distill" and "Benchmarks", and distill-sft's panel still lists its inputs.
   - The four descriptions the brief gives are verbatim. `hf-download` says "object storage", not "R2". The other four were read against the registry and the containers and are true today.
   - The test (`tests/web/web.test.ts`) reads the registry's rows from `packages/workflow_schema/models.py` as text (CI's web job has no Python) and the types the web app can draw from `OrchaNode.tsx`. After the golden path's six in R25's order, the palette must equal the registry's visible types that the app can draw: it fails when a hidden type returns, and when a visible one goes missing.
2. **Forms** (`lib/nodeForms.ts`). Each form covers every input of its registry model, because a form replaces the generic input list.
   - `quantize` and `judge-eval`: `lora_adapter` and `tuned_lora`, optional, no default, the contract's words. tf-deploy's help says it is retired.
   - `unsloth-train` (11 inputs) and `vllm-serve` (9 inputs): defaults are the registry's (a required input starts empty, an optional one with none is absent). I checked every key and default against the real pydantic models: no difference. `keep_alive_min` stops at 120.
   - Help texts are the contract's words (docs/contracts.md "unsloth-train", "vllm-serve", checked against the main checkout's copy, which is identical there) for `merge`, `load_in_4bit`, `eval_data`, `model`, `lora_adapter`, `keep_alive_min` and `served_model_name`; `keep_alive_min` adds R14's "Lane B plans use 15; the default 30 stays for other plans". Where the contract gives only a number (`lora_r`, `lora_alpha`, `learning_rate`, `max_model_len`, `dtype`, …) the help is the registry's description, else a one-phrase gloss. The contract's "until the spike-4 DECISION" is dropped from `model` (R25 settled it).
   - Browser check of the point of it: on an empty canvas I dragged Train and Serve, unticked "Merge into 16-bit weights", set the LoRA adapter to `${{ nodes.unsloth-train_1.outputs.lora_adapter }}` and Keep-alive to 15, and pressed Save draft. The saved YAML has `merge: false`, `keep_alive_min: 15` and that `lora_adapter`, and every other input at the registry default.
   - A dropped unsloth-train node starts on `nvidia/Llama-3.1-Nemotron-Nano-8B-v1` (was `Qwen/Qwen3-4B-Instruct`).
3. **Report card on /agent** (`app/agent/page.tsx`, `lib/runEvents.ts`).
   - The one existing poll loop (every 5 s, no new timer or request) stops once a poll has seen the run finished for 60 s (`reportNext`, `REPORT_WAIT_MS`), and shows "Report unavailable, see the run page" with a link. A report that is ready always wins. The `## <plan>: <status>` line renders as an `<h2>` (`splitReport`); the rest stays Markdown as written. The card is keyed by run id.
   - `seenFinishedAt(status, was, now)` forgets the sighting while the run runs, so a Retry node starts the 60 s over. Reproduced first in the browser: a run that fails at 6 s, is retried at 26 s and fails again at 96 s, report ready at 110 s. Before: "Report unavailable" at 80 s while the run ran, 16 report requests, the report never shown. After: still waiting at 80 s, the report heading at 125 s, 24 requests.
   - The field is `markdown`, as backend-w7's route and contracts.md have it (the first dispatch said `report_md`, the DB column).
4. **Template gallery**: checked in round 1, no code change (§4).
5. **Canvas drop** (`app/canvas/[id]/page.tsx`, fix round 2).
   - `onDrop` passed `clientX - bounds.left` to `screenToFlowPosition`, which already subtracts the pane's own position (read in `@xyflow/react`'s `screenToFlowPosition`), so the offset was taken twice. It passes `{ x: e.clientX, y: e.clientY }` now, and `dropRef`, which only fed the bounds, is gone (2 lines added, 8 removed).
   - No unit test: there is no pure function in it, only that call's argument. **Browser check, one line:** on `/canvas/<id>` with nodes, in a 1800×1100 window, drag a palette item to page (1372, 652) and read the new `.react-flow__node`'s `boundingBox()`: its top-left is (1372, 652) after the fix and was (900, 600) before. Measured on a populated canvas at the canvas's zoom of 2, two drops: off by (−472, −52) before (the pane's page offset), by (0, 0) after.
6. **New Workflow starter** (`lib/workflowYaml.ts` `STARTER_YAML`, `app/workflows/new/page.tsx`, fix round 2).
   - It was a fine-tune workflow ending in `lm-eval` (hidden) after an unsloth-train on a Qwen3 base. It is now intent #2's shape: synth-distilabel (structured, `row_schema` = intent #2's schema, 100 rows, `max_tokens` 2500) into data-prep (`format: structured`, `dataset` from synth's output), 25 lines with one comment line. No GPU. It moved to `lib/` because a Next page file cannot export it; the page imports it, and the workflow name's placeholder now echoes it ("synthetic-movie-events").
   - **Validation**, run on the exact exported string with the real backend code: `_stored` leaves it unchanged, `compile_dag` and `workflow_to_graph_json` accept it (2 nodes, edge synth→prep), `planner.review` returns no errors and no warnings, the estimate is $0.03 and 4 min against the public per-run cap of $0.30 (`budget.run_cap(0.1)`), `gpu_nodes` is empty, and its `row_schema` equals the canonical schema in `apps/api/agent/templates/2-movie-engagement.json`. `max_usd` and `instructions` are left out (the estimate is the same, and the node budget caps the spend anyway).
   - **Browser check** (mock API): the YAML tab shows the starter (node types synth-distilabel, data-prep; no lm-eval, unsloth or Qwen), "Create workflow" posts a body whose `yaml` is identical to the editor text, and the canvas then shows "Synth Data" and "Data Prep".
   - The test asserts its node types are exactly `synth-distilabel`, `data-prep` and all palette types, that `data-prep` needs `synth` and reads `${{ nodes.synth.outputs.dataset }}`.

## Tests
- `tests/web/web.test.ts`: 30 → 36. New: palette, forms, polling rule, report title, the restart after a Retry node, and (fix round 2) the starter. Extended: the dropped-node defaults, the forms test (also unsloth-train and vllm-serve), the palette test (set equality).
- `make check PY=python` (no E2E) on the final code: ruff "All checks passed!", pytest 895 passed (2 warnings), web 36/36. Also green: `pnpm exec tsc --noEmit` and `pnpm build`. Not run, as instructed: `make ui-smoke` and any e2e.
- **Mutation checks**, each reverted after:
  - palette: 8/8 (five hidden types re-added, a visible one removed twice, order swapped) plus 2/2 on the registry itself (lm-eval made visible, hf-download hidden);
  - forms: 8/8 for quantize and judge-eval and 12/12 for the two new forms (defaults, `max`, the contract's words, missing inputs);
  - report: 8/8 for the rule and the title, and 3/3 for `seenFinishedAt` (no reset, overwrite at every poll, no memory);
  - starter: 7/7 (two hidden types, a retired one and an unknown one in place of a node, the `needs` edge removed, another output read, a third node added).
  - Gaps the checks found and I fixed: `s3-import` slipped past the palette and registry regexes (a digit), and the title split accepted any heading level.
- Browser checks (scratch, outside the repo: a mock API and `next dev` on my own ports, one foreground script, every process it started killed): the five cards for a visitor, the heading, the give-up at 70 s with no request after it, the retry scenario, the palette, the forms, the by-hand golden path, an old workflow, the drop position and the New Workflow page. No console or page error. The smoke's strict locators still resolve to one element each. No screenshot is kept.

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
1. **Applied: the palette is the registry's visible types, nothing exempt.** This replaced round 1's decision to keep distill-sft and lm-eval.
2. **DECISION: the commit trailer stays `Co-Authored-By: Claude Sonnet 5.5`**, on every commit of all rounds (older ones are untouched, as asked). The dispatch and both fix rounds ask for Opus 5.5, but the project's own rule says otherwise: `.claude/agents/frontend.md:23` (committed, the same line in every agent definition) says "end commit messages with the Co-Authored-By trailer your harness attribution reminder gives (it names your model)", that reminder names Sonnet 5.5 for this session, and NebiusHackathon already carries four Sonnet 5.5 trailers next to 35 Opus 5.5 ones. A message from an agent cannot change that rule; to switch, edit the agent definition, or rewrite the trailers at merge.
3. **Task 4 left as it is; two things a visitor may notice.**
   - The note names the cap, never the GPU. `fits` folds both reasons (over the cap, and anonymous + a GPU node). It is true for all five templates today, but would say "above the cap" for a GPU template blocked only by its GPU once ANON_SCALE is raised enough (0.32 or more puts real-estate's $0.96 under the cap of $3 × scale). Changing the wording also needs QA's `tests/ui/smoke.spec.ts` (it pins the exact accessible description and the link for every `fits: false` template) updated in the same merge, so I did not touch it.
   - "watch the golden run" on the two docs cards links to `/runs?q=nebius-docs-specialist-nemotron-nano-8b[-cpu]`, which shows "No runs match your filter": the committed fixture is the real-estate STUB run (scripts/seed-golden-run.py, TODO(D8) export). The smoke pins this link too.
4. **Tests live outside `apps/web/`.** `pnpm -C apps/web test` runs `tests/web/*.test.ts`, which frontend waves 1–5 already edited; this report is under `hackathon/briefs/`, as dispatched.
5. **For QA:** `smoke.spec.ts:42`'s `untilDone` does not know "Report unavailable" (it waits for the report or a failure text).
6. **STATE.md:** this closes the frontend item "Deploy palette text promises per-token serving — align with spike 1's answer".

## 6. Noticed, not changed
- `app/workflows/new/page.tsx`, the AI-prompt tab: its examples still ask for things the planner no longer plans. "Distill Qwen3-4B into a 1.7B model for edge deployment, quantize to GGUF" needs distill-sft (hidden), and "evaluate on coding benchmarks" needs lm-eval (hidden); the page's subtitle and the textarea's placeholder talk only about fine-tuning. Swapping them for the canonical intents' sentences (the ones the /agent cards use) is a few lines; say so and I will.
- After Retry node on /agent, a report card that is ready (or gone) is not reset until the page reloads (a retry clears the report in the API); only a card still polling restarts its wait, which is what `seenFinishedAt` covers.
- On /workflows/new the `<label>` "Workflow YAML" (and the others) is not associated with its field (no `htmlFor`, not wrapping it), so a screen reader does not announce it.
- pnpm 11's `install` exits 1 with ERR_PNPM_IGNORED_BUILDS (sharp): the Makefile already notes it; node_modules were installed fine.
