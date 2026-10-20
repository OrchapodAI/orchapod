# devrel-w1 report — wave 1 (2026-10-20)
Status: DONE_WITH_CONCERNS · branch `hack/devrel-w1` (worktree `/Users/hari/src/orchapod-hack/.claude/worktrees/devrel-w1`; `git merge-base --is-ancestor 178d2e6 HEAD` = yes; HEAD was 7f27372 before my commits) · cost $0 (no API call, no container, no network).

**Concern.** Bash was limited to git for this dispatch, so I could not run pytest or `make check`. Every "proof" below is a desk-check with `git grep` (outputs quoted), not a test run. Run before merging: `cd /Users/hari/src/orchapod-hack/.claude/worktrees/devrel-w1 && . /Users/hari/src/orchapod-hack/.venv/bin/activate && python -m pytest tests/docs -q && make check`. Expected: 5 new tests pass, and `make check` stays green (153 baseline + 5 = 158 on this base; more with ml-w1 merged). Nothing else in the tree changed, so ruff is unaffected.

## Commits (never pushed)
- `4e25d76` docs(readme): rewrite as the hackathon stage-one README
- `1475dee` test(docs): README drift guard
- Trailer is `Co-Authored-By: Claude Sonnet 5.5` (my harness reminder). The role file in this worktree still says Opus 5.5; deefaef on NebiusHackathon already changed the rule to "use your harness trailer".

## What I delivered
- `README.md`, rewritten (200 lines, was 246). Order follows the brief: what it is, why, how it works (node table, two lanes), how we use Nemotron / Token Factory / Nebius AI Cloud / Tavily, setup, run the demo, costs and caps, what changed during the submission period, repository map, license.
  - Sponsor usage is concrete: five Nemotron roles with the three real ids from contracts (Super planner + teacher, Ultra judge, Lightning quality filter + reporter), Token Factory fine-tuning (Lane A), Serverless Jobs / Endpoints / Object Storage (Lane B), Tavily search + extract with credit metering.
  - Known inconsistencies fixed: `studio.nebius.ai` → `tokenfactory.nebius.com` / `https://api.tokenfactory.nebius.com/v1`; "Super 49B", "Ultra 253B" and "Nemotron Mini 4B" → real ids; clone URL → `github.com/bangadpurva/orchapod.ai` (`-b NebiusHackathon`); port 8000 → 8001; manual Postgres/Redis/MinIO/Colima/alembic steps → `make up` (create_all runs at API start).
  - 16 `TODO(D8)` lines mark everything that needs evidence: links, hosted URL, results, screenshots, measured cost/time, spike 1 (deploy path, exact 8B id, fine-tune price), spike 4 (Lane B student), GPU quota, Job/Endpoint ids, GHCR public pull, "no other provider" proof, CHANGELOG refresh, node table vs `NODE_REGISTRY`. No result is claimed.
  - Budgets are labelled design budgets (Lane A < $2, Lane B ≈ $2.8 per R14), not measurements. I dropped the old tagline "In 25 minutes. Under $5." (unmeasured, and above the $3 run cap).
- `tests/docs/test_readme.py` (+ empty `__init__.py`, like the other test dirs): 5 tests, stdlib only. Required sections; the three model ids, Token Factory URL and clone URL present (ids also present in contracts.md); no stale string (legacy host, old model names, `localhost:8000`, removed env vars, Cloudflare/Clerk/Cleanlab); every TODO is `TODO(D8)`; every `make <target>` in a code span exists in the Makefile and every `NEBIUS_*`/`TAVILY_*`/`ORCHAPOD_*` name exists in contracts.md or NODE_CONTRACT.md.

## Proof (desk-check, not a test run)
Green at HEAD (`git grep` on the working tree):
```
sections: 9 of 9   (README.md lines 12 27 36 66 99 138 149 174 198)
stale strings, bad clone URL (-P "bangadpurva/orchapod(?!\.ai)"), bare TODO: no hits (rc=1)
TODO(D8) lines: 16
make targets in code: up check down agent-e2e e2e demo   ⊂ Makefile {up down check e2e agent-e2e demo checkpoint}
env names (17 distinct, e.g. ORCHAPOD_R2_, NEBIUS_PROJECT_ID, ORCHAPOD_MAX_COST_USD): each found in docs/contracts.md or NODE_CONTRACT.md
model ids: 3 of 3 in README and in contracts
```
Red at the base README (`git grep … 178d2e6 -- README.md`): required sections present 1 of 9 (License only); `nvidia/Nemotron-3_5-Lightning` absent; clone URL `github.com/bangadpurva/orchapod` (line 69, no `.ai`); 19 stale hits (studio.nebius.ai ×4, Ultra 253B ×4, Mini 4B ×4, localhost:8000 ×2, Super 49B, NEBIUS_FOLDER_ID, Cleanlab, Cloudflare, Clerk); no `TODO(D8)`. So 4 of 5 tests fail without the rewrite; the make-target/env-var test passes vacuously on the old README (it has no make commands) and is a forward guard.

