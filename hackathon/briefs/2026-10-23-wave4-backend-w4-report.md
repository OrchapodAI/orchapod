# backend-w4 report: wave 4 (2026-10-21)

**Status:** DONE. I did brief items 1 and 2, plus the Orchestrator's two mid-task items (`hf_token` in stored YAML, the GET /runs limit).
**Branch:** `hack/backend-w4`, worktree `.claude/worktrees/backend-w4`, base 9578c48 (`git merge-base --is-ancestor 9578c48 HEAD` passes). It is not pushed, and Docker was not started.
**Spend:** $0. STUB=1 throughout, with no key and no network call outside localhost.

## Commits (oldest first; 25 files, +550 −108)
| SHA | What |
| --- | --- |
| ef3276e | docs(contracts): the D6 hardening lines (Config, Run control API, Budget guard), in a commit of their own before the code |
| e7bff8f | refactor(api): `apps/api/config.py` holds every contract Config default, and the API reads env only through `config.env` |
| 9d14131 | feat(api): CORS allow-list from `ORCHAPOD_CORS_ORIGINS`; never credentials |
| 82e5fe3 | feat(api): per-IP token buckets, 429 with Retry-After |
| 5d4422c | fix(api): public lists are capped (GET /runs, /workflows, /artifacts) |
| d1718c0 | fix(api): /inference/deploy never writes an `hf_token` into the stored workflow |
| 4d365ae | feat(api): deep `/health` and shallow `/livez` |
| 2c01d27 | fix(api): an admin run in flight no longer blocks anonymous callers (the backend-w2 KNOWN CEILING) |
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
  | compare | POST /compare | 10, then 1 per 6 s |

  - Over the burst: 429, `Retry-After: <s>`, and a detail that names the wait.
  - /workflows/from-prompt (the same planner) and /inference/deploy (a launch path) are included. Without them, each limit could be bypassed by a sibling route.
  - The address is the TCP peer. When the peer is in `ORCHAPOD_TRUSTED_PROXIES` (IPs or CIDRs, blank = none), it is the nearest X-Forwarded-For hop outside that list, so a hop the client prepends counts for nothing.
  - IPv6 counts per /64.
  - Buckets that have refilled are forgotten once there are more than 10,000.
  - A bad `ORCHAPOD_TRUSTED_PROXIES` stops the API at start rather than failing requests later.
  - `ponytail:` the buckets live in the process, so this needs one worker (like the budget grants); more workers or hosts need Redis.
- **`/health` is now deep.** Database (`SELECT 1` on the engine), Redis (`PING`) and object storage (`HeadBucket`) are checked concurrently, 3 s each.
  - 200 `{"status":"ok"}`, or 503 `{"status":"fail","failed":["redis","storage"]}`.
  - Causes go to the log only.
- **`/livez` is shallow:** 200 while the process answers. It is meant for the watchdog and the container healthcheck.
- **Kill switch, confirmed read per request.** `budget.kill_switch()` → `config.env()` → `os.environ` on every call. Plan, run, start, retry and /compare check it on every request, and the executor at every node boundary. A test flips it between requests on the same app (1 → 503, 0 → through, "true" → 503, blank → through). A cached version fails that test.
  - **For docs/HOSTING.md:** a running container's env cannot change. "`ORCHAPOD_KILL_SWITCH=1` in .env, then `docker compose up -d api`" recreates the API. The startup sweep then fails every run in flight ("control plane restarted") and terminates its pods, so the kill switch also stops runs already going.
- **KNOWN CEILING, fixed (the smaller diff).** I kept no separate pot; instead, each grant carries the scale it was granted at (`budget._granted[run_id] = (usd, scale)`).
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
### 2. `apps/api/config.py` (it deletes duplication)
- `DEFAULTS` holds every contract Config variable, plus the 2 new ones. `env(name)` reads os.environ on every call; blank = default; an undeclared name is a KeyError.
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
- **List caps:**
  - GET /runs `limit` = `Query(50, ge=1, le=500)`: 500 accepted, 0 and 501 are 422.
  - Same root cause: GET /workflows had no limit at all. It is now `Query(500, ge=1, le=500)`. The default is the cap because frontend-w4's runs page (on NebiusHackathon) names its 500 runs from an unparameterised GET /workflows; a default of 50 would have hidden the golden run's old workflow from the `/runs?q=` link.
  - GET /artifacts gains `ge=1`. SQLite read `limit=-1` as no limit, and Postgres would 500.

## Proof
- **`make check`** in the worktree on 1b6f216: exit 0.
  - `All checks passed!`
  - `596 passed, 2 warnings` (base: 580)
  - web `tests 22, pass 22, fail 0`
  - `SKIP stub e2e`
