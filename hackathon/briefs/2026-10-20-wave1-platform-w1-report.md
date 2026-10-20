# Wave 1 report: platform-w1 (2026-10-20)

**Status:** DONE_WITH_CONCERNS. All of the brief is done and `make check` is green. The concerns are decisions to record and issues in files I don't own.
**Branch:** `hack/platform-w1`. Base check `git merge-base --is-ancestor 178d2e6 HEAD` passes.
**Commits:** `524aa4d` (clients, PRICES, deletion), `e609293` (LocalDocker, .env.example), `be19354` (mid-stream errors raise ProviderError).
**Cost:** $0. No live calls were made and no keys were used.

## What was done
### 1. Token Factory and Tavily clients (contracts "Provider interfaces")
- `packages/providers/base.py` adds:
  - `ProviderError(provider, kind, status, message)`; `str()` is `"<provider> <kind> <status>: <message>"`.
  - `request()`, which applies the contract's retry policy:
    - Up to 3 retries on 429 (waits Retry-After, capped at 60 s), on 500/502/503/504, and on timeouts and connection errors. Backoff is 1, 2, 4 s plus up to 1 s of jitter.
    - Creates retry only on 429 and connect errors, never after a 5xx or a read timeout.
    - 400/404/409/422 → `bad_request`; 401/403 → `auth`; 402/432/433 → `quota`.
  - `http_client()`: timeouts of 10 s to connect and 120 s to read. Under `STUB=1` it is an in-process `httpx.MockTransport`.
  - `stub_hash()`: the first 8 hex of the request's sha256, with the random multipart boundary removed so uploads hash stably.
- `packages/providers/tokenfactory.py`:
  - Model constants: `SUPER`, `ULTRA`, `LIGHTNING`, `NANO`.
  - `chat`:
    - `json_schema` → strict `response_format`, and the reply comes back as `parsed`.
    - Invalid JSON raises `bad_output`, naming finish_reason. It is never retried, and the tokens are still billed.
    - `thinking` → `chat_template_kwargs`; any other `**params` go into the request body as given.
  - `stream_chat`: sends `include_usage`, retries only before the first chunk, and bills after the last chunk.
  - `files.create/get/content`.
  - `fine_tuning.create/get/events/checkpoints/best_checkpoint/cancel/list`.
  - `lora.deploy/status/delete`. A 400/404/405/422 from deploy → kind `unsupported`, with the contract's message.
  - ModelRef targets: a call to a URL other than Token Factory costs $0 and skips on_usage.
  - The Token Factory key is never sent to another URL (kind `auth`, nothing is sent).
  - A missing key → `auth`, and a missing price → `bad_request`. Both are raised before sending.
- `packages/providers/tavily.py`:
  - `search` and `extract`. Extract sends more than 20 URLs in batches of 20 and merges the results.
  - Both send `include_usage: true` and call `on_usage("tavily", "search"|"extract", credits=…, usd=credits × 0.008)`.
- STUB=1: deterministic offline fakes that return the real response shapes, so nodes run their normal code path.
  - chat: `stub-<h>`, or a minimal instance of the schema.
  - Fine-tuning: jobs succeed at once with two checkpoints (valid_loss 1.0, then 0.5); LoRA status is `active`.
  - Tavily: unique pages of at least 400 characters.
- `packages/sdk-py/orchapod/prices.py`: the single PRICES table (R16). Only Super, Ultra and Lightning are priced; everything else is absent, so lookups fail closed.
- Deleted `apps/api/services/nebius_token_factory.py`. Proof that nothing imports it:
  ```
  $ git grep -nE "(import|from) [a-z_.]*nebius_token_factory|nebius_token_factory import" -- "*.py"
  apps/api/services/nebius_token_factory.py:17:  from api.services.nebius_token_factory import token_factory   ← its own docstring
  $ git grep -n "nebius_token_factory" -- "*.py" ":!apps/api/services/nebius_token_factory.py"
  apps/api/routes/models.py:36,48,60: "nebius_token_factory_id": ...   ← a dict key, not an import
  ```

### 2. LocalDocker and .env.example
- `local_docker.py`:
  - Image: runs `orchapod/<type>:dev` if it is built locally. Otherwise it runs `${ORCHAPOD_IMAGE_PREFIX:-ghcr.io/bangadpurva}/<type>:latest` and docker pulls it; before, a missing local image raised `ProvisionError`.
  - Terminate: `docker stop -t 30`, then `docker rm -f`.
- `.env.example`:
  - Holds exactly the contracts "Config" list, with the contract defaults and where to get each value.
  - Adds R7's `ORCHAPOD_ADMIN_TOKEN`.
  - Drops ANTHROPIC/OPENAI/JUDGE_MODEL/NEBIUS_FOLDER_ID/NEBIUS_SUBNET_ID/GITHUB_ORG/CLOUDFLARE_TUNNEL_TOKEN, plus the Clerk vars (not in the Config list, and no code reads them).
  - A test checks that the file's variables and values match the contract list exactly, and that none of the removed names appear.
