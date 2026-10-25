# devrel-w9 report: the docs after the live golden run (2026-10-25)

**Status:** DONE. The README, the Devpost text and feedback.md now state the live golden run, the hosted URLs and the bring-up findings. TODO(D8) is left only for future items.

**Branch:** `hack/devrel-w9`, base 8b17ab0 (`git merge-base --is-ancestor 8b17ab0 HEAD` passes). Not pushed.

**Spend:** $0. Bash ran only git and the tests. To count the markers I piped `git grep -o` through `sort | uniq -c`.

## Commits
| SHA | What |
| --- | --- |
| 4b9a907 | docs: the live golden run (README, devpost, tests/docs) |
| 9647160 | docs(feedback): the six bring-up items |
| 7541b79 | merge NebiusHackathon 6e397d7: it brought the golden-run fixture (60b0713) and the TTL record (LOG 06:58Z) |
| f05e68a | docs: `make demo` seeds the live golden run; the endpoint's TTL deletion worked |

## Proof
- **TDD.** I changed tests/docs first.
  - STALE gains five pre-golden-run claims:
    - "has run on Nebius yet"
    - "nor the golden run exists"
    - "the app is not deployed yet"
    - "only MinIO"
    - "No AI Cloud call has run yet"
  - The README must now name `https://app.orchapod.dev`.
  - Result: 3 failed, 23 passed. Then I edited the docs.
- **Tests dropped.** I removed two tests whose pinned TODOs the golden run answered:
  - `test_unbuilt_make_targets_are_marked_todo`: `make e2e` has a live result now.
  - `test_unmeasured_claims_carry_a_todo`: the evaluation is measured now.
- **Guard fix.** The 0.84 "noise" guard misfired on `$0.8408`. It now matches `\b0\.84\b`, and both of the real 0.84 lines still say "noise".
- **Docs tests.** `pytest tests/docs -q`: 26 passed.
- **`make check`** (no E2E) at f05e68a: exit 0.
  - ruff gave `All checks passed!`.
  - pytest gave `1122 passed, 2 warnings`.
  - The web tests gave `tests 38, pass 38, fail 0`.
  - The output ended with `SKIP stub e2e`.
- **Trial merges.** `git merge-tree` exits 0 against NebiusHackathon 6e397d7, hack/backend-w9 and hack/frontend-w8.
- **TODO markers.** The README had 22 TODO(D8) and 2 TODO(G3), and now has 4 and 2:
  - TODO(D8): the status note (video, screenshots, Devpost), the console screenshots, the Results screenshots and video link, and the freeze update of "What changed".
  - TODO(G3): the private repo and its private images.
  - The Devpost keeps its submission-time TODO(D8)s: check the links logged out, the video URL, paste the feedback, the freeze list.
  - feedback.md keeps three: the TF adapter loaded in vLLM and llama.cpp, the rate on Nebius's bill, and "what worked well".

## Facts written in
Every number comes from the brief's Context and LOG.md:715–723 (and 06:58Z after the merge).
- **README.**
  - **Status note (2026-10-25).** It names the hosted demo and the run's headline.
  - **Results.** A new lead paragraph and the brief's per-step table, plus bullets for train, evaluate, the sample win, and the first attempt (fa20d166, $0.58) with its fix 69cafd1. prep's cost cell stays blank, as in the brief.
  - **"Why".** The evaluation bullet gives 7/22/1 on 30, win rate 0.6 and consistency 0.733.
  - **How it works.** Lane B now says the golden run did both steps on Nebius.
  - **Templates and nodes.** The docs-template row and the vllm-serve node row lose "untested": `--enable-lora` ran on Nebius.
  - **AI Cloud bullets.** The Job took 11.2 min, about 6 of them the image pull. The endpoint took about 4 min to start. The bucket is in eu-north1. A new Container Registry bullet says Jobs pull from a same-project registry with no credentials.
  - **Tavily.** $0.032 (4 credits, at $0.008 a credit).
  - **Hosted.** It gives app/api.orchapod.dev and a link to the run page. The VM is in eu-west1; the bucket and the GPUs are in eu-north1.
  - **Live, headless.** It now says `make e2e` passed.
  - **Guard line.** It now says "No live run has hit a cap yet: the golden run spent $1.61 of its $3."
  - **Costs.** They stay "estimates, not measurements": $2.66 estimated, $1.61 measured.
- **README Setup (item 3).**
  - GHCR is private, and the hosted app pulls from our Nebius registry, which only our project can read. So a judge builds the images locally, as today.
  - GPU nodes need their images in a registry the Job can pull: a same-project Nebius Container Registry and `ORCHAPOD_IMAGE_PREFIX`.
- **After the merge.**
  - `make demo` now seeds the live golden run d20d30f3. The fixture includes its report, "## nebius-docs-specialist-nemotron-nano-8b: succeeded".
  - The caps table says the golden run's endpoint was gone within 3 minutes of its expiry.
  - The console-screenshot TODO now targets a future run, because the golden run's Job and Endpoint are deleted.
- **Kept honest, without markers.** These stay as plain words, since they have not run: real estate's endpoint ("not run live yet"), the CPU variant at 8B ("not run at 8B yet"), and Linux ("not yet tried on Linux").
- **Devpost.** It carries the same facts in "What it does", "Why" (with the sample win), the Token Factory, Jobs, Endpoints, Object Storage and Tavily bullets, the demo guard and the Links demo URL.
- **feedback.md.** Six new AI Cloud items, each saying what happened and what would have helped:
  1. PermissionDenied after billing activation until a CLI re-login.
  2. The vCPU quota is 0 in eu-north1, so the VM went to eu-west1.
  3. Same-project Container Registry pulls need no credentials: it worked.
  4. `--tail` is capped at 1000.
  5. The MCP server's mcp ≤ 1.16 pin breaks with pydantic 2.14, fixed by `--with "pydantic<2.12"`.
  6. Startup times: about 4 min for the endpoint, about 6 min for the 44 GB pull.
  - **Updated.** The intro, the quota line (H100 ×8 and L40S ×8 in eu-north1), the billed-rate item (our meter: $0.8408 at list) and the "To record" golden-run line ($0.0027 a judged question).
  - **Removed.** The obsolete "first Job and Endpoint" TODO.

## Not done, and why
- **Run-page features.** Persisted logs, where each step runs and canvas status are not described. backend-w9 and frontend-w8 have not merged, as you asked.
- **The run-page link.** I could not open it: Bash is git-only and I have no network. It is built from the run id and the `/runs/{id}` route.
- **Sources.** The `--tail` cap and the endpoint's 4-minute start come from the brief alone; the LOG does not record them.
- **"What changed".** The README and Devpost lists still stop at Oct 21. CHANGELOG has Oct 22–25, and their TODO(D8) covers the freeze update.
- **The video script** is unchanged. Its placeholders are filled from the recorded run, which is a fresh run.
- **STATE.md:133** still lists the golden-run topic as open, although the golden run used the docs topic. Recording the decision is the Orchestrator's.
