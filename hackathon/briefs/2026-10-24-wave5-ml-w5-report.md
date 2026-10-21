# ml-w5 report: wave 5 (2026-10-21)

Branch `hack/ml-w5`, worktree `.claude/worktrees/ml-w5`. The base check passes: `git merge-base --is-ancestor 0188074 HEAD` returns 0. Status: **DONE**, items 1 and 2. Nothing is pushed.

Spend: **$0**. I made no Nebius call, no Token Factory call and no other cloud call, and built no images. `VASTAI_API_KEY` is unset in `.env`, so no GPU could have been rented.

## Commits
| SHA | What |
| --- | --- |
| b904da4 | docs(contracts): the vllm-serve section only. Covers the per-node name, the leftover delete before the create, lost-create recovery, billing from creation and the TTL timeout. |
| d8d6a30 | fix(vllm-serve): item 1, plus the estimate-from-creation and `timeout=30` minors |
| 7a46c23 | test(vllm-serve): the bill after a deleted leftover starts at the fresh create |
| 189be77 | fix(judge-eval): `STOP.clear()` at the top of `main()` |
| 3c2f34b | docs(unsloth-train): `ponytail:` note on the GPU price ceiling |
| f50a311 | docs(registry): `rents_gpu` in the NODE_REGISTRY "Row keys" comment |

The diff is 7 files, +149/−21: `containers/vllm-serve/run.py` +55, its tests +96, and the rest are one to seven lines each.

## Item 1: vllm-serve lost-create recovery
- **Name.** The endpoint is `orchapod-<run_id[:8]>-<node_id>`, lowercased, with any character outside `[a-z0-9-]` replaced by `-`, cut at 63 characters and stripped of edge dashes. This was already the code's rule; it is now in the contract, and a test pins `orchapod-12345678-serve-8b`. It gives one name per node of a run, like tf-finetune's R19 suffix.
- **Before the create: `clear(eps, name)`.** It calls `endpoints.find(name)`.
  - If find returns an endpoint (one an earlier attempt left behind), the node logs a WARN naming it and deletes it, unless it is already DELETING.
  - It then polls `find(name)` every 15 s for up to 15 min, until the name is free, so the create cannot get a 409. If the endpoint is still listed after that, the node exits 1 ("still listed … delete it in the Nebius console") before any create.
- **Choice: delete and create fresh; never adopt.** Reasons:
  1. get()/find() return `{id, name, state, url, code, message}` with no spec. A found endpoint cannot be checked against this attempt's inputs (model, adapter, platform, preset, token). An admin can edit a workflow before a retry, and the smoke test would still pass on a stale model served under the same name (`tuned`). That would be a silently wrong eval.
  2. A found endpoint may already be registered, from an attempt that failed after `/internal/ttl`. Its backend timer would still delete it at the old expiry, earlier than the new `model_ref.expires_at`. Its keep-alive was also already billed.
  3. It is one path for every state: an ERROR or DELETING endpoint cannot be adopted anyway. The cost is one more startup (about 5 min of L40S, about $0.13), and only on a retry that finds a leftover.
  4. The most likely leftover is the previous attempt's own endpoint, still DELETING after its `finally` deleted it, when the user clicks retry. That is why DELETING is waited out rather than deleted again.
- **Right before the create.** The node logs at WARN: `creating endpoint <name> on <platform>/<preset>; if this node stops before it logs the endpoint id, delete <name> in the Nebius console`. The SDK prints it to stdout before it posts, so the line exists even if a SIGTERM cuts the create's read.
- **Lost create.**
  - `sent` becomes true just before `endpoints.create`.
  - If the create raises a `ProviderError` of any other kind than `server` or `bad_output` (that is `bad_request` including 409, `auth`, `quota` or `rate_limit`), `sent` is reset: the create was refused, so there is nothing to look for.
  - In `finally`, `sent` with no id (a 5xx, a read timeout, a reply without `resourceId`, or SystemExit(143) mid-request) runs `find(name)`. A hit is deleted and billed from just before the create.
  - On a miss, a final ERROR line says: `endpoint <name> is not listed after its create failed, but may still exist: delete it in the Nebius console`.
  - With `server` or `bad_output`, the provider's error is logged first.
