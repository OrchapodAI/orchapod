# platform-w7 report: Token Factory client fixes from spike 1

**Status:** DONE.

**Branch:** hack/platform-w7, in the worktree /Users/hari/src/orchapod-hack/.claude/worktrees/platform-w7.
- **Base:** 2b29844. `git merge-base --is-ancestor 2b29844 HEAD` passed.
- **Pushed:** nothing.

**Commits:**
- 38a91e5 docs(contracts): files.content follows Token Factory's 307 to object storage without the key, bounded; lora.deploy maps 410 to unsupported
- bde5e7a fix(providers): files.content follows Token Factory's 307 to presigned object storage without the key, bounded at 2 GiB and 600 s
- f3219c8 fix(providers): lora.deploy maps Token Factory's 410 to unsupported, so tf-deploy points at vllm-serve
- 2ea3c65 fix(providers): files.content retries a body cut off mid-download, as the client retries any timeout

**Cost:** $0. No key was read, and no live call was made. The tests replay the replies that spike 1 recorded.

## 1. `files.content` and the 307 (packages/providers/tokenfactory.py, base.py)

**Choice:** follow the 307. `GET /files/{id}/link` was the alternative.

**Evidence from spike 1 for that choice:**
- **Coverage.** Following the 307 covers every result file the spike saw:
  - the four small files answered 200 on `/content`;
  - the two large files answered 307 to `storage.eu-west2.nebius.cloud:443`, with a signed query;
  - followed, those two gave 200 with the listed byte counts, 41,994,968 and 17,209,920 (`content_redirects.json`, `result_files_meta.json`).
- **No key on the hop.** httpx 0.28 dropped the key on that hop: `key_sent_on_redirect: false` was measured. That httpx version is pinned in apps/api and in the tf-finetune and tf-deploy images.
- **Why not `/link`.** It returned the same bytes (`link_equals_followed: true`). However:
  - it was only measured on the two 307 files;
  - it would add a call for every file.
- **Diff size.** The route stays, so following the 307 is also the smaller change.

**Mechanism:**
- `base.request` gains `follow_redirects=False`, and only `files.content` passes True. Every other call still treats a 3xx as `bad_request`, and `test_redirect_is_not_success` still holds.
- On a cross-origin hop, httpx drops `Authorization`.

**Bounds:**
- **Size:** the body is streamed, at most `FILE_MAX_BYTES` = 2 GiB. Above that the call fails with `bad_output`.
- **Time:** `FILE_TIMEOUT_S` = 600 s for the whole file, on top of the 120 s per read. Past that the call fails with `server`.
- **Retries:** a body cut off mid-download is retried up to 3 times, within the same deadline. This is the "Errors and retries" rule; the old non-streamed read had this implicitly.
- The file is still held in memory. A `ponytail:` comment names that ceiling: spike 1's largest file was 42 MB.

**Tests (tests/providers/test_tokenfactory.py):**
- **Recorded 307:** built from `content_redirects.json`, the recorded host plus a placeholder signed query.
  - The request to `api.tokenfactory.nebius.com` carries `Bearer tf-key`.
  - The request to `storage.eu-west2.nebius.cloud` carries no `Authorization`.
- **Size:** at the 2 GiB cap passes; one byte over fails.
- **Deadline:** a slow body hits the deadline.
- **Cut-off body:** retried once, then succeeds; four cuts fail with `server`.
- **Before the fix,** the 307 test failed with `token_factory bad_request 307:`, exactly as live.

**Checked by hand (temporary test files, deleted, not committed):**
- **tf-finetune end to end:** `main()` with `file-a` behind a 307 writes the storage bytes into `lora_adapter`, and the storage host never sees `Authorization`.
- **The key assertion can fail:** a same-origin hop does keep the key, so the committed assertion distinguishes the two cases.

## 2. `lora.deploy` and 410

- **Fix:** 410 joins 400/404/405/422 as `unsupported`.
- **Test:** sends the recorded `deploy_request.json` and replays the recorded 410 body from `deploy_result.json`. It asserts kind `unsupported`, one request, and the full message: `token_factory unsupported 410: Token Factory has no per-token LoRA deploy for meta-llama/Llama-3.1-8B-Instruct (410): serve lora_adapter with vllm-serve; Token Factory said: {"detail":"LoRA adapter deployment is no longer available"}`.
- **Checked by hand:** adding 410 to ml's `test_no_per_token_lora_points_at_vllm_serve` parametrize gives 5 passed. tf-deploy exits 1 with "… — serve it with vllm-serve + lora_adapter". The file was restored, not committed.

## Verification
- `ruff check apps packages containers` → All checks passed!
- `python -m pytest tests -q` on 2ea3c65 → `869 passed, 2 warnings in 23.69s`.
- **Flake:** `tests/api/test_budget.py::test_concurrent_runs_never_grant_more_than_the_day_cap` failed in 2 earlier full runs. It is the known flake from the spike 1 report: it fails 2 of 6 runs of `pytest tests/api/test_budget.py` on an export of base 2b29844, and passed 4 of 4 alone here.