## What is not verified
- pytest and `make check` not run (see Concern). The test was re-read line by line; regex semantics were checked with PCRE `git grep -P`, which matches Python's here.
- No README command was executed. I checked them against sources instead: Makefile, `infra/docker-compose.dev.yml`, `apps/api/main.py` (create_all at startup), `storage.py` (`ensure_bucket_exists` has zero callers, hence the boto3 bucket step), `next.config.ts`, `local_docker.py` (rewrites localhost to host.docker.internal), CI. Unrun: the boto3 snippet, `PYTHONPATH=apps:packages/sdk-py uvicorn api.main:app --port 8001`, the `NEXT_PUBLIC_*` override on `pnpm dev`.
- The README describes the post-wave-2 system from contracts v1. At this commit these do not exist yet (all TODO-marked or listed here for D8): `packages/providers/tokenfactory.py` and `tavily.py` (platform-w1); `STUB=1` (only `STUB_TEACHER` in synth today); `/agent` page (frontend-w1) and the Agent API, templates, report (backend wave 2); web-research, tf-finetune, tf-deploy, judge-eval nodes (wave 2); `scripts/e2e_demo.py`, `e2e_agent.py` (qa D3), `seed-golden-run.py` (backend D4) behind `make e2e / agent-e2e / demo`; ruff, huggingface_hub, jsonschema in `requirements-dev.txt` (qa-w1) which the README's `pip install` line relies on for `make check`; the `.env.example` rewrite (platform-w1) which makes "the rest is preset for the local stack" true; CI `:latest` (qa-w1) and public GHCR packages (human).
- Stage-one claim "No other model provider is called on this path" is TODO-marked. Still in the tree at this base: `anthropic==0.40.0` in `apps/api/requirements.txt`; `apps/api/agent/workflow_builder.py` and `routes/workflows.py:142` (Claude); `run_workflow.py:241-242` forwards OPENAI/ANTHROPIC keys (backend-w1 drops them); synth-distilabel `teacher_kind` and `pip install openai anthropic` (data wave 2); `.env.example` and compose still name ANTHROPIC_API_KEY.