- **Tests: `tests/containers/test_vllm_serve.py`, fake client.** The fake `Endpoints` records the order of find, create and delete. Its create notes which WARN lines were already logged, takes 5 s on the fake clock and can raise. Its find walks a list of results. New or changed tests:
  - The happy path does find, then create. The name is logged at WARN before the create. The TTL post has `timeout=30`. The bill is (create + polls)/3600 + 0.5 h.
  - Lost create (parametrized over a 5xx, no id, and SIGTERM): the ops are exactly find, create, find, delete ep-lost. The exit code is 1 (or 143 for SIGTERM). The bill is the create's 5 s. No TTL is registered.
  - A lost create that find misses: no delete, no bill, and the final ERROR names the endpoint for the console.
  - Refused creates (409, 401, 402, 429): exactly find, create. There is no lookup and no bill.
  - A leftover (RUNNING, ERROR or DELETING) is deleted, except when DELETING. The node waits until the name is free, then creates a fresh endpoint; the `model_ref` is the new `ep-1`. The bill starts at the fresh create, not before the cleanup wait.
  - A leftover still listed after 15 min: exit 1 with no create.
  - Pre-flight refusals now assert `ops == []`: no lookup either.

## Item 2: the ml-w4 review minors
1. **Spend from endpoint creation.**
   - The spend clock (`created`) is now taken just before the create, not after it returns. A slow create, and the lost-create lookup, are billed, and the cleanup wait for a leftover is not.
   - Before any call the node refuses when `(keep_alive_min + 15)/60` h × the platform's price is above `ORCHAPOD_MAX_COST_USD`. 15 min (WAIT_S) is the node's wait for Running and smoke, which is counted from creation.
   - At the defaults on an L40S this is $1.16, against the old $0.78.
   - The bill is still `(now − created)/3600 + keep_alive_min/60` once the TTL is registered. I did not touch the planner's estimate (that is backend's).
2. **TTL post timeout.** `log.post("/internal/ttl", …, timeout=30)`. With the SDK's default 3 s, a slow API would make the node delete a good endpoint.
3. **judge-eval.** `STOP.clear()` is now the first line of `main()`. Test: patch in a fresh Event, `set()` it as an unwound `main()` would leave it, then run; all 4 rows are judged (with the bug, 0 are).
4. **unsloth-train GPU price.** I added a `ponytail:` note, because the executor's env carries no `<platform>/<preset>` (`_build_env` and `NebiusProvider.provision` add none), so reading it would need a platform change. The ceiling: the price comes from the CUDA device name, which cannot tell gpu-l40s-a ($1.55) from the AMD gpu-l40s-d ($1.82), and it bills any H100 or L40S at these Nebius rates. That is correct while NebiusProvider rents only its two presets.
5. **Registry comment.** The "Row keys" comment now lists `rents_gpu`: an api node that bills GPU time, such as vllm-serve's endpoint, which the budget's gpu guard counts as gpu.

## Proof
- `python -m pytest tests/containers/test_vllm_serve.py -q` → `31 passed` (18 before). The first run of the new tests, against the old code, gave `15 failed, 16 passed`.
- `python -m pytest tests/containers/test_judge_eval.py -q` → `31 passed`. The new test failed before the fix.
- `make check` (shared venv) → exit 0:
  - ruff: `All checks passed!`
  - pytest: `754 passed, 2 warnings`
  - web: `pass 27 fail 0`
  - `SKIP stub e2e: set E2E=1`
- **Mutation check** on `containers/vllm-serve/run.py`. I broke one rule at a time and restored the file each time (`cmp` against HEAD: IDENTICAL).

  | Rule broken | Result |
  | --- | --- |
  | no pre-create find | 13 failed |
  | refused create looked up | 4 failed |
  | no find in `finally` | 4 failed |
  | DELETING leftover deleted again | 1 failed |
  | no wait for the name | 4 failed |
  | name logged at INFO | 1 failed |
  | clock started after the create | 5 failed |
  | clock started before the cleanup | 3 failed |
  | TTL timeout left at 3 s | 1 failed |
  | budget without the wait | 1 failed |

