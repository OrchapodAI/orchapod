# devrel-w6 report (2026-10-22)

**Status:** DONE_WITH_CONCERNS. The README, Devpost text, feedback doc, video script and WORKFLOW_SPEC now carry the brief's four rulings and the coordinator's `make agent-e2e` fact. The concerns are listed below.

**Branch:** `hack/devrel-w6` in `.claude/worktrees/devrel-w6`, base 97b749c (`git merge-base --is-ancestor 97b749c HEAD` passes). Not pushed.

**Spend:** $0. I used no key, called no model, built no image and started no server.

## Commits (oldest first)
| SHA | What |
| --- | --- |
| 7e49651 | docs: Nemotron 3 Super writes the run report, not Lightning (README, devpost, tests/docs/test_submission_docs.py) |
| 45de6a6 | docs(readme): R25 NVIDIA end to end, R24 tf-deploy retired, five templates, live status |
| 0e25403 | docs(devpost): the same facts |
| 6f47772 | docs: the golden run is Lane B (R25); tf-deploy is retired (R24) (video-script, WORKFLOW_SPEC) |
| dcda04a | docs(feedback): spikes 1 and 2 were live; Super took over the report |
| 83cc169 | docs(readme): `make agent-e2e` runs one intent for real (qa-w7); `make e2e` is still stub-only (README, test_readme.py comment) |

Before this report the diff was 7 files, +45 −40, all in docs and tests/docs.

## Proof
- **TDD.**
  - At the base, `pytest tests/docs -q` gave 27 passed.
  - I changed the reporter guard first, and it failed (1 failed, 26 passed) because the README still said Lightning.
  - After the README and Devpost edits it gave 27 passed, and so did every later commit.
  - The guard now requires that, in the README and the Devpost, the line naming the deterministic template says "Nemotron 3 Super writes" and not "Lightning writes". The README's Reporter row must give Super's id.
- **`make check`** (no E2E) at 83cc169: exit 0.
  - ruff gave `All checks passed!`.
  - pytest gave `895 passed, 2 warnings`.
  - The web tests gave `tests 30, pass 30, fail 0`.
  - The output ended with `SKIP stub e2e`.
  - dcda04a gave the same result.
- **The flake.** Two other runs, at dcda04a and 83cc169, failed one test only: `tests/api/test_budget.py::test_concurrent_runs_never_grant_more_than_the_day_cap`.
  - It is base 97b749c's known flake: the spike 1 report puts it at about 1 run in 3.
  - backend-w7 fixed it in NebiusHackathon 98cd829, which my base does not include.
  - I merged this branch with 98cd829 in a detached worktree and removed the worktree afterwards. That merge gave ruff clean and `900 passed`.
- **Trial merges.** `git merge-tree --write-tree` exited 0 against NebiusHackathon 98cd829 (backend-w7 merged), against hack/qa-w7, and against both together.
  - tests/docs passed 27 on this branch merged with 98cd829 and qa-w7.
  - hack/backend-w7 on its own conflicts with the base in docs/contracts.md. The conflict exists without my branch too, and 98cd829 has resolved it.
- **Stale-claim grep** over the five docs I own:
  - None of these strings remain: "Lightning writes", "per-token LoRA model", "tf-deploy model", a "fourth" card or template, "not wired", "is to delete", "candidate topics", "Llama 8B tuned", "$2.65".
  - Every remaining mention of tf-deploy or per-token deploy says it is retired: README:46, :61 and :89, and WORKFLOW_SPEC:63–64.

## Facts written in
1. **Reports** (contracts "Agent API", backend-w7):
   - **Where.** README:75 and :83, devpost:42.
   - **What.** Super writes the report once, in the background, when the run ends. Its title is `## <plan>: <status>`. It is one call of at most 30 s, with thinking off. A deterministic template is the fallback.
   - **Spike 2.** Lightning took 16–110 s per report and Super about 2 s.
   - **Lightning.** It keeps only the opt-in quality filter (README:53 and :82, devpost:42).
   - **feedback.md.** Line 20 now says Super took over the report because of that latency, sourced to LOG 2026-10-22T03:40Z. Line 42 no longer lists Lightning as the reporter.
2. **NVIDIA end to end (R25):**
   - **Where.** README:37 ("Why"), :47 (Lane B), :95–96 (Jobs, Endpoints) and :193 (costs); devpost:38 (a new paragraph) and :44–45.
   - **The models.** Super plans, teaches and reports. Lightning is the optional filter. Ultra judges.
   - **The student.** `nvidia/Llama-3.1-Nemotron-Nano-8B-v1`. Unsloth trains it (16-bit LoRA) on an H100 Job. vLLM serves base and adapter on one L40S endpoint (keep-alive 15 min). Ultra judges it pairwise against the base.
   - **Costs.** The full-scale estimate is $2.66. The R14 worst case is $2.92, under the $3 cap: 25 min of H100, up to 15 + 15 min of L40S, and about $0.27 of calls. `merge: false` skips the 16 GB merged copy.
   - **Template 5.** Estimated at $2.15: GGUF q4_k_m plus a GGUF LoRA on llama-server, with no endpoint.
   - **Scope.** The docs say "That holds for the golden path only". Real estate is Lane A (Llama 3.2 3B on Token Factory). The maths template quantizes Qwen2.5-Math-1.5B-Instruct, which is not NVIDIA's either, so writing "one template differs" would have been false.