## Open questions / for the Orchestrator
1. **Date conflict.** CHANGELOG.md line 3 and PLAN.md line 48 say the first commit is May 7, 2026. `git log --reverse` shows root commit 367c605 "Initial commit" on 2026-05-04 (Purva), 40 commits before Aug 26, all May 4–20. The README says only "May 2026" and points at `git log --before=2026-08-26`. Fix CHANGELOG.md before it is pasted into Devpost (or tell me the date to use; GitHub's repo-creation date may be the May 7 source).
2. **Disclosure.** The repo shows an AI-assisted build (CLAUDE.md, `.claude/`, `hackathon/`). The README lists `hackathon/` as "build journal" and says nothing more. Hari decides whether README/Devpost state it.
3. **Merge.** Take devrel's README wholesale. ml-w1's only README hunk (synth build command with the repo root as context) is subsumed by the README's "Node images" paragraph, which states the same rule with a data-prep example.
4. Suggested CHANGELOG line (yours, not edited): "README rewritten for the submission (what/why/how, Nemotron + Token Factory + Nebius AI Cloud + Tavily usage, setup, costs and caps) with a test that keeps it consistent with the contracts."

## Found in files I do not own (not touched; each affects the README or its claims)
- `apps/web/next.config.ts:5-6`, `lib/api.ts:6`, `lib/ws.ts:6` default to `localhost:8000` (8000 is complychip2's). README works around it with `NEXT_PUBLIC_API_URL/WS_URL` on `pnpm dev`; once the defaults are 8001 the override line can go. (frontend / platform)
- `infra/docker-compose.dev.yml:65,80,105-106`: `api` publishes 8000, `JUDGE_MODEL` defaults to `nvidia/Llama-3.1-Nemotron-Ultra-253B-v1`, still ANTHROPIC_API_KEY / CLOUDFLARE_TUNNEL_TOKEN. Nobody in wave 1 owns compose (ml-w1 raised the same). `.env.example:26` still says `studio.nebius.ai`.
- Legacy host `api.studio.nebius.ai` remains in `packages/providers/nebius.py:17,39`, `containers/lm-eval/run.py:40`, `containers/synth-distilabel/run.py:37`, `apps/api/services/nebius_token_factory.py` (platform deletes it).
- `apps/api/services/storage.py::ensure_bucket_exists()` has no caller, so a fresh MinIO has no `orchapod-artifacts` bucket and the first output upload would fail. One call in the API lifespan (backend) or a compose init step removes the bucket step from Setup, which matters for QA's 20-minute fresh-clone test.
- `scripts/seed-demo-workflow.py` is the old YC demo (Qwen3, Vast.ai, `localhost:8000`, posts to `/api/workflows`, which is not a route). `make demo` points at a different, unwritten script. Candidate for deletion; the README does not mention it. `scripts/build-and-push-containers.sh` is also stale (ml-w1 item 6).
- `docs/WORKFLOW_SPEC.md` (7 node types, Vast.ai/RunPod, "YC demo", "under $5 on Vast.ai") and `docs/NODE_CONTRACT.md` (hard-coded bucket, no cost/metrics, short env table) predate contracts v1. docs/ is mine but outside this brief, so I linked NODE_CONTRACT.md and deliberately not WORKFLOW_SPEC.md. Proposed for D4: regenerate the node list from `NODE_REGISTRY` and update the env table.

## DECISIONs to record
- DECISION 2026-10-20: README convention is API `:8001`, web `:3000`, local stack via `make up`; the web app needs the `NEXT_PUBLIC_*` override until its defaults move — devrel-w1.
- DECISION 2026-10-20: the README is written against contracts v1 as the end state; whatever depends on a spike result, unmerged work or a measurement is a `TODO(D8)` line, and `tests/docs/test_readme.py` keeps ids, ports, env names and make targets consistent with contracts.md and the Makefile — devrel-w1.
- DECISION 2026-10-20: demo cost claims in the README are the R14 / PLAN design budgets (Lane A < $2, Lane B ≈ $2.8), labelled as such; the "25 minutes, under $5" tagline is removed until measured — devrel-w1.

## Fix round 1 (orchestrator review): `a6f9e72` README, `be103ce` test; HEAD `be103ce`
Supersedes the first-pass numbers above (README 200 lines, 16 TODO(D8) lines, 5 tests, 158 total). Still not run (Bash is git-only for this role). Desk-check by `git grep` on the edited files: 9 of 9 sections; no hit for the 4 stale strings, the bad clone URL or a bare TODO; the 4 setup-guard strings are present (README L104, L107, L111, L186); `make` targets in code (up, check, down, agent-e2e, e2e, demo) all exist in the Makefile; 12 env names, all in contracts.md or NODE_CONTRACT.md. Expected: 6 tests in `tests/docs` pass, 159 total on the 7f27372 base (153 + 6).

**Important 1, spike-dependent claims are conditional** (README line numbers at HEAD):
- L40 Lane A: "fine-tunes on Token Factory. TODO(D8): spike 1 decides serving — a per-token LoRA model (no GPU quota) or `vllm-serve` with the adapter (needs GPU quota)." Your wording, with `vllm-serve` in backticks.
- L49 (tf-deploy row) and L84 (prose): "deploy(s) the adapter as a per-token LoRA model if Token Factory accepts the base (TODO(D8): spike 1), then …".
- L51 (vllm-serve row) and L91 (Serverless Endpoints bullet): "(TODO(D8): spike 4 confirms vLLM loads the adapter)".
- Left as is: L41 and L50, which are design statements; L51, L90, L91 and L93 tag what they depend on.

**Important 2, test** (`tests/docs/test_readme.py`, now 86 lines): L76-77 no longer asserts `"TODO(D8)" in README`; only the bare-TODO regex remains, so the test passes on a finished README with no TODOs.

**Also applied:**
- README L62 `cost_json` and `metrics_json`. L19 "each must run from the chat box … TODO(D8): which intents have run end to end." (I changed "runs" to "must run" and ended the sentence with a full stop, since the table follows a blank line.) L31 "The Nemotron models share …". L111 `make check` comment now "stub e2e (TODO(D8): script pending)"; L143 "TODO(D8): the stub e2e is not verified end to end yet." L136 Lane B paragraph is one sentence pointing at `.env.example` (true once platform-w1's rewrite merges).
- Repository map deleted (old L184-197, including the blank line, so License follows one blank line and is now L184). README is 186 lines. `hackathon/` no longer appears in the README, so open question 2 (disclosure) is moot for it.
- Test: `STALE` cut to studio.nebius.ai, Super 49B, Ultra 253B, localhost:8000 (L40-45; "Mini 4B" and the env-var, Cloudflare, Clerk and Cleanlab entries are gone); the `"Tavily"` needle is removed (L57); new `test_setup_and_license_lines` (L62-69) asserts the `git clone -b NebiusHackathon https://github.com/bangadpurva/orchapod.ai.git` line, `make up`, `make check` and `[MIT](LICENSE)`.