- **Real client, not committed.** I ran a one-off test of the node against the real `NebiusServerless` code over an `httpx.MockTransport` Nebius (`2 passed`).
  - With a 504 create, the requests were: GET ×3 (pre-create find), POST ×1 (never re-sent), GET, then DELETE `/ai/v1/endpoints/aiendpoint-lost`.
  - With a leftover, they were: GET, DELETE `aiendpoint-old`, GET ×3, POST, GET, DELETE `aiendpoint-lost`.
  - The file was deleted afterwards.

## Open questions and notes for the Orchestrator
1. **The stricter budget check and Lane B (needs a DECISION).** At the defaults vllm-serve now needs $1.16 left. R14's Lane B (25 min of H100 = $1.875) leaves $1.125 of the $3 run cap, so vllm-serve would refuse after a full-length unsloth-train run.
   - Fix in the plan: Lane B plans set `keep_alive_min` ≤ 28. At 25: (25 + 15)/60 × 1.55 = $1.03.
   - Or: cap unsloth-train at about 24 min.
   - Intent #1 (TF fine-tune, then vllm-serve) is not affected: about $1.9 is left by then.
   - No template uses unsloth-train today.
2. **find() before every create costs about 45 s.** On the common path (nothing found), find looks 3 times (0, 15, 45 s) before the create. This is latency only: nothing bills before the create. A single `list()` look would find an earlier attempt's leftover, which has been listed for a long time by the time someone clicks retry. I kept find() as the brief says. Say if the 45 s matters for the live demo.
3. **SIGTERM mid-create within the 30 s grace.** If the endpoint shows up only on find's third look (45 s), the executor's SIGKILL at 30 s lands first. The WARN line before the create still names the endpoint, and the next attempt's pre-create find deletes it. This limit is inherent to the grace period.
4. **Name collisions** (a `ponytail:` note in the code). Canvas node ids that differ only in case or punctuation, or share their first 45 characters, get one name, so two such vllm-serve nodes in one run would delete each other's endpoint. Planner ids are snake_case (`[a-z][a-z0-9_]*`), so this does not happen for agent plans.
5. **Unbilled leftover time.** The time between an earlier attempt's exit and our delete of its leftover is billed by no one, because find's view has no `createdAt`. It is small and rare.
6. **Still open from platform-w5 (not mine, G2).** The hosted vllm-serve gets no IAM token: `NEBIUS_IAM_TOKEN` is blank on the host and its container has no CLI.

## DECISION to record
- DECISION 2026-10-21: vllm-serve names its endpoint `orchapod-<run_id[:8]>-<node_id>` (R19).
  - An endpoint found under that name before the create is deleted, unless it is already DELETING, and never adopted, because find's view has no spec and a registered one keeps its old timer. The node then waits up to 15 min for the name to be free.
  - A create that fails with `server` or `bad_output`, or is cut by SIGTERM, is found by name in `finally` and deleted.
  - Spend counts from just before the create. The pre-create check prices `(keep_alive_min + 15)/60` h.
  - Source: ml-w5.

## Fix round 1 (46469f8 docs/contracts, ff312a2 code + tests)
This round supersedes these earlier statements:
- Item 1's "`clear()` calls `endpoints.find(name)`". The pre-create check is now one `endpoints.list()` scan.
- Open question 2 (the 45 s on every create). Fixed: the normal path makes one scan.
- Open question 1 (Lane B). Ruled: Lane B plans set `keep_alive_min` 25 and R14 is amended at merge, so the default is unchanged.

**Important 1: one scan, not find().**
- `listed(eps, name)` is a `def` with a docstring: `next((e for e in eps.list() if e["name"] == name), None)`.
- `clear()` uses it for the first look (`old = listed(eps, name)`) and for the wait loop (`while listed(eps, name):`). A failed scan raises a ProviderError, and the node exits 1 with it:
  - an auth failure surfaces at once instead of after 45 s;
  - an outage in the wait loop is no longer read as a free name.
