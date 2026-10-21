# qa-w4 report: wave 4 (2026-10-21)

**Status:** DONE. All three items are complete, and the item-3 additions are done too.
- Two pieces are written but not executed. The CI job needs a push to run, and the Playwright test is orchestrator-only (`make ui-smoke`).

**Branch:** `hack/qa-w4`, worktree `.claude/worktrees/qa-w4`, base 6f2f5da (`git merge-base --is-ancestor 6f2f5da HEAD` passes). Not pushed.

**Spend:** $0. No key was used and no model was called.
- Network calls were limited to: pip and pnpm installs in the temp clone; an anonymous `git ls-remote` of the README's clone URL; anonymous GHCR registry probes.

**Docker:** I built, tagged and removed no `orchapod/*` image. I ran none of `make up`, `make down`, E2E or ui-smoke, and started no server on 8000–8002.
- `make check` builds and removes its usual throwaway `orchapod-test/exit1:<uuid>` image (tests/providers/test_local_docker.py).
- One disclosure: I stopped my temporary `next dev` (temp clone, port 3000) with `pkill -f "next dev --turbopack"`.
  - That pattern would also match ui-smoke's web server.
  - No other `next dev`, Playwright or e2e_ui process was running, before or after (checked with pgrep and lsof).

## Commits (oldest first)
| SHA | What |
| --- | --- |
| 421c63a | test(drills): failure drills from faked responses, asserting the run page's exact error (tests/drills/, new) |
| fdfbd17 | ci: build the prod api and web images on NebiusHackathon pushes, never pushed (+ harness test) |
| 90b95a0 | test(ui): at ORCHAPOD_ANON_SCALE=0.1 a template above the per-run cap keeps Run disabled and says why (spec + e2e_ui.py's public-scale API) |

8 files, +511 −14. The changes sit in tests/drills/, tests/test_harness.py, tests/e2e/test_e2e_ui.py, tests/ui/smoke.spec.ts, scripts/e2e_ui.py and .github/workflows/ci.yml.

## 1. Failure drills (`tests/drills/test_failure_drills.py`, no Docker)
**How they run.**
- The executor is the real one, started through `POST /runs/{id}/start` (and `/retry`).
- Its provider runs each node's own `containers/<node>/run.py` `main()` in-process, under the env the executor built, with the real SDK:
  - uploads land in an in-memory bucket;
  - the SDK's `/internal/log`, `/internal/progress` and `/internal/artifact` posts (with its secret header) are replayed through the API;
  - `cost_json` and `logs` are written by the SDK's own exit hook.
- Provider replies are faked with `httpx.MockTransport`.
- Each drill asserts `GET /runs/{id}/summary`: `status`, the run `error` and every node's `(id, status, error)`. That `error` is the string the run page shows verbatim.

| Drill | Faked | The run page shows (exact) | Recovers? |
| --- | --- | --- | --- |
| Token Factory 429, then success (synth-distilabel, intent #2 rows) | 429 `Retry-After: 2`, then 200 | run `succeeded`, error `null` | Yes. The client slept exactly 2.0 s and resent once; cost = one call ($0.0009), so the 429 is not billed. |
| Fine-tune job ends `failed` (tf-finetune → tf-deploy) | job `failed`, error.message | `exit 1: Token Factory job ftjob-1 failed: train.jsonl line 3: the last message must be from the assistant` | Run failed. tf-deploy stays `pending`; no cancel is sent. |
| Fine-tune job ends `cancelled` (on Token Factory's side) | job `cancelled`, error null | `exit 1: Token Factory job ftjob-1 cancelled: no message` | As above. |
| Judge timeout (judge-eval, 2 rows) | Ultra raises `ReadTimeout`; base/tuned answer | `exit 1: 2 of 2 rows failed (more than 10%); first: judge: token_factory server None: ReadTimeout('The read operation timed out')` | Fails readably. `eval_summary` is still registered (n 2, judged 0, errors 2); each row is tried 4 times; only the 4 answers are billed. |
| Tavily out of credits (web-research → synth) | 432 with Tavily's JSON body | `exit 1: tavily quota 432: {"detail":{"error":"This request exceeds your plan's set usage limit. Please upgrade your plan or contact support@tavily.com"}}` | Fails readably. One request (not retried), $0, synth `pending`. |
| Preempted Serverless Job (unsloth-train on the gpu provider, admin) | checkpoints 100 and 200 via the SDK, then SIGTERM (SystemExit 143); Job end ≠ COMPLETED → 1, per contracts "NebiusProvider" | `exit 1` (**no reason**: see What does not work, 1) | Yes, by Retry node: the retried Job gets `ORCHAPOD_RESUME_CHECKPOINT_URI` = `…/train/checkpoint_step_000200`, and the run succeeds. |

**Visitor refusals (anonymous, ORCHAPOD_ANON_SCALE 0.1).** The `detail` strings asserted, and how the UI's `explainError` shows them:

| Refusal | Asserted (exact) |
| --- | --- |
| 402, day share spent, at `POST /agent/plan` | `day cap $1.5: nothing left` → "Over budget: …" |
| 402, day share spent, at `POST /runs/{id}/start` | `day cap $1.5: $0.00 left` |
| 402, plan above the run cap, at `POST /agent/run` (docs template, full plan) | `run cap $0.3: $0.30 left, the plan needs $<estimate>` (today $0.77) |
| 429 (backend-w4), the 6th `POST /agent/plan` from one address | `Retry-After: 12`, `too many requests from your address; try again in 12 s` |
| 409 (backend-w4), anonymous PUT and DELETE on a workflow with a run | `this workflow has runs, so it is read-only on the public app; save a copy as a new workflow`; the admin's PUT is 200 |
| 403 (backend-w4), anonymous start of an unsloth-train run | `unsloth-train runs on a rented GPU, billed by the hour: only the admin can start it on the public app` |

- The three backend-w4 tests carry `skipif(api.services.ratelimit is missing)`, reason "SKIP (not a pass): backend-w4's D6 refusals are not merged".
  - My base predates backend-w4's merge (85140ab), so on the branch they SKIP. On the merged tree they run and pass (Proof).

### Proof
- **`make check` on 90b95a0: exit 0.** Results:
  - `All checks passed!`
  - `685 passed, 3 skipped` (the 3 are the backend-w4 refusals)
  - web `pass 27, fail 0`
  - `SKIP stub e2e`
  - (base: 675)
- **Trial merge with NebiusHackathon @ 8a3a43b** (`git merge --no-commit`, then aborted): clean, no overlapping files.
  - `tests/drills`: `11 passed`.
  - The gate on the merged tree: ruff `All checks passed!`, pytest `715 passed`, web 27/27.
- **Mutation checks: 13 of 13 caught.** Each mutated one production line, ran its drill (it failed), then reverted with `git checkout`.

  | Area | Mutation |
  | --- | --- |
  | Retry and 429 | Retry-After ignored; 429 not retried |
  | Fine-tune | tf-finetune's "no message" dropped |
  | Node error | /internal/log no longer keeps the ERROR line |
  | Judge | judge-eval tolerates every failed row |
  | Tavily | 432 no longer a quota error |
  | Retry and resume | retry clears the node's outputs; the executor resumes the oldest checkpoint |
  | Budget | the 402 sentence loses its cap |
  | backend-w4 (merged tree) | 429 without Retry-After; plan burst 6; anonymous rewrite of run workflows allowed; gpu guard off at 0.1 |

- **Stability:** drills plus the tf-finetune, judge-eval and web-research unit tests, 5 runs in a row: `81 passed, 3 skipped` each time, 2.7 s.

## 2. README audit: temp clone, non-Docker steps run and timed
Setup:
- `git clone -b NebiusHackathon /Users/hari/src/orchapod-hack` (the local repo, tip 8a3a43b; GitHub needs credentials, gap 1) into the scratchpad.
- Then the README's commands, in its order, on this Mac (Python 3.12.13, node 26.5, pnpm 11.0.9).
- The clone (800 MB with .venv and node_modules) is deleted.

| README line | Command | Time | Result |
| --- | --- | --- | --- |
| 104 | `git clone -b NebiusHackathon …` | 1.1 s (local path; 18 MB .git) | The README's GitHub URL fails logged out (gap 1). |
| 106 | `cp .env.example .env` | 0.0 s | ok |
| 107 | `make up` | not run (Docker) | read: compose project orchapod-hack; postgres:16 on 5432, redis:7 on 6379, minio on 9000/9001; credentials match .env.example |
| 109 | `python3.12 -m venv .venv && . .venv/bin/activate` | 1.4 s | ok |
| 110 | `pip install -r requirements-dev.txt -r apps/api/requirements.txt` | 17.6 s (warm pip cache) | exit 0 |
| 111 | `make check` | 16.9 s | exit 0: ruff clean, `702 passed`, web 27/27. It needs no `pnpm install` (the web tests use no node_modules). |
| 118–123 | create the bucket (boto3) | not run (MinIO) | redundant (gap 6) |
| 126–127 | `set -a; . ./.env; set +a` + `PYTHONPATH=apps:packages/sdk-py uvicorn api.main:app --port 8001` | not run (Postgres, Redis, MinIO; port 8001 is off limits here) | `.env` sources cleanly; `import api.main` with that PYTHONPATH from the repo root: ok, 0.9 s, 46 routes |
| 130 | `cd apps/web && pnpm install` | 2.2 s (warm store) | **exit 1** on pnpm 11: `ERR_PNPM_IGNORED_BUILDS: sharp@0.34.5` (all packages installed anyway; gap 2) |
| 131 | `NEXT_PUBLIC_API_URL=… pnpm dev` | 0.7 s | **exit 1** at once: pnpm 11's deps check re-raises the same error, so Next never starts (gap 2) |
| 131 (workaround) | `pnpm --config.verify-deps-before-run=false dev` | Ready in 0.8 s | `GET /agent` 200 after 5 s |
| 134 | `pnpm test` (in apps/web) | 0.7 s | **exit 1** on pnpm 11, same error; the tests never run |
| 145 | `make e2e` / `make agent-e2e` | `--help` only | both refuse real runs: "only --stub exists so far" |

**Totals.**
- Non-Docker steps: about 40 s on this Mac's warm caches. A truly fresh machine adds the pip and pnpm downloads.
- The Docker half (images; Postgres, Redis and MinIO pulls; building the node images a first run needs) is for D7 on the hosted VM, as briefed.

### README gaps for devrel (line numbers from NebiusHackathon @ 8a3a43b)
**P0: a fresh visitor cannot reach a first run as written.**
1. **L104.** `https://github.com/bangadpurva/orchapod.ai.git` is not readable logged out.
   - Anonymous `git ls-remote` asks for a username: private (or renamed) until G3.
   - Gate the README's clone line on the repo going public, a Human action already listed.
2. **L101, L130, L131, L134 (pnpm ≥ 10; 11.0.9 here).**
   - Symptoms: `pnpm install` exits 1 (`ERR_PNPM_IGNORED_BUILDS: sharp`), and `pnpm dev` and `pnpm test` then refuse to start. The web app never runs.
   - The README names no pnpm version. CI uses 9, and L114's `make check PNPM=pnpm` hint covers only make check.
   - Fix, either:
     - name pnpm 9 (`corepack enable && corepack prepare pnpm@9.15.9 --activate`), or
     - let frontend add `"packageManager": "pnpm@9.15.9"` or `pnpm.ignoredBuiltDependencies: ["sharp"]` to apps/web/package.json.
3. **L136.** Every node image `ghcr.io/bangadpurva/<node>:latest` answers 403 to an anonymous pull (registry API, all 12). So a fresh machine's first run fails at provision unless it builds images.
   - The README gives one `docker build` example.
   - It should list each intent's images and give a build-only command. `scripts/build-and-push-containers.sh` also pushes. For example:
     - intent #2: synth-distilabel and data-prep;
     - docs golden path: web-research, synth-distilabel, data-prep, tf-finetune, tf-deploy and judge-eval.
   - Alternatively, make the GHCR packages public (a Human action).
4. **L106, L127, L146.** .env.example ships `STUB=` (blank) and empty keys, so the README's API answers `/agent/plan` with 503 "NEBIUS_API_KEY is not set". L146 says "Start the API with STUB=1" but no command shows where.
   - Say: set `STUB=1` in `.env`, or `STUB=1 PYTHONPATH=… uvicorn …`.
5. **L106, L143.** .env.example sets `ORCHAPOD_ANON_SCALE=0.1` and a blank `ORCHAPOD_ADMIN_TOKEN`, and the web app sends no admin header. So a local user is a public visitor:
   - $0.30 a run and $1.50 a day;
   - Run disabled on the real-estate ($0.83) and docs ($0.55) templates;
   - gpu nodes refused (403).
   - The golden path cannot run from the local UI.
   - Say: set `ORCHAPOD_ANON_SCALE=1` in `.env` for local runs (or platform changes the local default; see open question 3).

**P1: wrong or stale.**
6. **L116–123.** The bucket snippet is unnecessary: the API creates the bucket at start (apps/api/main.py:39, `storage.ensure_bucket_exists`). Drop it or mark it optional.
7. **L127.** uvicorn binds 127.0.0.1. On Linux, node containers reach the host through `host-gateway` (LocalDocker adds `--add-host`), and that never reaches a 127.0.0.1 listener. Add `--host 0.0.0.0` for Linux; Docker Desktop works as written.
8. **L145.**
   - `make agent-e2e INTENT=…` "runs one intent through the Agent, capped at $3" is not true today: it refuses ("only --stub exists so far; the real run is written once the keys exist").
   - `make demo` (scripts/seed-golden-run.py) does exist, so "still being written" is stale for it.
   - The keyless `python scripts/e2e_agent.py --stub` (all canonical intents, $0, Docker) is not mentioned.
9. **L19–25 and L143.** "one of the three intents": the gallery has 4 templates. The 4th, "Llama 8B tuned as a Nebius docs specialist", is PLAN's golden path and is missing from the intents table.
10. **L175.** "the gpu-l40s-a rate … needs re-checking (the table uses $1.82)" contradicts L173's $1.55 (DECISION 2026-10-21). Delete the clause.
11. **L184.** The same stale TODO as L145 (`make demo` exists).
12. **L80.** "TODO(D8): confirm after the legacy Anthropic and OpenAI code paths are removed (wave 2)": wave 2 removed them, so this can be confirmed now.

**P2.**
13. **L107.** `make up` publishes 5432, 6379, 9000 and 9001: a machine already running Postgres or Redis there fails. Name the ports.
14. **L164.** The 402 list omits `/agent/plan` (R18). "Costs and caps" omits the per-IP limits (backend-w4):
   - plan and run: 5, then 1 per 12 s;
   - compare: 3, then 1 per 60 s;
   - writes: 10, then 1 per 30 s.
15. **L51 and L56.** `vllm-serve` is listed as `api`, but NODE_REGISTRY says `gpu` until ml-w4 merges. L56's TODO covers it; recheck then.
16. **L114.** The recorded stub run (@1c0b746) could cite the newer green `make check E2E=1` after D6 hardening (LOG 36fc921).

## 3. CI prod images and the Playwright `fits: false` test
**CI.** The new `prod-images` job:
- `needs: test`, `if: github.event_name == 'push' && github.ref_name == 'NebiusHackathon'`.
- docker/build-push-action with `push: false`, gha cache scopes prod-api and prod-web:
  - `apps/api/Dockerfile`, context `.`;
  - `apps/web/Dockerfile`, context `apps/web`, build args `NEXT_PUBLIC_API_URL`, `_WS_URL` and `_SITE_URL` (example.com placeholders).
- `tests/test_harness.py::test_ci_builds_the_prod_images_on_nebiushackathon_and_pushes_neither` pins: the trigger, both files and contexts, `push: false`, and that every `ARG` in apps/web/Dockerfile has a build arg.
  - RED first (`KeyError: 'prod-images'`), then green.
- Not executed: it runs on the first NebiusHackathon push. platform-w4 built both images locally. No actionlint on this Mac.

**Playwright.** New test in tests/ui/smoke.spec.ts: "templates: at ORCHAPOD_ANON_SCALE=0.1 a template above the per-run cap cannot be run and says why".
- **Setup.** The smoke's own API stays at full scale, so the golden path can still run from the gallery.
  - scripts/e2e_ui.py starts a second API at `PUBLIC_CAPS = FULL_CAPS | {ORCHAPOD_ANON_SCALE: "0.1"}` (own port from 8003 up, own DB) and passes it as `E2E_PUBLIC_API_URL`.
  - The test serves the page `GET /agent/templates` from it (`page.route` → `route.continue({url})`).
- **Assertions.** For every `fits: false` card:
  - its reduced estimate really is above $0.30;
  - `Run template: <title>` is disabled;
  - its accessible description is exactly `about $X.XX — above the public demo's per-run cap; watch the golden run`;
  - the link goes to `/runs?q=<plan name>`.
  - Every other card stays enabled, and no console or API errors occur.
- **Expected today.** Real-estate ($0.83) and docs ($0.55) are disabled; movie ($0.03) and maths ($0.02) are enabled.
- **Checks.** Driver unit tests were RED first, then green: `tests/e2e` 74 passed, including the spec/driver env-name check. `node --check` passes. **Not run** (orchestrator-only).
- **To run:** `make ui-smoke`, or only this test with `make ui-smoke UI_ARGS="-g ANON_SCALE"`. Both build the intents' `:dev` images.

## What does not work / not verified
1. **A preempted Serverless Job reads `exit 1`.**
   - The node logs no ERROR line on SIGTERM.
   - The contract's NebiusProvider "logs code + message" only to the API log.
   - The Jobs provider itself is not built yet (packages/providers/nebius.py is still the legacy Compute API and needs the removed `NEBIUS_FOLDER_ID`).
   - The drill pins today's string; when the provider lands, its readable form must replace it (open question 1).
2. **Readability nits in the asserted strings** (they work, but read badly):

   | Owner | Nit |
   | --- | --- |
   | platform, packages/providers/base.py | `token_factory server None:` prints the `None` status. |
   | platform | Tavily's reason arrives JSON-wrapped; `detail.error` could be lifted out. |
   | ml | `cancelled: no message` could say "cancelled on Token Factory". |
   | backend | The 402 sentence differs between `/agent/plan` ("nothing left") and start/run ("$0.00 left"). |
   | backend | `run cap $0.3` vs `$0.30` (`:g` vs `.2f`). |

3. **Faked shapes.** The Token Factory fine-tune error text and the Tavily 432 body are plausible fakes, not recordings, since there are no keys. Swap in recordings after spikes 1 and 3.
4. **Not run here.** The CI job (needs a push), the Playwright test (orchestrator), and the Docker half of the README (D7 on the VM).

## Open questions
1. **Readable preempted-Job error.**
   - Proposal for the contract: when a gpu provider's Job ends in a non-COMPLETED terminal state, the node error becomes `exit 1: <job id> <state> <code>: <message>`.
     - For example, `wait()` raises a dedicated JobEnded(reason) that the executor shows verbatim, instead of `internal: …`.
   - Optionally, the SDK's SIGTERM handler logs one ERROR line ("stopped by SIGTERM: cancel, timeout or preemption"), which the executor's own `cancelled` and `timeout` errors already override.
   - Owner: platform-w5 (NebiusServerless jobs), plus backend for the executor line.
2. **The 402 sentence.** Unify `/agent/plan`'s "nothing left" with the guard's "$X.XX left" (backend)? The drills pin both until then.
3. **Local default.** Should `.env.example` default `ORCHAPOD_ANON_SCALE=1` for local use, with the hosted 0.1 coming from the prod compose? Or does the README say it? This is gap 5. Owners: platform or devrel.

## DECISIONs for the Orchestrator to record
- The failure drills are unit tests in `tests/drills/`, run by `make check` and CI.
  - Each node's own run.py runs in-process with the real SDK under the executor's env, against faked provider replies.
  - Each drill asserts the run page's exact `GET /runs/{id}/summary` error.
  - New D5 drills go there.
- The `fits: false` Playwright test reads its templates from a second API at `ORCHAPOD_ANON_SCALE=0.1` (scripts/e2e_ui.py `PUBLIC_CAPS`), while the page's own smoke API stays at full scale.
- CI builds `apps/api/Dockerfile` and `apps/web/Dockerfile` without pushing, on NebiusHackathon pushes only (`prod-images`); the hosted VM builds its own images.
