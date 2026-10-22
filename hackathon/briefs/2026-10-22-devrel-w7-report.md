# devrel-w7 report (2026-10-22)

**Status:** DONE. The README, the Devpost text, NODE_CONTRACT.md and feedback.md now state the two live runs and the golden path on stubs. The live golden run stays TODO(D8).

**Branch:** `hack/devrel-w7`, base 3b7bf07 (`git merge-base --is-ancestor 3b7bf07 HEAD` passes). Not pushed. CHANGELOG.md is untouched, as asked.

**Spend:** $0. I used no key, called no model and started no server. This time Bash ran only git and the tests.

## Commits
| SHA | What |
| --- | --- |
| 826f707 | docs: intents #2 and #3 ran live; the golden path passes on stubs and in the UI smoke (README, devpost, NODE_CONTRACT, tests/docs/test_readme.py) |
| b89aa14 | docs(feedback): Super's live plans differ from our templates (a planner-robustness lesson) |

## Proof
- **TDD.**
  - At the base, `pytest tests/docs -q` gave 27 passed.
  - I first added three STALE needles to tests/docs/test_readme.py: "No pipeline has run live", "no live run yet" and "drives the real-estate template card". The suite then gave 2 failed, 25 passed: the README and the Devpost still carried them.
  - After the edits it gave 27 passed.
  - STALE also guards feedback.md and the video script.
- **The make-target guard.** Lines that mention `make agent-e2e` no longer need TODO(D8), because it ran live. Only `make e2e` stays pinned, since its real mode is unbuilt.
- **`make check`** (no E2E) at b89aa14: exit 0.
  - ruff gave `All checks passed!`.
  - pytest gave `1009 passed, 2 warnings`.
  - The web tests gave `tests 36, pass 36, fail 0`.
  - The output ended with `SKIP stub e2e`.
- **Trial merge.** `git merge-tree --write-tree NebiusHackathon HEAD` exits 0 against c665c06. Nothing upstream touched my files since the base.
- **Grep.** No owned doc still says "no live run", "is next", "3 of 3", "all three intents" or "real-estate template card". The two "never run" hits that remain are unrelated: HOSTING.md:136 (the VM) and video-script:25 (Job and Endpoint).

## Facts written in
Each fact was checked against LOG.md:529–575 and the qa-w8 report.
1. **Live run 1, intent #2.**
   - **Where.** README:10, :31 and :159; a new Results bullet; devpost:24 and :42.
   - **The run.** Super planned `movie-interactions-synthetic` live: synth → data-prep, estimated at $0.30 and 9 min. Run 84e57f84 succeeded in 446 s with 928 rows that have exactly the schema's fields. Super wrote the report.
   - **Cost.** $0.1007 in all: the run $0.0966, the planner and reporter $0.0041.
2. **Live runs 2 and 3, intent #3.**
   - **Where.** A Results bullet; devpost:51.
   - **First attempt.** Run cf49d0f1 failed in 73 s for $0.0034, because the live plan omitted gsm8k's config. The fix, 782be76, is in my base: data-prep picks `main`, else the first config, and logs a warning.
   - **Pass.** Run 59786797 took 255 s and $0.0175. It downloaded 3.1 GB and quantized to q4_k_m (0.99 GB) in 75 s on CPU.
   - **Ultra's verdict.** On 5 questions: 1 win, 4 ties, 0 losses, consistency 1.0. Exact match was 0.8 against 0.6, a gap of one question. Both docs say plainly that five questions is a smoke-scale sample.
   - **The model.** I wrote "a 3.1 GB maths model" and did not name it, because the LOG does not.
3. **Golden path on stubs.**
   - **`make check E2E=1`.** It gave `4 PASS`, with template 4's full plan as run 60719547: 26 s, $0, against a $2.66 estimate.
   - **`make ui-smoke`.** It passed 5/5. Its golden test clicks template 4's card, which runs the reduced plan, through the run, the eval view and the compare playground. This is qa-w8's record at 00c0fb6 (LOG 07:27Z).
   - **Where.** README:121, :143, :149 (unsloth-train's `--target stub` stage), :158 and :165; devpost:24; NODE_CONTRACT.md:89.
   - **Oct 21 history.** The "What changed" bullets for Oct 21 (README:203, devpost:77) now say "a browser smoke test that runs a template card on stubs". On Oct 21 that card was real estate, so writing template 4 there would have been false. The Oct 22 changes are left for the freeze update, which their TODO(D8) already covers.
4. **Live golden run.** It is still TODO(D8) in README:10, :31 and :193 and in devpost:24. It needs a Tavily key, GPU quota and the hosted API. README:193 adds the two measured runs' time and cost.
5. **Evaluation claim.** README:39 and devpost:31 now say Ultra has judged live only at smoke scale (5 questions of intent #3). The TODO(D8) for the golden run's win rate stays.
6. **feedback.md.**
   - **New item** after the model-ids finding: Super's live plans differ from our templates, for example by omitting a dataset config. We hardened data-prep and the knowledge text, and we call it an honest planner-robustness lesson. Sourced to LOG 07:30Z and 07:34Z.
   - **Intro.** It now names the first live Agent runs.

## Concerns
- **The ui-smoke record is from 00c0fb6.** qa-w8's follow-up round added golden-test assertions (a814563) after that run, and no run has exercised them yet (qa-w8's open risk). If the integration you are re-running fails there, README:165 and devpost:24 still describe the 00c0fb6 run correctly, but the newest code is unproven.
- **Template 5 has no e2e or smoke yet** (qa-w8's concern). The docs do not claim one.