- **Live smoke over real HTTP** (scratchpad smoke.sh).
  - Setup: `uvicorn api.main:app --port 18765 --no-proxy-headers` with STUB=1, a scratch SQLite DB, Redis and storage on closed ports, and `ORCHAPOD_TRUSTED_PROXIES=127.0.0.1`.
  - Results:
    - `/livez` → `{"status":"ok"} HTTP 200`
    - `/health` → `{"status":"fail","failed":["redis","storage"]} HTTP 503 in 0.50s`
    - preflight from `http://localhost:3000` and `http://127.0.0.1:3100` → 200 with the origin echoed, no credentials header; from `https://evil.example` → `400` with no ACAO
    - 6 plans with `X-Forwarded-For: 203.0.113.5` → `200 200 200 200 200 429`
    - the 7th → `429`, `retry-after: 12`, `access-control-expose-headers: Retry-After`
    - prepending `198.51.100.1, 203.0.113.5` → still `429`; another client through the proxy → `200`
    - `/runs?limit=500` → `200`; `limit=501` → `422`
    - uvicorn log: 0 tracebacks; the process was killed and port 18765 is free.
- **Mutation checks: 13 of 13 caught.**
  - Rate limits 7/7: deploy unlimited, from-prompt moved to the run bucket, leftmost XFF hop, XFF trusted from anyone, IPv6 counted per address, no pruning, Retry-After not exposed.
  - Health 2/2: no timeout, always 200.
  - Budget 3/3: the share counts admin grants (the old ceiling, which gives the 402), no whole-day term, and the same re-checked after the test rewrite.
  - Kill switch 1/1: `lru_cache` on `kill_switch()`.
