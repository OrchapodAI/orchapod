# Report: devrel-w13 (2026-10-27, G3 freeze docs pass)

**Status:** done. Spent $0, with no paid or model calls.

This report is in the worktree, at /Users/hari/src/orchapod-hack/.claude/worktrees/agent-ab9e5238cc9922bbc/hackathon/briefs/2026-10-27-devrel-w13-report.md. It is uncommitted, because the worktree isolation refused the write to the shared checkout's hackathon/briefs. Copy it there.

## Branch and commits
- Branch: `worktree-agent-ab9e5238cc9922bbc`. The worktree started at 387a2cc, which does not contain 4071b59, so the base check failed. I ran `git reset --hard 4071b59` (the worktree was clean), and the check then passed.
- 1526faa docs: README and Devpost what-changed lists caught up with CHANGELOG (Oct 22-27)
- a13ec91 docs(feedback): what worked well and one question per finding; ready to paste
- Not pushed.

```
$ git diff --stat 4071b59 HEAD
 README.md                          |  7 +++--
 docs/devpost.md                    |  7 +++--
 docs/feedback.md                   | 59 +++++++++++++++++++++++++++++++++++---
 tests/docs/test_submission_docs.py | 19 ++++++++++++
 4 files changed, 84 insertions(+), 8 deletions(-)
```

## Proof
- `pytest tests/docs -q` → `29 passed in 0.13s`. The baseline at 4071b59 was 27; my two new tests make 29.
- `make check PY=/Users/hari/src/orchapod-hack/.venv/bin/python` (no E2E, no ui-smoke) → exit 0.
  - ruff: `All checks passed!`
  - pytest: `1179 passed, 1 skipped, 2 warnings in 200.83s (0:03:20)`. The skip is tests/providers/test_local_docker.py, which is expected while Docker Desktop's proxy hangs.
  - web: `tests 51 / pass 51 / fail 0`.
  - Then `SKIP stub e2e: set E2E=1`.
  - PY is passed explicitly because the worktree has no `.venv`.
- TDD: both new tests failed first.
  - The README list lacked `['Oct 22', 'Oct 24', 'Oct 25', 'Oct 27']`.
  - `'TODO' not in FEEDBACK` failed.
  - Both pass after the edits.

## What changed
1. **README "What changed during the submission period":** the TODO line is replaced by one bullet each for Oct 22, Oct 24, Oct 25 and Oct 27.
   - They are written in the style of the Oct 20 and Oct 21 bullets: semicolon lists, with facts from CHANGELOG.md only.
   - Oct 25 names the hosted demo, both live golden runs (7/22/1 in 24 minutes for $1.61; 7/20/3 in 23.5 minutes for $1.58) and the multi-state run. Its caveat, in CHANGELOG's words, is "on 30 held-out questions from its own synthetic set".
   - Oct 27 is the cost check that lists only the steps that rent a GPU (`vllm-serve`'s L40S at $1.55 an hour instead of an H100 at $4.50 for every step).
2. **docs/devpost.md:** the same four bullets replace its TODO line. The only change from the README's wording: the hosted URLs carry `https://`, as elsewhere in that file.
3. **README status note:** the date is now 2026-10-27. The rest is unchanged, including its TODO(D8) for the video and the Devpost link.
4. **docs/feedback.md:** the closing TODO is replaced by two `##` sections.
   - **What worked well** has 5 bullets, each a fact with `Source:`:
     - both golden runs on Serverless Jobs and Endpoints ($1.61, $1.58);
     - Super's guided-JSON planner (valid on the first call in spike 2; the same six nodes at $2.66 on 10-25, 10-26 and 10-27);
     - Super's 300 grounded rows for about $0.03;
     - Ultra judged all 30 questions in each of the three live runs, for about $0.0027 a question, with consistency 0.73, 0.67 and 0.70;
     - thinking off (7 against 129–139 completion tokens).
     A scan of the new sections for praise words finds only the heading the brief requires.
   - **Questions** has 32 lines, one per finding, in the same order, under `###` Token Factory (18), Nebius AI Cloud (12) and NVIDIA Nemotron models (2).
     - The question lines avoid the seed needles in tests/docs (each needle is still on exactly one line), so the seed test still guards each finding.
     - Every line that names the OpenAPI carries its version, as test_findings_that_cite_the_openapi_name_its_version requires.
5. **Beyond the task list, done so that feedback.md is "ready to paste" (the brief's "Why now"):**
   - Three other TODO(D8)s in feedback.md are gone:
     - The intro sentence about TODO markers and the re-check of every page is gone. The re-check moved to devpost.md Links: "TODO(D8): re-check the pages it cites, then paste it into the Devpost field and link it on GitHub."
     - The TODO to load the Token Factory adapter in vLLM and llama.cpp is gone. The finding now says "we have not loaded it in either", because Lane A never ran live.
     - The TODO for the rate on Nebius's bill is gone; it is now asked in Questions.
   - New tests in tests/docs/test_submission_docs.py:
     - `test_the_period_lists_have_a_bullet_for_every_changelog_date`: README and Devpost each have a `- <Mon> <day>` bullet for every dated CHANGELOG heading.
     - `test_feedback_is_ready_to_paste`: no TODO in the file, 4 to 6 sourced "What worked well" bullets, as many questions as findings, and each question ends in "?".

## TODO markers left (README, devpost.md)
- README:9 has TODO(D8) for the video and the Devpost link. README:201 has TODO(D8) for the video link.
- devpost.md:
  - :3 is the copy instruction.
  - :64 is the logged-out check of the demo.
  - :65 is the video URL.
  - :66 has TODO(G3) for the repo going public, then a logged-out check.
  - :67 has TODO(D8) to re-check the cited pages, paste the feedback and link it on GitHub.
- README:114 and README:156 keep TODO(G3): the repo is private, and the GHCR packages refuse anonymous pulls. These clear only after Hari's step D, and this brief does not name them.

## Open questions
1. README:114 and :156, and devpost.md:66, keep TODO(G3) until the repo and the GHCR packages are public (Hari, G3 checklist D). Should devrel clear them after that step, or the orchestrator at the tag?
2. devpost.md:67's TODO(D8) (re-check the pages, paste the feedback, link it on GitHub) is a submission-time step. It is not literally one of the allowed items (video, Devpost link, logged-out checks). Is it acceptable for checklist C?
3. Suppose Hari reads the Serverless Job and Endpoint rates on the Nebius bill before submitting. Then the finding "Serverless AI's own GPU-hour rate is unverified" can state the billed rate, and its question line changes or goes. The test then needs one question per finding still.
4. The heading "To record from live runs" is kept. Its golden-run bullet overlaps the new Super and Ultra bullets in "What worked well" (d20d30f3's $0.0295, $0.0802, 0.733). I left it unchanged. Say if the overlap should go.

## For the Orchestrator to record
- DECISION candidate: docs/feedback.md stays TODO-free, with one question per finding (test_feedback_is_ready_to_paste).
- DECISION candidate: the README and Devpost "What changed" lists get a bullet for every dated CHANGELOG heading (test_the_period_lists_have_a_bullet_for_every_changelog_date).
  - So a CHANGELOG entry under a new date, such as Oct 28 or 29, fails tests/docs until both lists have its bullet.
