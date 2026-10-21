# backend-w4 report: wave 4 (2026-10-21)

**Status:** DONE, including fix round 1 (all 10 items; that section is at the end).
- The first round covered brief items 1 and 2, plus the Orchestrator's two mid-task items (`hf_token` in stored YAML, the GET /runs limit).
- Statements that fix round 1 superseded are corrected in place and marked "(fix round 1)".

**Branch:** `hack/backend-w4`, worktree `.claude/worktrees/backend-w4`, base 9578c48 (`git merge-base --is-ancestor 9578c48 HEAD` passes). It is not pushed, and Docker was not started.
**Spend:** $0. STUB=1 throughout, with no key and no network call outside localhost.

## Commits, first round (oldest first; the fix-round commits are listed in their section)
| SHA | What |
| --- | --- |
| ef3276e | docs(contracts): the D6 hardening lines (Config, Run control API, Budget guard), in a commit of their own before the code |
| e7bff8f | refactor(api): `apps/api/config.py` holds every contract Config default, and the API reads env only through `config.env` |
| 9d14131 | feat(api): CORS allow-list from `ORCHAPOD_CORS_ORIGINS`; never credentials |
| 82e5fe3 | feat(api): per-IP token buckets, 429 with Retry-After |
| 5d4422c | fix(api): public lists are capped (GET /runs, /workflows, /artifacts) |
| d1718c0 | fix(api): /inference/deploy never writes an `hf_token` into the stored workflow |
| 4d365ae | feat(api): deep `/health` and shallow `/livez` |
| 2c01d27 | fix(api): the backend-w2 KNOWN CEILING. Its title overstates: an admin node's *grant* no longer blocks anonymous callers, but admin *spend* still does (fix round 1) |
| 16f9da8 | test(api): the kill switch is read on every request |
| 60f0ff2 | test(api): fixes a race in my own admin-in-flight test (an order-dependent teardown error) |
| 8b1fc68 | style(api): the forwarded env names as one split string (gitleaks false positive, see below) |
| 1b6f216 | fix(api): GET /workflows defaults to its 500 cap, because the merged runs page names its runs from that list |

## What was built
### 1. D6 public-demo hardening
- **CORS** (`apps/api/main.py: cors()`).
  - `ORCHAPOD_CORS_ORIGINS` is a comma list of exact origins.
  - Blank (the default) allows only this machine's pages: `https?://(localhost|127.0.0.1)(:port)?`. That covers `next dev` on 3000 or 3001 and qa-w3's Playwright at `127.0.0.1:31xx`.
  - Credentials are never allowed, because the web app sends none. So `*` works, but never with credentials.
  - `Retry-After` is exposed, so the browser can read a 429.
  - Before: every origin was echoed with `Access-Control-Allow-Credentials: true`.
- **Per-IP rate limits** (`apps/api/services/ratelimit.py`, a route dependency, checked before body validation and the budget guard).

  | Bucket | Routes | Burst, then refill |
  | --- | --- | --- |
  | plan | POST /agent/plan, /workflows/from-prompt | 5, then 1 per 12 s |
  | run | POST /agent/run, start, retry, /inference/deploy | 5, then 1 per 12 s |
  | compare | POST /compare | 3, then 1 per 60 s (fix round 1; was 10, then 1 per 6 s) |
  | write | POST/PUT/DELETE /workflows, POST /runs and cancel, POST /models | 10, then 1 per 30 s (fix round 1) |

  - Over the burst: 429, `Retry-After: <s>`, and a detail that names the wait.
  - /workflows/from-prompt (the same planner) and /inference/deploy (a launch path) are included. Without them, each limit could be bypassed by a sibling route.
  - **The address is `request.client.host` (fix round 1).** The prod image runs uvicorn with `--forwarded-allow-ips "*"` behind Caddy, which overwrites X-Forwarded-For, and api:8000 is not published.
    - The first round's own X-Forwarded-For walk and `ORCHAPOD_TRUSTED_PROXIES` are gone.
  - IPv6 counts per /64, and an IPv4-mapped address counts as its IPv4.
  - `take()` is async, so it runs on the event loop and no two requests interleave in it. The dict stays in last-use order, and refilled buckets are dropped from the front.
  - `ponytail:` the buckets live in the process, so this needs one worker (like the budget grants); more workers or hosts need Redis. Many addresses together can still drain the anonymous share; the day cap and the kill switch are the backstop.