- Doc lines: docs/NODE_CONTRACT.md gains "Calling Token Factory and Tavily" and a note on local image resolution and the cancel grace period. README is untouched because devrel is rewriting it.

## Proof
- `make check` (venv activated): ruff is clean; `195 passed, 58 warnings`; the stub e2e is skipped because qa's `scripts/e2e_demo.py` doesn't exist yet. The baseline was 153 passed with 58 warnings, so this adds 42 tests and no new warnings.
- `python -m pytest tests/providers -q`: `64 passed` (my 42 plus the 22 existing vastai tests).
- Tests replay recorded responses through `httpx.MockTransport`. They cover:
  - 429 with Retry-After, including the 60 s cap.
  - 5xx retried 3 times with 1/2/4 s backoff.
  - Creates not retried after a 5xx or a read timeout, but retried on 429 or a connect error.
  - The non-retried 4xx mapping.
  - The pairing refusal.
  - `json_schema` → `parsed`, and `bad_output`.
  - Unpriced chat and fine-tune calls refused before sending.
  - A missing key.
  - LoRA deploy success and `unsupported`.
  - `best_checkpoint`.
  - Streaming, including a stream that breaks mid-way.
  - Tavily batching and credits.
  - STUB determinism for both clients.
- Mutation check: I removed each of 12 guards one at a time (create no-retry ×2, the Retry-After cap, the boundary strip, Tavily quota, the pairing check, the chat and fine-tune price checks, the `unsupported` mapping, bill-before-parse, best-by-valid_loss, batch size). The tests caught all 12.
- Real Docker check (local images only, nothing pulled):
  - `resolve data-prep -> orchapod/data-prep:dev` and `resolve web-research -> ghcr.io/bangadpurva/web-research:latest`.
  - Terminate on a container whose SIGTERM handler needs 2 s took 2.2 s (SIGKILL would take about 0 s), and the container was gone afterwards.

## DECISIONs for the Orchestrator to record
1. **PRICES shape (agreed with backend-w1 by message):**
   - `token_factory {model: {"in","out"}}` in $ per 1M tokens.
   - `token_factory_finetune {base_model: $ per trained token}`, empty until spike 1.
   - `tavily {"credit": 0.008}`.
   - `nebius_serverless {platform: $ per GPU-hour}`.
   - The clients always pass `usd=` to on_usage, so `cost.add`'s `usd=None` path is only used when a node calls it directly.
2. **`fine_tuning.create` fails closed** (`bad_request`, nothing sent) when there is no fine-tune price for the model (R5). Spike 1 must add the per-token rate before a real tf-finetune run.
3. **Under STUB=1 the key and price checks are skipped**, because nothing is sent or spent. This lets stub runs use unpriced models such as Llama before spike 1. The key↔URL refusal still applies. Stub calls report on_usage with 0 tokens and $0, so the cost_json plumbing still runs.
4. **Contract addition: `files.get(file_id) -> dict`** (GET /v1/files/{id}). In TF's documented download flow, each checkpoint `result_files` id needs its `filename` to rebuild the PEFT directory (tf-finetune).
5. **Stub details:**
   - `chat` with `json_schema` returns `text` = the JSON of the minimal instance, so `parsed == json.loads(text)` still holds.
   - Tavily `extract` stub pages keep the requested URL. Search hits are at `https://example.com/stub/<h>/<i>`.
6. **`lora.deploy` returns the response's `name`.** Nebius docs show a served name that differs from the requested one. This is unverified until spike 1. The `unsupported` message appends TF's own error text.
7. **LocalDocker builds the fallback ref from `ORCHAPOD_IMAGE_PREFIX`**, so it is correct both before and after backend's executor change.
8. **A blank env var means the default** for `NEBIUS_BASE_URL` and `ORCHAPOD_IMAGE_PREFIX`. `.env.example` ships blanks, so I told backend-w1 to read `ORCHAPOD_INTERNAL_SECRET` as `os.environ.get(...) or secrets.token_hex(32)`; otherwise an empty secret would leave /internal open.

## Concerns and follow-ups (not in my brief)
- **Test isolation (ml or qa):**
  - `tests/containers/test_unsloth_train.py` puts a fake, non-package `orchapod` into `sys.modules` at import time, along with fakes for transformers, unsloth, trl and datasets. It never restores the originals.
  - Any later test module that imports a real `orchapod.*` submodule then fails with "'orchapod' is not a package". Backend's `orchapod.cost` tests will hit this if they are collected after tests/containers.
  - I worked around it in `tests/providers/conftest.py`. The real fix is to scope those fakes with `monkeypatch.setitem(sys.modules, …)` or a fixture.