- **Dry merge with NebiusHackathon @ 8ec7bcd** (`git merge-tree --write-tree`, nothing touched): clean. The merged tree, extracted to the scratchpad: ruff clean, `613 passed, 1 skipped`.
- **gitleaks** over 9578c48..HEAD finds 1 false positive. The generic-api-key rule read the env-var name `"ORCHAPOD_R2_SECRET_KEY", "ORCHAPOD_R2_BUCKET"` in a tuple as a key and its value.
  - Fixed forward in 8b1fc68, so `gitleaks dir apps/api` is clean.
  - History fingerprint for `.gitleaksignore` (orchestrator's file): `e7bff8fd0ad2543e9b51e944e480858ea6b587f6:apps/api/executor/run_workflow.py:generic-api-key:49`.
  - The same pattern exists before my work, at tests/api/test_executor.py:232 (the forwarded-env test's set literal).

## For platform-w4 and .env.example (new env vars)
- **`ORCHAPOD_CORS_ORIGINS`.** Default blank (this machine's pages). Hosted: `https://app.${DOMAIN}`, which the prod compose already sets.
- **`ORCHAPOD_TRUSTED_PROXIES`.** Default blank (trust nobody). Hosted: Caddy's address as an IP or CIDR. Pin it, either by giving the compose network an `ipam` subnet and trusting that subnet, or with a fixed `ipv4_address` for caddy. Hostnames are not accepted, and the API refuses to start on a bad entry.
- **apps/api/Dockerfile must drop `--forwarded-allow-ips "*"`.** With it, uvicorn rewrites the client from the leftmost X-Forwarded-For hop of any peer before the app's trusted-proxy check runs. Use `--no-proxy-headers` (the smoke ran this way) or a list equal to `ORCHAPOD_TRUSTED_PROXIES`. Uvicorn's default `FORWARDED_ALLOW_IPS=127.0.0.1` is harmless behind Caddy, whose peer address is not 127.0.0.1.
- **The compose api healthcheck and scripts/watchdog.sh belong on `/livez`, not `/health`.** A Redis or storage outage would otherwise restart the API, which fails every run in flight. `/health` is for UptimeRobot (hosting proposal line 79: "asking backend for a deep check").
- **tests/providers/test_env_example.py `names_read()`** scans `os.environ.get("X")` literals. API reads now go through `config.env("X")`, so the scan should also take `api.config.DEFAULTS` keys; otherwise new API variables escape it.
  - `DATABASE_URL` is still seen, via alembic/env.py, so its assertion holds.
  - Its CONFIG dict and the dev compose test also need the 2 new names.

## Notes for others
- **frontend.**
  - Rate-limited calls answer 429 with the detail "too many requests from your address; try again in N s" (the toasts show it), and `Retry-After` is readable.
  - GET /runs accepts `limit` up to 500.
  - `hf_token` can go from apps/web/lib/types.ts:159 and app/inference/page.tsx:115 (it is now ignored).
- **qa.**
  - In tests/api, an autouse `no_rate_limits` fixture makes the buckets endless; tests/api/test_hardening.py restores the real ones.
  - The e2e scripts start real APIs, so the real limits apply. e2e_agent (3 plans, 3 runs) and the Playwright smoke (1 worker, 0 retries, at most 3 per bucket) stay under every burst.
  - The e2e `wait_healthy` polls `/health`, which now needs Redis and the bucket (a moment of 503 until `ensure_bucket_exists` runs).
- **Tests and the module engine.** A test that hits the module-level aiosqlite engine (`api.database.engine`) leaves a connection thread alive, and pytest then never exits. The health tests point it at the test's engine.

## What does not work / limits (not fixed; for the Orchestrator)
1. **Anonymous callers can PUT and DELETE any workflow** (no auth).
   - PUT on the golden run's workflow would change its canvas graph on the hosted app, and a later retry of that run would execute the new YAML.
   - DELETE of a workflow with runs fails on Postgres (FK, a 500); drafts can be deleted.
   - Proposal: a workflow with runs is read-only for anonymous callers (409), and the canvas saves a copy. This needs frontend work, so it is not built.
2. **GPU time is not bounded by the grant.** When the Serverless Job provider lands, a gpu node started through POST /runs/{id}/start is bounded only by `ORCHAPOD_NODE_TIMEOUT_S` (5,400 s; an H100 at $4.50/h is $6.75). Start's guard checks only that some budget is left, not an estimate, and GPU time is billed whether or not the node calls `cost.add`. Proposal: the executor caps a gpu node's wall time at grant ÷ hourly price, or gpu runtimes need the admin token. Not live today, because NebiusProvider is still the legacy stub.
3. **The anonymous share counts admin spend.** Spend is still counted against every share (contracts: caps × scale over the day's spend). So an admin who has spent $1.50 today (at the default scale) leaves anonymous callers nothing until UTC midnight. A fully separate anonymous pot needs spend tagged by caller, and that means a column or table plus a migration for existing DBs. I did not build it (the `ponytail:` note is on `reserve()`).
4. **Compare concurrency per address.** The compare bucket limits rate, not concurrency, so one address can still take all `ORCHAPOD_MAX_COMPARES` slots for the length of its streams. A per-address in-flight cap of 1 would close this (parked D6 item).
5. **GET /models is still unbounded.** Its tag filter runs in Python after the query, so a SQL limit would change results. The rows are small.
6. **/inference/deploy builds YAML with f-strings** from `model` and `served_model_name`, so a newline can inject keys such as `provider_pref`. The budget guard and the rate limit still apply. Delete the route (audit P2), or build the YAML with `yaml.safe_dump`.

## DECISIONs to record
1. **Per-IP limits.** The buckets and rates are as in the table above, including from-prompt (plan) and /inference/deploy (run). They are in-process (one worker), with 429 + Retry-After. The client IP comes from X-Forwarded-For only when the peer is in `ORCHAPOD_TRUSTED_PROXIES` (blank = none), taking the rightmost hop outside it. IPv6 counts per /64.
2. **CORS.** `ORCHAPOD_CORS_ORIGINS`: blank = local pages on any port, else exact origins. Credentials are never allowed.
3. **Health.** `/health` is deep (database, Redis, storage; 3 s each; 503 names what failed). `/livez` is shallow and serves the watchdog and the container healthcheck.
4. **The anonymous share of the day budget** (fixes the backend-w2 KNOWN CEILING). A grant counts against the whole day for everyone, and against a caller's share only when granted at that scale or below. Spend still counts against every share.
5. **Config.** `apps/api/config.py` `env(name)` replaces the contract's "one pydantic-settings object": it reads per call, blank = default, and no value is cached. The contract line was amended in ef3276e.
6. **Kill switch.** It is read per request, and flipping it on the hosted app means recreating the API container, which fails the runs in flight. That is acceptable for a kill switch.
7. **List caps.**
   - GET /runs: 1..500, default 50.
   - GET /workflows: 1..500, default 500.
   - GET /artifacts: ≥ 1.
   - /inference/deploy accepts no `hf_token`.

## Contract lines changed (ef3276e; the Orchestrator approves at merge)
- **Config.**
  - The config.py line now describes `env(name)`.
  - Two new variables join "Control plane": `ORCHAPOD_CORS_ORIGINS` and `ORCHAPOD_TRUSTED_PROXIES`.
- **Run control API.**
  - The per-IP rate limits bullet.
  - The `/health` and `/livez` bullet.
- **Budget guard.**
  - How a grant counts against the whole day and against a caller's share.
  - The kill switch is read per request and adds /compare; flipping it means recreating the API container.
- **No ruling number was taken.** The Orchestrator added R23 (ml-w3) on NebiusHackathon after my base; my edits are in other hunks, and the merge is clean.