3. **tf-deploy retired (R24):**
   - **README.** Line 46 (Lane A) and line 61.
   - **devpost:43 (Lane A).** Spike 1's live 50-row fine-tune took 6 min 45 s. Per-token deploy answers 410, so vllm-serve serves the adapter. The fine-tune rate is unpublished, so the client will not start a fine-tune.
   - **video-script.** Lines 14, 40 and 49 no longer mention a tf-deploy model.
   - **WORKFLOW_SPEC.** Lines 63–64 mark tf-deploy retired. Line 67 drops tf-deploy from judge-eval's ref sources.
   - **feedback.md.** It already carried the 410 (:7), the unpublished rate (:11) and Lightning's latency (:20). Its intro (:3) no longer says that no live call has run.
4. **Live status:**
   - **README:10, the status of 2026-10-22.** STUB is green. No pipeline has run live. Two spikes made the first live Token Factory calls. Intent #2 is next. The golden run needs a Tavily key, GPU quota and the hosted API.
   - **README:31 and :165.** Both STUB checks passed again on 24e234a: e2e_agent 3/3, and ui-smoke 5/5 including the Save a copy case (LOG 2026-10-21T17:53Z).
   - **devpost:24 and :44.** The same status.
   - TODO(D8) marks where the live numbers go.
5. **The coordinator's addition (qa-w7):**
   - **README:159.** `make agent-e2e INTENT=2 MAX_COST=0.5` runs one canonical intent through the Agent API with real Token Factory calls.
     - It needs NEBIUS_API_KEY and is capped by MAX_COST, at most $3.
     - It refuses plans that rent a GPU until G2, and plans that need an unset key.
     - The orchestrator runs it. TODO(D8) marks its run id and cost.
   - **Checked against hack/qa-w7.** The Makefile matches, and so does scripts/e2e_agent.py:18–24 and 77–87.
   - **`make e2e` stays stub-only.** qa-w7's e2e_demo.py:375 still errors on `--max-cost`.
   - **The test.** I updated test_readme.py's comment to match and left the test itself unchanged.
6. **Five templates.** README:21 now reads "Two more cards…": the fourth serves from a GPU endpoint, and the fifth judges on CPU. video-script:14 now names "Nemotron Nano 8B tuned as a Nebius docs specialist".
7. **WORKFLOW_SPEC:43.** `merged_model` is written only when `merge` is true, which is the default.

## Judgment calls beyond the brief's list (owned files only)
- **Endpoint deletion at expiry.** It is wired (backend-w5: apps/api/routes/internal.py:417–443).
  - So README:96, devpost:45 and video-script:25 and :49 now say the control plane deletes the endpoint. Before, they said the delete was "not wired" yet.
  - TODO(D8) marks the check on a live endpoint.
- **Shot 6.** The executor deletes a Nebius Job when it ends (run_workflow.py:247 → nebius.py:278–282), so shot 6 captures the Job while it trains.
- **Shots 5 and 6.** Both fall inside the 15-minute keep-alive, and judge-eval uses part of it.
- **Without an endpoint.** If the endpoint refuses the adapter, the CPU variant runs and there is no playground. The script then cuts shot 5 and gives its time to shot 4.
- **WORKFLOW_SPEC.** It gained the two LoRA inputs template 5 uses: quantize's `lora_adapter` → `gguf_lora`, and judge-eval's `tuned_lora`. I checked both in models.py and judge-eval/run.py.
- **The topic TODO.** I kept "TODO(D8): Hari confirms the golden run's topic by D6" (README:21, video-script:14), because STATE's Human actions still lists the topic as open.

## Concerns and what is not done
- **README:159 depends on qa-w7.** It is true once qa-w7 merges. If this branch merges first, the line describes a Makefile that NebiusHackathon does not have yet.
- **Outside my paths:**
  - apps/api/agent/templates/1-real-estate-compliance.json, in its `rationale`, still says "Token Factory's per-token LoRA deploy is unverified for 3B (spike 1)". That file belongs to backend or ml.
  - apps/api/agent/planner.py:158–160 still has the dead tf-deploy warning. This is ml-w6 review item M1, already assigned to integration.
  - The board's frontend Deploy palette item is open, and I did not check it.
- **Left as is:**
  - WORKFLOW_SPEC still says "The 7 node types", which contracts calls stale. The brief does not cover it.
  - The "What changed" lists in the README and the Devpost stop at Oct 21. Their TODO(D8) says to update them at the freeze, as before.
- **Rule note.** Early on I used Bash for read-only inspection beyond git and the tests: `python -c` to print the template JSON and the NODE_REGISTRY rows, and `tail`/`wc` on hackathon/LOG.md. Nothing was written, nothing touched the network, and it cost $0.

## For the Orchestrator to record
- DECISION 2026-10-22 (devrel-w6): every submission doc scopes the "NVIDIA end to end" claim to the golden path (templates 4 and 5). Real estate (Lane A, Llama 3.2 3B) and maths (Qwen2.5-Math) are named as outside it.
- DECISION 2026-10-22 (devrel-w6): tests/docs pins Super as the reporter. The deterministic-template line must say "Nemotron 3 Super writes", and the README's Reporter row must be Super's id.