## Open, not done
- **tf_routes drops headers.** `tests/containers/conftest.py`'s `tf_routes` rebuilds each reply from status and body only, so `Location` is lost. A committed tf-finetune 307 test would need it to keep headers (ml's file).
- **https not enforced on the redirect target.** Nebius's Location is https, and a downgrade would carry no key.

## For the Orchestrator
- **DECISION:** `files.content` follows Token Factory's 307 to presigned object storage without the key, rather than calling `/files/{id}/link`. It is bounded at 2 GiB and 600 s per file, and a cut-off body is retried. See contracts 38a91e5.
- **DECISION:** `lora.deploy` maps 410 to `unsupported`. See contracts 38a91e5.

## Fix round 1 (review of 2ea3c65)

**Commits:**
- 271298a docs(contracts): files.content follows at most 3 https redirects, hides the target's error body, 512 MiB, a hard 600 s deadline
- 13323f9 fix(providers): walk redirects ourselves (https only, at most 3 hops), hide the target's error body, hard 600 s deadline, 512 MiB

**Cost:** $0, no live calls.

### Important 1: walk the redirects ourselves (base.py `request`)
- **How it sends now:** `request` sends with `follow_redirects=False` and walks `resp.next_request` inside the retry wrapper, so retries apply to every hop.
- **Each hop:**
  - It is checked against the deadline before it is sent.
  - The response before it is closed first.
  - It must be https, and at most `MAX_HOPS` = 3 hops are followed.
- **Refusals:** an http target or a 4th hop raises `ProviderError` `bad_request 307: refused redirect: https only, at most 3 hops`, which names no URL. A loop therefore no longer ends in a raw `TooManyRedirects`.
- **The key:** httpx builds `next_request` without `Authorization` off the origin, and that is kept.
- **Tests:**
  - Hop targets: `https://<api>:8443` is followed with `Authorization` None; `http://<api>` and `http://<storage>` are refused after one request.
  - TF → storage → TF: the key is on hop 0 only, so it is never regained.
  - A loop gives the refusal after 4 requests, and all four 307 responses are closed.
  - Before the fix, the two http cases and the loop were red: "DID NOT RAISE", and the replay queue ran out.

### Minors
1. **Error bodies from the redirect target are no longer echoed.** When the final `resp.url.host` is not the API host, the message is `the redirect target answered <status>`. Tested with an S3 `SignatureDoesNotMatch` body that carries `<SignatureProvided>`: it was echoed before the fix.
2. **httpx logging:** `logging.getLogger("httpx").setLevel(logging.WARNING)` in base.py.
3. **Hard deadline.**
   - **Checks:** `request(deadline=…)` checks before every send (hops and retries) and before every backoff. `files.content` passes the deadline through and also checks it before its own mid-body retry.
   - **Overrun:** at most one connect + read timeout, 130 s, as the contract line now says.
   - **Test:** a read that times out past the deadline gives no backoff and no second send; a 307 that lands past the deadline gives no hop.
4. **Memory:** `FILE_MAX_BYTES` is now 512 MiB, about 12× the 42 MB adapter.
5. **Size test:** a 1,000-chunk stream with a 4-byte cap stops after 3 chunks.
6. **Polish:**
   - `request`'s docstring states the GET-only assumption: on a 307, httpx re-sends the body and every header but `Authorization`.
   - `base.backoff()` is shared by `request` and `files.content`.

### Verification
- **Provider tests:** `pytest tests/providers` → 202 passed. With tf-finetune and tf-deploy's container tests → 242 passed.
- **tf-finetune end to end (temporary, deleted):** re-run through a 307 on 13323f9 → passed.
- **`make check PY=python` (shared venv) on 13323f9 → rc=0:** `All checks passed!`, `876 passed, 2 warnings`, web `pass 30` / `fail 0`, `SKIP stub e2e`.
- **Flakes:** two other `make check` runs failed only on known flakes that also fail on base 2b29844, under a load average of about 8:
  - `tests/api/test_budget.py::test_concurrent_runs_never_grant_more_than_the_day_cap` (2 of 6 on the base);
  - two cases of `tests/api/test_executor.py::test_an_endpoint_node_without_a_token_fails_before_it_starts`. Its fake `nebius` CLI must finish within `IAM_TIMEOUT_S` = 0.2 s, and run back to back with head it failed 1 of 4 on the base. For qa/backend.

### DECISION, superseding the 2 GiB line above
`files.content` follows at most 3 redirects, https only, never with the key. It reports a redirect target's error by status only. It is bounded at 512 MiB and 600 s, where the deadline is checked before every send and after every chunk. See contracts 271298a.