- `eps.find(name)` stays only in `finally`, for the lost create.
- Optional part taken: a 409 on the create counts like `server`/`bad_output` (`sent = … or e.status == 409`), so `finally` finds and deletes whatever holds the name. The other refusals (400, 401, 402, 429) still look nothing up.
- Contract line 223 now says "one `endpoints.list()` scan".

**Minors.**
2. **SIGTERM in `finally`.** Its first line is now `signal.signal(signal.SIGTERM, signal.SIG_IGN)`, so a cancel during the lost-create lookup cannot abort the delete; docker's 30 s still bounds it. The tests patch `vs.signal` with a mock that records into the fake's ordered `ops`, so pytest's own handler is untouched. The lost-create test pins the order: `list, create, ignore SIGTERM, find, delete`.
3. **Failed leftover delete.** It now ends in `fail(f"could not delete endpoint {old['id']} ({name}): {e}; delete it in the Nebius console")`. Tested with a 503 on the delete: exit 1, that exact line, no create.
4. **Contract overclaims.**
   - "so the create cannot 409" is dropped.
   - "a registered one still expires on its old timer" is dropped from the contract and from `clear()`'s docstring. It holds only once backend-w5's delete-by-id at expiry merges. Never-adopt rests on get() showing no spec.
   - The errors line now reads: every endpoint whose id the node knows is deleted or registered; the one that may outlive the node without an expiry is a lost create that find misses, which an ERROR line names for the console.
5. **No token in the logs.** `assert TOKEN not in str(vs.log.mock_calls)` is now in the happy-path test and the four lost-create cases.

**Proof.**
- Red first: with only `import signal` added, the updated tests gave `17 failed, 19 passed`.
- `python -m pytest tests/containers/test_vllm_serve.py tests/containers/test_judge_eval.py -q` → `67 passed`. vllm-serve has 36 tests (31 before this round). New tests:
  - the normal path makes exactly `[list, create, ignore SIGTERM]`;
  - failed scans (auth; an outage while waiting);
  - a failed leftover delete;
  - 409 in the lost-create cases.
- `make check` → exit 0: ruff `All checks passed!`, `759 passed, 2 warnings`, web `pass 27 fail 0`, `SKIP stub e2e`.
- Mutation check: I broke one rule at a time and restored the file each time (`cmp` IDENTICAL). A no-op control edit passes all 36 tests.

  | Rule broken | Result |
  | --- | --- |
  | pre-create look by find() | 17 failed |
  | wait loop by find() | 5 failed |
  | failed leftover delete not fatal | 1 failed |
  | 409 not looked up | 1 failed |
  | SIGTERM not ignored in `finally` | 13 failed |
  | SIGTERM ignored only after the lookup | 13 failed |

  The earlier round's eight rules all still fail a test:

  | Rule broken | Result |
  | --- | --- |
  | no pre-create scan | 17 failed |
  | refused create looked up | 4 failed |
  | no `finally` find | 5 failed |
  | DELETING leftover deleted again | 1 failed |
  | name at INFO | 1 failed |
  | clock from before the cleanup | 3 failed |
  | TTL timeout 3 s | 1 failed |
  | budget without the wait | 1 failed |

- **Real client, not committed.** I ran a one-off test of the node against the real `NebiusServerless` over an `httpx.MockTransport` Nebius (`2 passed`).
  - Normal path with a 504 create: GET (one scan), POST, GET (find), then DELETE `aiendpoint-lost`. Before this round the scan alone was 3 GETs.
  - With a leftover: GET, DELETE `aiendpoint-old`, GET, POST, GET, DELETE `aiendpoint-lost`.
  - The first attempt failed only because the fixture's signal mock records into `eps.ops`, which the real client lacks. With that attribute added, both cases passed. The file was then deleted.
- Cost $0. No Nebius or cloud call, and no images built.