- **`/health` is now deep.** Database (`SELECT 1` on the engine), Redis (`PING`) and object storage (`HeadBucket`) are checked concurrently, 3 s each.
  - 200 `{"status":"ok"}`, or 503 `{"status":"fail","failed":["redis","storage"]}`.
  - Causes go to the log only.
  - Concurrent callers share one check, and its result is reused for 10 s (fix round 1).
- **`/livez` is shallow:** 200 while the process answers. It is meant for the watchdog and the container healthcheck.
- **Kill switch, confirmed read per request.** `budget.kill_switch()` → `config.env()` → `os.environ` on every call. Plan, run, start, retry and /compare check it on every request, and the executor at every node boundary. A test flips it between requests on the same app (1 → 503, 0 → through, "true" → 503, blank → through). A cached version fails that test.
  - **For docs/HOSTING.md:** a running container's env cannot change. "`ORCHAPOD_KILL_SWITCH=1` in .env, then `docker compose up -d api`" recreates the API. The startup sweep then fails every run in flight ("control plane restarted") and terminates its pods, so the kill switch also stops runs already going.
- **KNOWN CEILING: an admin node's grant never blocks anonymous callers; admin spend does.** I kept no separate pot; instead, each grant carries the scale it was granted at (`budget._granted[run_id] = (usd, scale)`).
  - `left()` is the least of three:
    - the run cap × scale, less the run's cost;
    - the caller's share of the day (day cap × scale), less the day's spend and the grants made at that scale or below;
    - the whole day cap, less the day's spend and every grant.
  - Tests for both callers:
    - An admin node holds its whole $3 while an anonymous start gets 200 and a $0.30 grant. Before the fix: 402.
    - Unit (day $4, anonymous scale 0.5):
      - the admin's $3 leaves an anonymous caller $1 (the whole day binds), then $0;
      - with the admin released, anonymous grants fill the $2 share;
      - an admin counts every grant.
  - The R20 guarantee still holds: concurrent runs never exceed the day cap.
  - **Ruling (fix round 1):** admin spend still counting against the anonymous share is accepted under the operating rule: no admin runs on the hosted instance, and the golden run is seeded there.
### 2. `apps/api/config.py` (it deletes duplication)
- `DEFAULTS` holds every contract Config variable plus `ORCHAPOD_CORS_ORIGINS`. `ORCHAPOD_TRUSTED_PROXIES` was added and then removed in fix round 1.
- `env(name)` reads os.environ on every call; blank = default; an undeclared name is a KeyError.
- **Duplication removed:**
  - the 5 R2 defaults (executor `_FORWARD` and storage.py);
  - the Token Factory base literal (executor; config imports `TF_BASE`);
  - email.py's third `ORCHAPOD_CONTROL_URL` default (`https://orchapod.ai`).
