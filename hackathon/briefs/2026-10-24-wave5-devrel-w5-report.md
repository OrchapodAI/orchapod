# devrel-w5 report: wave 5 (2026-10-21)

**Status:** DONE. Item 1 is complete: the README and Devpost refresh for waves 3–4, all 16 qa-w4 audit gaps, docs/video-script.md:14 and the "E2E=1 is strict" wording.

**Branch:** `hack/devrel-w5`, worktree `.claude/worktrees/devrel-w5`, base 5354f75 (`git merge-base --is-ancestor 5354f75 HEAD` passes). Not pushed.

**Spend:** $0. No key was used, no model was called, no image was built and no server was started. The only Docker use was `make check`'s own throwaway `orchapod-test/exit1:<uuid>` image (tests/providers/test_local_docker.py), as the brief allows.

## Commits (oldest first)
| SHA | What |
| --- | --- |
| fd0edc6 | docs(readme): waves 3–4 and qa-w4's 16 audit gaps (README.md, tests/docs/test_readme.py, tests/docs/test_submission_docs.py) |
| 69ac42d | docs(devpost): result views, four templates, the CPU measurement, demo guards, what changed |
| 4888a1a | docs(video): both golden-run topics have a template card; one click runs the reduced plan; shot 5 needs a live tuned model |
| 7b80b15 | docs(readme): GPU nodes also need https object storage (platform-w5, merged meanwhile, refuses a local MinIO) |

Diff: 5 files, +107 −66. docs/feedback.md is unchanged (see Open questions 3).

## Proof
- **TDD.** At the base, `pytest tests/docs -q` gave `23 passed`. After the test edits and before the README edit it gave `2 failed, 23 passed`: `test_no_stale_strings` ($1.82) and `test_every_template_card_is_in_the_readme`. After: `25 passed`. The node-table guard was green from the start, because the table already matched; it now pins it.
- **`make check`** in the worktree on 7b80b15: exit 0.
  - ruff `All checks passed!`
  - pytest `702 passed, 2 warnings in 16.95s` (base 700 + the 2 new guards)
  - web `tests 27, pass 27, fail 0`
  - `SKIP stub e2e: set E2E=1`
- **Trial merges.**
  - `git merge-tree --write-tree NebiusHackathon HEAD` is clean against da97314, which has platform-w5 merged and the re-dated CHANGELOG.
  - Clean against hack/qa-w5 and hack/platform-w6.
  - hack/backend-w5 conflicts in apps/api/routes/internal.py with the base 5354f75 as well, so the conflict is not mine.
  - `pytest tests/docs` ran in a detached throwaway worktree, created and removed, on two merge commits that are on no branch. Both gave `25 passed`:
    - my branch + NebiusHackathon da97314;
    - the same + hack/qa-w5.