- **LocalDocker `--rm` race (existing bug):** if a container exits and is auto-removed before `docker wait` attaches, `wait()` returns 0 ("assuming success"). A node that fails fast could therefore show as succeeded. Fix: drop `--rm` once the executor calls `terminate` on every path (backend-w1 is reworking that path), since terminate now always runs `docker rm -f`.
- **API image:** `apps/api/Dockerfile.dev` sets `PYTHONPATH=/app`. Once the API imports the clients (wave 2), it also needs `/app/packages/sdk-py` on the path for `orchapod.prices`.
- **Stale references:**
  - `scripts/build-and-push-containers.sh` still reads `GITHUB_ORG` (default `orchapod`) instead of `ORCHAPOD_IMAGE_PREFIX`.
  - `infra/docker-compose.dev.yml` still passes NEBIUS_FOLDER_ID/SUBNET_ID, JUDGE_MODEL (with the stale Ultra-253B id), ANTHROPIC_API_KEY and CLOUDFLARE_TUNNEL_TOKEN, and publishes the api on port 8000 (the contract says 8001). This belongs with platform's wave-2 config.py work.
  - README.md:220 still lists the deleted file (devrel).
- **The recorded responses are hand-written** from TF's OpenAI-compatible shapes, the Nebius docs and the Tavily docs, because no keys are set yet. Spikes 1–3 should swap in real captures: the TF job and checkpoint JSON, the `/v0/models` response, and whether Tavily returns `usage.credits`.
- **Known limits, kept small on purpose:**
  - events, checkpoints and list read only the first page, which is enough for jobs of 3 epochs or fewer.
  - A stream abandoned before its last chunk records no usage (marked `ponytail:` in the code).

## Coordination
I sent two messages to backend-w1: agreement on the PRICES shape, and the "blank `ORCHAPOD_INTERNAL_SECRET` = unset" warning.

## Fix round 1 (commit `e416890`)
### What changed
1. **Create rule tested at every call site.** The two create tests are now parametrized over `files.create`, `fine_tuning.create` and `lora.deploy`.
   - The no-retry test covers a 5xx, a read timeout and a dropped connection.
   - The retry test covers 429, ConnectError and ConnectTimeout.
   - Mutation check: dropping `create=True` at any one call site fails 3 tests (`CAUGHT` for each of the three sites).
2. **ModelRef keys (load-bearing).** `_prepare` now uses `key = api_key if base_url else self.api_key`.
   - When a ModelRef passes no key (`None` or `""`), the request goes out with no Authorization header. This fixes judge-eval's llama-server (`api_key_env ""`) and refs whose env var is unset.
   - The key↔URL refusal still holds: `api_key=<NEBIUS_API_KEY>` with another URL → `auth`, and nothing is sent.
   - The key-refusal test's `{}` case now asserts that no Authorization header was sent, and a `""` case was added.
3. **STUB=1 always uses the stub transport**, even when an `http` client is injected, in both clients. Both stub tests now assert that the injected client saw no requests.
4. **`base.request` error handling:**
   - Only 2xx counts as success (`resp.is_success`), so a 307 is now `bad_request 307` and is not retried.
   - The two exception branches are now one `except httpx.TransportError`. For a create it re-raises unless the error is ConnectError or ConnectTimeout.
   - The error-body `resp.read()` moved inside the `try`, so no raw httpx exception escapes.
   - New tests: a ProxyError is retried 3 times and then raised as ProviderError `server`; a redirect is not success.
5. **Billing order.** `chat` bills from `usage` before it reads `choices[0]`. A reply with no choices → `bad_output`, after billing. A new test covers this.
6. **Tavily without `usage`** is billed by the contract rule instead of $0: search costs 1 credit (basic) or 2 (advanced); extract costs the same per 5 successful URLs, and failed URLs are free. A new test is parametrized over all four cases.

Optional cuts, all applied:
- A `_Part` base class replaces the three identical `__init__(self, tf)` methods.
- The stub's `raw_content` loop is folded into the comprehension.
- One shared `recorder` fixture now lives in tests/providers/conftest.py, and the new `train` fixture is reused in two tests.

I did not touch the conftest `sys.modules` workaround.

### Tests run
- RED before the fix: 10 failures, each for the intended reason:
  - a raw `httpx.ProxyError`
  - a `JSONDecodeError` on the 307
  - the `auth` refusal of a ModelRef with no key
  - `credits 0` ×4
  - `IndexError` on `choices[0]`
  - stubs using the injected client ×2
- `python -m pytest tests/providers -q`: `80 passed` (was 64). Ruff is clean on packages/providers and the new tests.
- `make check`: lint clean; `211 passed, 58 warnings` (was 195 passed, 58 warnings); the stub e2e is still skipped because qa's script doesn't exist yet.