- `ORCHAPOD_CONTROL_URL`'s default lives only here (`http://localhost:8001`, as in the contract); this Mac's 8002 comes from .env.
- 11 modules switched, net −8 lines in them.
- No settings object, because a cached object would break per-request reads and the tests' monkeypatching. The contract line was amended.
- A test fails if any `apps/api/**/*.py` other than config.py reads `os.environ`/`os.getenv`, or if any `config.env("X")` name is not declared.
### Orchestrator items
- **`hf_token`:** the `DeployRequest.hf_token` field and the 3 YAML lines in `_build_workflow_yaml` are gone. The request still accepts the key (extra keys are ignored), so the web form still posts.
  - Test: all 3 modes posted with a token. Neither `hf_token` nor its value appears in any stored workflow YAML, graph_json or run inputs.
  - `apps/api/routes/models.py` writes no YAML. It has only the `requires_hf_token: True` catalog flag (the registry page's badge), so nothing was removed there.
  - Fix round 1 removes the root cause: secret-looking inputs are dropped at every ingest point.
- **List caps:**
  - GET /runs `limit` = `Query(50, ge=1, le=500)`: 500 accepted, 0 and 501 are 422.
  - Same root cause: GET /workflows had no limit at all. It is now `Query(500, ge=1, le=500)`. The default is the cap because frontend-w4's runs page (on NebiusHackathon) names its 500 runs from an unparameterised GET /workflows; a default of 50 would have hidden the golden run's old workflow from the `/runs?q=` link.
  - GET /artifacts gains `ge=1`. SQLite read `limit=-1` as no limit, and Postgres would 500.

## Proof (first round; fix round 1's is in its section)
- **`make check`** in the worktree on 1b6f216: exit 0.
  - `All checks passed!`
  - `596 passed, 2 warnings` (base: 580)
  - web `tests 22, pass 22, fail 0`
  - `SKIP stub e2e`
- **Live smoke over real HTTP** (scratchpad smoke.sh).
  - Setup: `--no-proxy-headers` and `ORCHAPOD_TRUSTED_PROXIES=127.0.0.1`. Both were dropped in fix round 1, whose smoke runs uvicorn exactly as the prod image does.
  - `/livez` → `{"status":"ok"} HTTP 200`
  - `/health` → `{"status":"fail","failed":["redis","storage"]} HTTP 503 in 0.50s`
  - Preflight from `http://localhost:3000` and `http://127.0.0.1:3100` → 200 with the origin echoed and no credentials header.
  - Preflight from `https://evil.example` → `400` with no ACAO.
  - 6 plans from one address → `200 200 200 200 200 429`, with `retry-after: 12` and `access-control-expose-headers: Retry-After`.
  - `/runs?limit=500` → `200`; `limit=501` → `422`.
  - uvicorn log: 0 tracebacks.
- **Mutation checks: 13 of 13 caught** (rate limits 7, health 2, budget 3, kill switch 1). The two X-Forwarded-For mutations among them were dropped together with the feature in fix round 1.
- **Dry merge with NebiusHackathon @ 8ec7bcd:** clean, and the merged tree gave `613 passed, 1 skipped`.
- **gitleaks** over 9578c48..HEAD: 1 false positive. The generic-api-key rule read the env-var name `"ORCHAPOD_R2_SECRET_KEY", "ORCHAPOD_R2_BUCKET"` as a key and its value.
  - Fixed forward in 8b1fc68.
  - History fingerprint for `.gitleaksignore`: `e7bff8fd0ad2543e9b51e944e480858ea6b587f6:apps/api/executor/run_workflow.py:generic-api-key:49`.
  - The same pattern predates my work at tests/api/test_executor.py:232.

## For platform and .env.example (corrected in fix round 1)
- **`ORCHAPOD_CORS_ORIGINS`.** Default blank (this machine's pages). Hosted: `https://app.${DOMAIN}`. NebiusHackathon's prod compose sets it, and its .env.example documents it (commented).
- **There is no `ORCHAPOD_TRUSTED_PROXIES`.** It was removed in fix round 1, never reached .env.example, and nothing needs to add it.
- **Keep `--forwarded-allow-ips "*"` in apps/api/Dockerfile.** My first-round advice to drop it was wrong: without it, every visitor would share Caddy's bucket. Caddy overwrites X-Forwarded-For and api:8000 is not published, so uvicorn's `request.client.host` is the real client.
- **The compose api healthcheck and scripts/watchdog.sh belong on `/livez`** (the Orchestrator does this at merge). A Redis or storage outage would otherwise restart the API, which fails every run in flight. `/health` is for UptimeRobot.
- **tests/providers/test_env_example.py `names_read()`** scans `os.environ.get("X")` literals, so it does not see the API's `config.env("X")` reads.
  - It passes on the merged tree.
  - Taking the `api.config.DEFAULTS` keys as well would keep new API variables from escaping it.

## Notes for others
- **frontend.**
  - Rate-limited calls answer 429 with the detail "too many requests from your address; try again in N s" (the toasts show it), and `Retry-After` is readable.
  - GET /runs accepts `limit` up to 500.
  - Fix round 1 adds two cases:
    - The canvas Save (PUT) on a workflow that has runs answers 409 for anonymous callers: "this workflow has runs, so it is read-only on the public app; save a copy as a new workflow". Offering "Save as new" (POST /workflows) on that 409 would complete the flow.
    - An anonymous Run of a plan with a gpu node answers 403 with a plain message, and `fits` is false for such a template.
  - `hf_token` can go from the web form (listed in fix round 1).
- **qa.**
  - In tests/api, an autouse `no_rate_limits` fixture makes the buckets endless; tests/api/test_hardening.py restores the real ones.
  - The e2e scripts start real APIs, so the real limits apply. e2e_agent (3 plans, 3 runs) and the Playwright smoke (1 worker, 0 retries, at most 3 per bucket) stay under every burst.
    - Compare's burst is now 3, enough for the smoke's probe and playground.
  - The e2e `wait_healthy` polls `/health`, which now needs Redis and the bucket (a moment of 503 until `ensure_bucket_exists` runs).
- **Tests and the module engine.** A test that hits the module-level aiosqlite engine (`api.database.engine`) leaves a connection thread alive, and pytest then never exits. The health tests point it at the test's engine.

## What does not work / limits
1. **Fixed in fix round 1.** Anonymous PUT/DELETE on a workflow with runs → 409.
2. **Fixed in fix round 1.** Anonymous callers never start a gpu node.
3. **Accepted by ruling.** Admin spend counts against the anonymous share (operating rule: no admin runs on the hosted instance).
4. **Compare concurrency per address.** The compare bucket limits rate, not concurrency. A burst of 3 now bounds one address to 3 slots at the start, but a per-address in-flight cap of 1 would close it.
5. **GET /models is still unbounded.** Its tag filter runs in Python after the query, so a SQL limit would change results. Its writes are now rate-limited.
6. **/inference/deploy builds YAML with f-strings** from `model` and `served_model_name`, so a newline can inject keys.
   - Since fix round 1, anonymous callers can't use the vllm-serve modes at all (gpu, 403), aliases are refused, and every launch still passes the guards.
   - Delete the route (audit P2), or build the YAML with `yaml.safe_dump`.
7. **Cancel has no ownership.** Anyone can cancel any run in flight (now rate-limited in the write bucket).
8. **Stored-YAML redaction is ingest-only.** Workflow YAML stored before fix round 1 is returned as stored; node and run inputs are redacted on the way out. The hosted DB starts fresh.

## DECISIONs to record (corrected in fix round 1)
1. **Per-IP limits.**
   - Rates: plan 5, then 1/12 s; run 5, then 1/12 s; compare 3, then 1/60 s; write 10, then 1/30 s.
   - The buckets live in the process (one worker), and an empty bucket answers 429 + Retry-After.
   - The address is `request.client.host`, as uvicorn `--forwarded-allow-ips "*"` reports it behind Caddy. IPv6 counts per /64, and IPv4-mapped addresses as IPv4.
2. **CORS.** `ORCHAPOD_CORS_ORIGINS`: blank = local pages on any port, else exact origins. Credentials are never allowed.
3. **Health.** `/health` is deep (database, Redis, storage; 3 s each; 503 names what failed; one check shared and reused for 10 s). `/livez` is shallow and serves the watchdog and the container healthcheck.
4. **The anonymous share of the day budget.** A grant counts against the whole day for everyone, and against a caller's share only when granted at that scale or below. Spend counts against every share, so admin spend does block anonymous callers (accepted with the operating rule).
5. **Config.** `apps/api/config.py` `env(name)` replaces the contract's "one pydantic-settings object": it reads per call, blank = default, and no value is cached.
6. **Kill switch.** It is read per request, and flipping it on the hosted app means recreating the API container, which fails the runs in flight.
7. **List caps.** GET /runs: 1..500, default 50. GET /workflows: 1..500, default 500. GET /artifacts: ≥ 1.
8. **Public app (fix round 1).**
   - An anonymous caller (scale < 1) gets 403 for gpu nodes at /agent/run, start, retry and /inference/deploy.
   - A workflow with runs is read-only to anonymous callers (409); the admin is the token itself, not scale 1.
   - YAML aliases → 422.
   - Secret-looking node inputs are dropped at ingest (POST/PUT /workflows, from-prompt, /agent/run), and node and run inputs are redacted on the way out.
   - POST /inference/extend is deleted.

## Contract lines changed (ef3276e, cd06121, 1004f55; the Orchestrator approves at merge)
- **Config.** The config.py line describes `env(name)`. `ORCHAPOD_CORS_ORIGINS` joins "Control plane". `ORCHAPOD_TRUSTED_PROXIES` was added in ef3276e and removed in cd06121.
- **Run control API.**
  - The per-IP rate limits bullet, with 4 buckets and the address rule.
  - The `/health` and `/livez` bullet (shared and cached).
  - A new "Public app (D6)" bullet: gpu 403 and `fits`, read-only workflows with runs, aliases 422, secret inputs dropped at ingest and redacted on the way out, extend deleted.
- **Budget guard.**
  - How a grant counts, worded: "an admin node's grant never blocks anonymous callers; admin spend does", plus the operating rule.
  - The kill switch is read per request.
- **No ruling number was taken.** The Orchestrator's R23 (ml-w3) sits in another hunk, and the merge is clean.

---

## Fix round 1 (Orchestrator review; all 10 items done)
### Commits (oldest first; 17 files, +407 −250 in the round; 28 files, +882 −283 on the branch)
| SHA | Item | What |
| --- | --- | --- |
| cd06121 | all | docs(contracts): the round's contract lines, before the code |
| 966a045 | 1, 3, 9 | fix(api): rate limits key on the client uvicorn reports, `take()` runs on the event loop, buckets prune from the front; compare 3, then 1/60 s |
| ddb5bc9 | 4 | fix(api): workflow YAML with an alias is refused (422) before it can expand |
| 9eeb3fb | 5 | fix(api): delete POST /inference/extend/{run_id} and its models |
| ace82dd | 6 | fix(api): a workflow with runs is read-only to anonymous callers (409); writes get their own per-IP bucket |
| 1dc8b14 | 7 | fix(api): anonymous callers never start a gpu node (403 at /agent/run, start, retry and /inference/deploy) |
| 2861995 | 8 | fix(api): /health runs one deep check at a time and reuses its result for 10 s |
| 59d321d | 10 | fix(api): secret-looking node inputs are dropped before a workflow or plan is stored; node and run inputs are redacted on the way out |
| b1165fe | 2 | docs(api): the ceiling docstring and test name say what it does |
| 1004f55 | 7 | docs(contracts): `fits` is false for an anonymous caller whose reduced plan has a gpu node |
| c970d79 | 7 | test(api): the gpu `fits` check uses two synthetic templates (data-w4 added a 4th template upstream) |

### Per item
1. **Proxy (I2 + ponytail).**
   - `address()` is `request.client.host`, with IPv6 per /64 and `a.ipv4_mapped or a`, so `::ffff:203.0.113.7` counts as `203.0.113.7`.
   - The X-Forwarded-For walk, `_proxies()` and `ORCHAPOD_TRUSTED_PROXIES` are gone from the code, config DEFAULTS and the contract.
   - The report is corrected above (platform section, DECISION 1).
2. **Ceiling (I3).** contracts:264 and `budget.left()`'s docstring now read "an admin node's grant never blocks anonymous callers; admin spend does", with the operating rule. The test is renamed `test_an_admin_nodes_grant_never_blocks_anonymous_callers`.
3. **Rate-limit race (M1).**
   - `take` is `async def`, so FastAPI awaits it on the event loop instead of the threadpool.
   - The key is popped and re-inserted, so the dict is in last-use order.
   - Refilled buckets are deleted from the front until the first one still in use: amortised O(1), no full scan, and no "dictionary changed size during iteration".
   - New test: 40 simultaneous `/compare` from one address under `sys.setswitchinterval(1e-6)` get exactly 3 × 422 and 37 × 429.
     - The race alone showed only 1 time in 3 with a sync `take`, so the test also pins `inspect.iscoroutinefunction(limit(...))`. A sync `take` now fails it every time (3/3).
     - The order test fails when the key is read with `get` instead of `pop`.
4. **YAML alias bomb (P1).**
   - `dag.load_yaml()` scans `yaml.parse(…, Loader=SafeLoader)` and raises on any `AliasEvent` before `safe_load`. `compile_dag` uses it, so POST/PUT /workflows (422), the executor and the planner are all covered.
   - Anchors alone are still accepted.
   - Test: my bounded copy of the reviewer's chain (under 1 KB, 9^6 leaves) gets 422 on POST and PUT, and nothing is stored.
   - Measured: a 721-byte chain with 9^10 leaves (the ~4 GB class) is refused in 0.4 ms in-process, and in 80 ms over HTTP.
5. **POST /inference/extend deleted (P2).** The route, `ExtendRequest`, `ExtendResponse`, `_HOURLY_COST_USD` and 6 imports went with it, and the stale `_ttl_tasks` comment was fixed.
   - Test: a run with a RUNNING vllm-serve node, extend with -60 → 404, cost unchanged. Before the deletion: 200.
6. **Writes (OPEN 1).**
   - Anonymous PUT/DELETE on a workflow that has a run → 409 "…read-only on the public app; save a copy as a new workflow". Drafts stay editable and deletable by anyone.
   - The admin check is a new `budget.admin()` dependency (the token itself; `scale()` uses it). So `ORCHAPOD_ANON_SCALE=1` does not make the public admin, and a test pins that.
   - The `write` bucket covers POST/PUT/DELETE /workflows, POST /runs and cancel, and POST /models. Test: 10 writes across those routes, then 429, while the plan bucket stays separate.
7. **GPU time (OPEN 2).**
   - `budget.gpu_guard(types, scale)` answers 403: "unsloth-train runs on a rented GPU, billed by the hour: only the admin can start it on the public app".
   - It applies at /agent/run (the plan's nodes), start (all nodes) and retry (only nodes not yet succeeded, so a run whose GPU part is done retries anonymously).
   - I added /inference/deploy, a launch path the brief did not name: its serve modes create vllm-serve, which is gpu today.
   - `/agent/templates`' `fits` is false for an anonymous caller whose reduced plan has a gpu node.
   - The admin is unchanged.
   - Three existing deploy tests that start vllm-serve now send the admin token. The launcher-scale test uses the CPU-only GGUF mode.
8. **/health (M2).** One deep check at a time (`asyncio.shield`ed, so a caller that hangs up leaves it to the others), reused for `HEALTH_TTL_S` = 10 s.
   - Test: 20 simultaneous probes make 1 storage check. A flip inside 9.9 s still answers the cached 200; at 10 s, 503.
   - Live: the first probe took 0.64 s, the next two 0.5 ms each.
9. **Compare refill (M3).** compare is now 3, then 1 per 60 s. The module's `ponytail:` note says that many addresses can still drain the anonymous share, and that the day cap and the kill switch are the backstop.
10. **hf_token root cause (M4).**
    - `redact.without_secrets(spec)` drops every node input whose key matches the R22 rule: `hf_token` and `api_key` go, while `max_tokens` and an `api_key_env` naming a variable stay. It drops rather than redacts, so a node never receives "[redacted]".
    - Applied at POST/PUT /workflows (re-dumped only when something was dropped), /workflows/from-prompt, and /agent/run (I added it; it stores a plan too).
    - Node and run inputs are redacted in `_node_run_out` and `_run_out` (GET /runs, /runs/{id}, /runs/{id}/nodes…).
    - test_runs.py's deploy docstring no longer claims the schemas lost `hf_token`.

### `hf_token` in other owners' files (NebiusHackathon @ 67f0dc4; not edited)
- `packages/workflow_schema/models.py:252`, `VLLMServeInputs.hf_token` (ml).
  - HFDownloadInputs and QuantizeInputs lost theirs in ml-w3, but this base still has them.
- `containers/vllm-serve/run.py:16, :195, :214` reads `inputs.get("hf_token")` before `HF_TOKEN` (ml-w4's rewrite).
- `apps/web/app/inference/page.tsx:89, :115, :321`: the HF token field the deploy form sends (frontend). The API now ignores it.
- `apps/web/lib/types.ts:159`, `hf_token?: string` (frontend).
- The `requires_hf_token` lines (`apps/web/lib/types.ts:115`, `app/registry/page.tsx:80`, `apps/api/routes/models.py`) are a badge flag, not a token. Keep them.

### Env vars for .env.example
- **Added on this branch:** `ORCHAPOD_CORS_ORIGINS` (blank = this machine's pages; hosted `https://app.<domain>`). NebiusHackathon's .env.example and prod compose already carry it.
- **Removed:** `ORCHAPOD_TRUSTED_PROXIES`. It was added in the first round and removed in this one, and it never reached .env.example or compose.
- **Nothing else.**
  - `HEALTH_TTL_S` (10) and the bucket rates are constants, not env.
  - Uvicorn's `--forwarded-allow-ips "*"` stays in apps/api/Dockerfile as it is.

### Proof
- **`make check`** on c970d79: exit 0. `All checks passed!`, `605 passed, 2 warnings`, web 22/22, `SKIP stub e2e`.
- **Mutation checks this round: 17 of 17 caught.**

  | Area | Mutations |
  | --- | --- |
  | Limiter | 5: sync take (3 of 3 runs), get instead of pop, no pruning, IPv4-mapped as ::/64, refusal refills |
  | Write rules | 2: anonymous rewrite allowed, admin = scale ≥ 1 |
  | GPU | 4: no guard, retry counts succeeded nodes, fits ignores gpu (re-run after the test rewrite), deploy unguarded |
  | Health cache | 1: always recompute |
  | Secrets | 5: POST/PUT, from-prompt and /agent/run stored as sent; node or run inputs unredacted |
  | Alias and extend | Not counted: their tests failed before the fix (201 for the bomb, 200 for extend) |

- **Live smoke over real HTTP** (scratchpad smoke2.sh). uvicorn ran as the prod image runs it (`--forwarded-allow-ips "*"`), with STUB=1, a scratch DB, and Redis and storage on closed ports.

  | Check | Result |
  | --- | --- |
  | 6 plans with X-Forwarded-For 203.0.113.5 | `200 ×5, 429` |
  | Another client | `200` |
  | compare ×4 | `422 422 422 429`, `retry-after: 60` |
  | 40 simultaneous compares from one address | `3 × 422, 37 × 429` |
  | /health ×3 | 503 `["redis","storage"]` in 0.64 s, then 0.5 ms, 0.6 ms (2 health log lines in all: one check) |
  | Alias bomb (721 bytes) | 422 in 80 ms |
  | Anonymous start of an unsloth-train run | 403 with the message |
  | Anonymous PUT on its workflow | 409 |
  | `hf_token` at ingest | not stored |
  | /inference/extend | 404 |
  | 11 workflow creates | `201 ×10, 429` |
  | uvicorn log | 0 tracebacks; process gone |

- **Dry merge with NebiusHackathon @ 67f0dc4** (platform-w4 and data-w4 included): clean.
  - The merged tree, extracted: ruff clean, `640 passed, 1 skipped`.
  - One test was deselected: `tests/providers/test_hosting.py::test_deploy_never_ships…` runs `git rev-parse HEAD` and fails identically on a plain NebiusHackathon extract, which has no `.git`. It is an artifact of the extraction, not a failure.
  - My own `fits` test broke on the merged tree (data-w4's fourth template) and was fixed in c970d79.
- **gitleaks** over 1b6f216..HEAD and `gitleaks dir apps/api`: no leaks found.

### Left open
- **Canvas Save on a workflow with runs.** It now gets 409 for anonymous users; the frontend should offer "save a copy" (POST /workflows).
- **The runs page's horizon.** It names runs from the newest 500 workflows, so the golden run stays findable through `/runs?q=` only while it is among the newest 500 runs and workflows. A `workflow_name` on RunOut would remove the dependency (backend + frontend).
- Limits 4–8 above.