## The 16 audit gaps (qa-w4 report, line numbers from 8a3a43b)
| # | Gap | Now in README.md |
| --- | --- | --- |
| 1 | Clone URL not readable logged out | Setup says the repo is private until the freeze and the clone needs read access until then (TODO(G3)). The clone line stays, because `test_setup_and_license_lines` pins it. **Infra: Human action (repo public at G3, default branch).** |
| 2 | pnpm 11: install, dev and test exit 1 | Setup gives `pnpm --config.verify-deps-before-run=false dev` (and `… test`), with the why in one sentence: install ends with `ERR_PNPM_IGNORED_BUILDS: sharp` after installing everything, and pnpm's pre-script dependency check then re-raises it. It also names pnpm 9 as CI's version (`make check PNPM=pnpm`). **Code: frontend-w5 may fix it in apps/web.** |
| 3 | GHCR images refuse anonymous pulls | "Node images" says the packages refuse anonymous pulls until made public (TODO(G3)). It gives a build-only loop (`docker build -t orchapod/$n:dev …`) and every template's image list, and notes that `scripts/e2e_agent.py --stub` builds the canonical three. It also flags unsloth-train at about 20 GB. **Infra: Human action (GHCR public).** |
| 4 | .env ships `STUB=` blank, so the Agent answers 503 | "The app": set `STUB=1` in `.env` for a keyless run. Blank needs the keys; without the Nebius key `/agent/plan` answers 503 "NEBIUS_API_KEY is not set" (planner.py:323). **Infra: .env.example default (platform), see Open question 1.** |
| 5 | `ORCHAPOD_ANON_SCALE=0.1` makes every local user a visitor | "The app": set `ORCHAPOD_ANON_SCALE=1`. It says why: no admin header from the web app, $0.30/run, $1.50/day, no GPU-renting node, Run disabled on the two fine-tune templates. **Same open question.** |
| 6 | Bucket snippet unnecessary | Deleted. "the API creates its tables and its bucket itself" (main.py:39). |
| 7 | uvicorn on 127.0.0.1 fails on Linux | `--host 0.0.0.0` on Linux, with the reason (host-gateway). Also: the stub e2e scripts' API binds 127.0.0.1, so they work on Docker Desktop only (e2e_demo.py:161 ponytail). |
| 8 | agent-e2e, demo, keyless e2e | `make demo` is described as working: it seeds the golden run, today a STUB placeholder (TODO(D8)), and needs `.env` loaded, which I checked in seed-golden-run.py. `make agent-e2e` and `make e2e` refuse real runs (TODO(D8)). `python scripts/e2e_agent.py --stub` is the documented first keyless run. |
| 9 | 4 templates; docs specialist missing | The intents table has an Intent / Template card / Plan row per template, including "Llama 8B tuned as a Nebius docs specialist". A new test requires every templates/*.json title in the README. |
| 10 | $1.82 clause contradicts $1.55 | Deleted. "$1.82" is now in STALE, which also covers devpost, feedback and video-script. |
| 11 | Stale TODO "make demo being written" | "What changed" was rewritten from the re-dated CHANGELOG (ab1b328: Oct 20 and Oct 21 entries). |
| 12 | Confirm no other provider | Confirmed by code read. The README says the Claude/teacher/judge-fallback paths were deleted during the build, and the executor's `FORWARD` (run_workflow.py:47) holds no other provider's key. See Open question 2. |
| 13 | `make up` ports | Named in the code block (5432, 6379, 9000, console 9001), plus "stop anything already listening". |
| 14 | 402 list omits /agent/plan; no per-IP limits | The guard paragraph adds `/agent/plan` 402 (R18). A new "The public app" paragraph covers rate limits (from ratelimit.py RATES), the 403 for GPU-renting nodes, the 409 on workflows with runs, secrets dropped and redacted, and the kill switch. The caps table adds `ORCHAPOD_MAX_COMPARES`. |
| 15 | vllm-serve runtime | Checked against NODE_REGISTRY: `api` + `rents_gpu`. The row says the public caps treat it as a GPU node. The "re-check this table" TODO is replaced by a test: the README table's nodes and runtimes equal the visible NODE_REGISTRY rows. |
| 16 | Cite the newer green E2E=1 | Cites 3b80954: `make check E2E=1` exit 0, all three intents passed, none skipped (LOG 2026-10-21T14:41Z). |

## The rest of item 1
- **README refresh (waves 3–4).**
  - "What it is" gains the result views: eval view, dataset card, and the compare playground when the run serves a model.
  - The intents table maps each intent to its template card and its real plan. Intent #1 shows vllm-serve, as in its template; intent #3 shows the exact template chain.
  - The node table covers the quality filter, judge-eval's llama.cpp path and quantize's f16 baseline. The Nemotron table describes the quality filter's failure gate.
  - "Results" gets two parts:
    - the measured CPU result: 18 min 01 s, exact match f16 0.78 and q4_k_m 0.84, "a gap of 3 questions in 50 that is within noise", 0.99 vs 3.09 GB, judge off, TODO(D8) for Ultra;
    - the STUB facts: e2e_agent 3/3 with none skipped on 3b80954, with run ids from LOG 14:41Z; ui-smoke 5/5 on f43fdd0, including the golden path and the public-cap check.
  - Hosting is covered in "Run the demo → Hosted" (docs/HOSTING.md, not deployed). D6 hardening is covered in "Costs and caps → The public app".
- **Honesty fixes found while checking claims.**
  - **Endpoint expiry.** "the control plane deletes the endpoint then" was not true: today's /internal/ttl does not delete Nebius endpoints, and that fix is queued in backend-w5. The README and Devpost now say "is to delete it" + TODO(D8).
  - **Lane B student.** The TODO is replaced with spike 4's evidence, marked as outside Nebius.
  - **vLLM adapter.** "spike 4 confirms vLLM loads the adapter" is corrected: the spike served merged weights, and `--enable-lora` has not run.
- **E2E=1 wording.** "both are strict: a failed intent, or a canonical plan that names a node that does not exist, fails them". That is true at the base and after qa-w5. I give no `--strict` command anywhere: qa-w5 deleted the flag (its report says `--stub --strict` now exits 2). The 3b80954 record is worded "none skipped", not "--strict".
- **docs/video-script.md:14.** Both golden-run topics now have a template card, named.
  - A card's one-click Run posts the reduced plan (apps/web/app/agent/page.tsx:91 `t.reduced ?? t`): 5 judged questions instead of 30. The script now says so, at shot 2 and in the alternative. Before, "its plan runs at once" implied the full plan.
  - Shot 3 now opens the chart tab instead of the stale "loss curve if the run page has one by D7".
  - The Recording section notes that `/compare` refuses an expired vllm-serve endpoint, so shot 5 on vllm-serve must be taken inside `keep_alive_min`. A tf-deploy model stays up.
  - The shot table still parses and the word caps hold (`test_video_script.py` green).
- **docs/devpost.md.** The same facts as the README:
  - result views, the fourth template, stub milestones;
  - the quality-filter detail, the spike-4 evidence, the endpoint-delete honesty fix;
  - a "Beyond the sponsor pieces" pair: the CPU quantization measurement (within noise, plus the arm64 llama.cpp fix) and the public-demo guards and hosting (TODO(D8): not deployed);
  - Built with: + Caddy, Playwright;
  - "What changed" matches the re-dated CHANGELOG.

## What does not work / not verified
- **Nothing ran live.** Every TODO(D8) still stands: no key, no hosted app, no golden run, no Nebius Job or Endpoint, no win rate.
- **I did not execute the README's Setup commands.** The rewritten steps rest on qa-w4's timed audit (8a3a43b), code reads and the LOG.
  - Unverified by anyone: the Linux `--host 0.0.0.0` path, and the per-template `docker build` loop on a fresh machine (this is D7's fresh-clone test on the VM).
- **"make ui-smoke passed 5 of 5 on f43fdd0" is a dated record.** After qa-w5 merges, the smoke has 4 tests (the fixture test is gone). Replace that sentence with the next recorded run.

## For the Orchestrator: code or infra changes the README now works around (true today)
1. **Repo private (gap 1) and GHCR private (gap 3).** These are Human actions already on STATE (Purva). The README carries TODO(G3) in three places: the status note, the Setup clone sentence and Node images. Delete them at G3.
2. **.env.example defaults (gaps 4, 5; qa-w4 open question 3).** Platform could default `STUB=1` and `ORCHAPOD_ANON_SCALE=1` for local use, with 0.1 and STUB blank in the prod compose / VM .env. Then the "two lines of .env" paragraph shrinks to one sentence.
3. **pnpm 11 (gap 2).** If frontend-w5 lands `packageManager: pnpm@9…` or an ignored-builds entry for sharp in apps/web/package.json, delete the README's pnpm-11 sentence.
4. **Stub e2e on Linux.** e2e_demo.py's `start_api` binds 127.0.0.1, so the documented keyless first run fails on Linux Docker. A `0.0.0.0` bind (or an env switch) would let the README drop that caveat (qa).
5. **Lines to refresh when these merge:**
   - backend-w5 (TTL delete via endpoints.delete): README "Serverless Endpoints" and the Devpost Endpoints bullet, the TODO(D8) clause "that delete is not wired to Nebius yet".
   - qa-w5: the ui-smoke count (above).

## Open questions
1. **.env.example local defaults:** platform or a README-only fix? Today it is README-only, per the brief.
2. **Stage-one scrutiny.** `containers/unsloth-train/spike/requirements.lock.txt` pins `anthropic==1.17.0` (line 11) and `openai==2.24.0` (line 112). The production unsloth-train image installs that lock (ml-w4 report), so the Lane B training image carries both SDKs. They are presumably vLLM's transitive dependencies. They are never imported on the demo path, so the README's "No other model provider is called" stays true. A judge grepping the repo may still ask; ml could note it in the lock's header or prune them if unused.
3. **feedback.md.** Not in this brief, so it is unchanged. platform-w5's "Could not confirm" list holds sourced Nebius findings for a later devrel pass:
   - the REST reference's per-endpoint pages are an interactive index;
   - `cancel` "immediately stops the underlying VM", so there is no SIGTERM grace and no cost record;
   - a blank `authToken` disables endpoint authentication;
   - a 429 means RESOURCE_EXHAUSTED (quota).
4. **AI-build disclosure** in the README or Devpost: still Hari's call (STATE, Human actions). Nothing was added.

## DECISIONs to record
- DECISION 2026-10-21: TODO markers in README.md, docs/devpost.md and docs/feedback.md:
  - TODO(D8) = waits on a live run, the hosted app or D8 evidence;
  - TODO(G3) = waits on the repo or its images going public;
  - tests/docs accepts those two and nothing else (`BARE_TODO`). — devrel-w5
- DECISION 2026-10-21: tests/docs pins the README to the code in three new ways. A new template or node, or a price correction, fails `make check` until the README follows. — devrel-w5
  - every `apps/api/agent/templates/*.json` title appears in the README;
  - the node table's nodes and runtimes equal the visible `NODE_REGISTRY` rows;
  - "$1.82" is stale in every submission doc.
- DECISION 2026-10-21: the docs never give `--strict` as a command (qa-w5 deleted the flag). "Strict" means: a failed intent, or a canonical plan naming a missing node, fails `make check E2E=1`. The intent #3 CPU result is always stated as within noise (f16 0.78 vs q4_k_m 0.84 at n = 50), never as q4 beating f16. — devrel-w5

## Fix round 1 (Orchestrator review, 2026-10-21)
**Commits:** fc8c6ac test(docs): three honesty guards; fa42b75 docs: README, devpost and video script. Both are on `hack/devrel-w5` and not pushed. The branch merges cleanly into NebiusHackathon 2d1891c.

**Proof**
- `pytest tests/docs -q`: `28 passed`, 25 before the round plus the 3 new guards.
- `make check` on fa42b75: exit 0, ruff `All checks passed!`, `705 passed, 2 warnings`, web `pass 27, fail 0`, `SKIP stub e2e`.
- Mutation check. I applied three throwaway edits at once and restored them with `git checkout`; the restored tree passes 28. Each edit failed exactly its own guard (`3 failed, 25 passed`):
  - README intent #1's `vllm-serve` changed to `tf-deploy` → `test_each_intent_row_shows_its_templates_node_chain`;
  - `judge-eval` dropped from the maths image list → `test_the_image_lists_are_the_templates_node_types`;
  - devpost's "within noise" changed to "so q4_k_m beats f16" → `test_the_cpu_exact_match_is_called_noise_wherever_it_appears`.

**Important**
1. **README:52 split.** Now: "seeded train / eval / test split stratified by source URL, so each source's rows spread across the splits".
   - **Deviation.** The requested "(each source appears in every split)" is not true for small sources. data-prep's own docstring (containers/data-prep/run.py:194-195) says "a source needs about 1/share rows to reach eval and test", and one-row sources stay in train. The LOG CORRECTION of 2026-10-21T02:12Z retracted the same wording.
   - **For the Orchestrator.** CHANGELOG.md (6fe1182) now carries that exact parenthetical. I do not own CHANGELOG. Suggest "(a source with enough rows appears in every split)", or drop the parenthetical.
2. **devpost.md:38.** Lightning "writes the run report and can filter data quality … (opt-in `quality_filter`; no template enables it yet)". I checked: no `apps/api/agent/templates/*.json` sets it, and the default is False (models.py:88).

**Minors**
1. **Endpoint expiry.** TODO(D8) added to:
   - README's caps table ("deletion at expiry is not wired to Nebius yet, so delete a live endpoint by hand; an L40S left up costs $1.55/h");
   - video-script.md shot 6 ("delete it by hand in the console after the take");
   - the Recording section ("until backend-w5 lands … the recorder deletes it by hand … once shots 5 and 6 are taken").
2. **"Side by side" hedged.** README:25 (intents table) and :56 (node table) now say "(TODO(D8): untested)".
3. **devpost.md:47.** Now "An earlier run on the same Mac had exposed … the evaluation image now drops those kernels, and the timed run used it".
4. **"a busy host"** added to README:163 and devpost:47.
5. **"secret-looking inputs never stored"** at README:202 and devpost:73.
6. **The three guards** (Proof above). The image-list guard reads only the "Node images" paragraph.
   - A helper `_templates()` now feeds the title, chain and image-list tests.
   - The noise guard covers README, devpost and feedback.
7. **Setup.**
   - Terminal 1 starts with `. .venv/bin/activate`.
   - README:121 gives Linux users one line: "there, run the app below with `STUB=1` instead (TODO(D8): not yet tried on Linux)". The uvicorn line's `--host 0.0.0.0` note already follows.
   - This is unverified: the D7 fresh-clone test on the Ubuntu VM is the first Linux run.
8. **ui-smoke.** "5 of 5 on f43fdd0" is kept as the dated record; nothing new was added.
9. **Polish.**
   - README:10 now names "the Nebius and Tavily keys".
   - README:85 reads "no other model provider's key".
   - README:97 adds "(TODO(D8): only MinIO so far)".
   - devpost:39 adds "No fine-tune has run yet: the price per trained token is unset until spike 1, and the client refuses to start an unpriced job". This is `PRICES["token_factory_finetune"]` = {} and tokenfactory.py:154-156. I added the same sentence to README's Lane A TODO, because a user with keys would hit that refusal.
   - devpost:62 now reads "TODO(G3) … goes public at the freeze; TODO(D8) then check it logged out".
