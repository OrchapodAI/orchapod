# Wave 2 report: platform-w2 (2026-10-21)

**Status:** DONE. Every item in the platform-w2 brief is done, plus the Orchestrator's P0 add-on (no silent vast.ai). `make check` is green.
**Branch:** `hack/platform-w2`. The base check `git merge-base --is-ancestor c75c119 HEAD` passes.
**Commits (in order):**
- `61aca1b` fix(providers): LocalDocker never loses an exit code
- `76a7f7d` fix(providers): a gpu node lands on vast.ai only when provider_pref names it
- `34779db` docs(contracts): chat read_timeout, padded-key pairing, unreadable 2xx is bad_output (contract edit in its own commit)
- `650ce2e` feat(providers): per-call read_timeout; padded keys refused; unreadable 2xx is bad_output
- `50d0173` fix(infra): compose api on 8001 with exactly the contract's Config variables
- `e169cce` test(api): default resources never provision on vast.ai; delete the dead YC seed script (Orchestrator follow-up, below)
- `fa519f1` fix(providers): pre-merge review fixes for platform-w2 (section "Pre-merge fixes", below)

**Cost:** $0. No live calls were made and no keys were used.

## Proof
- `make check` (worktree root, shared venv) at `e169cce`: ruff clean; `317 passed, 67 warnings` (the base had 294 passed and 66 warnings); stub e2e SKIP (qa's script is not there yet); exit 0.
  - The one extra warning is SQLModel's `session.execute` deprecation from the executor's own `db.scalars` (run_workflow.py:93, backend's code). Every executor-level test triggers it; my own test line uses `db.exec`.
- gitleaks over `c75c119..HEAD`: no leaks found.
- No throwaway containers or images were left behind. `docker ps -a --filter ancestor=orchapod-test/exit1:latest` and `docker images orchapod-test/exit1` are both empty. I touched no other container.

## What was done
### 1. LocalDocker fast-fail race (P0): `packages/providers/local_docker.py`
- **Root cause:** `docker run -d --rm` auto-removed a container that exited at once. `docker wait` then answered "No such container", and `wait()` mapped that to exit 0, so the node read as succeeded.
- **Fix:**
  - `provision` no longer passes `--rm`.
  - `wait` raises `ProvisionError("docker wait failed: …")` when `docker wait` fails. It never assumes success. The executor reports this as the node error `internal: docker wait failed: …`.
  - `terminate` (`docker stop -t 30`, then `docker rm -f`) removes the exited container. The executor already runs it in its `finally` after `wait`.
- **Test:** `tests/providers/test_local_docker.py::test_a_container_that_fails_at_once_keeps_its_exit_code_until_terminate`.
  - Real docker. It builds a throwaway image (`FROM alpine:latest`, `CMD ["false"]`) from the local alpine; BuildKit resolves the local digest, so nothing is pulled.
  - It provisions through the provider, then sleeps 1 s, standing in for the executor's DB commit and log-stream start before it waits.
  - It asserts that `wait() == 1` and that the container is gone after `terminate`.
  - Without the sleep, `docker wait` won the race 5/5 on this Mac. With the sleep, the old code fails 5/5 with `assert 0 == 1`, and the fix passes every run.
  - The test skips when no docker daemon is running. CI's ubuntu runner has one; there it pulls alpine.
  - It adds about 3–4 s to `make check`.
- **Extra evidence (not committed):**
  - A temporary tests/api test ran the real executor with the real LocalDocker on that image: run `failed`, node `failed`, error `exit 1`, container removed afterwards.
  - On SQLite the old code also passed that test: the commit is too fast to open the race window, which a Postgres commit would open. The provider test is the regression guard.
  - Timing probe: a container running `echo boom; exit 3` gives code 3, the log stream gets `['boom']`, and the drain takes 0.00 s. A fast-failing node's last stdout now reaches the UI; with `--rm` it could be lost.
- **Doc:** docs/NODE_CONTRACT.md, "Local runs" paragraph.

### 2. Provider selection, P0 add-on (no silent vast.ai): `apps/api/services/provider_selector.py`, `packages/workflow_schema/models.py`
- **Root cause:**
  - `ResourceSpec.provider_pref` defaulted to `["nebius", "vastai"]`.
  - `pick_provider` fell back to `["runpod", "vastai"]`.
  - nebius was registered only when `NEBIUS_IAM_TOKEN` was set.
  - So with `VASTAI_API_KEY` set and Nebius not configured, a gpu node asked vast.ai for a GPU.
- **Fix:**
  - The default and the fallback are now `["nebius"]`, so vastai is used only when the node's `provider_pref` names it.
  - nebius is registered when `NEBIUS_PROJECT_ID` is set, per contracts "provider selection".
  - The dead RunPod import and registration are deleted (the module never existed).
  - Node error without Nebius: `no gpu provider: none of ['nebius'] is configured with 1xH100 capacity (nebius needs NEBIUS_PROJECT_ID)`.
- **Test:** `tests/providers/test_provider_selector.py`.
  - Setup: `VASTAI_API_KEY` set, `NEBIUS_PROJECT_ID` and `NEBIUS_IAM_TOKEN` unset, and vast.ai's quote faked to say "available" (the step right before provision).
  - `ResourceSpec()`, `provider_pref=[]` and `None` each raise `NoCapacity` naming NEBIUS_PROJECT_ID, and vast.ai is never asked.
  - An explicit `["nebius", "vastai"]` still reaches vastai.
  - On the old code the test fails with "DID NOT RAISE".
- **Doc:** docs/WORKFLOW_SPEC.md (the `provider_pref` example line), plus the ResourceSpec field description.
- **Scope note:** these two files were outside my usual paths; the Orchestrator assigned them by message. In models.py I touched only `ResourceSpec`, no NODE_REGISTRY block.
- **Still explicit, as intended:** `apps/api/routes/inference.py` writes `provider_pref: vastai` into its generated YAML (the hidden Vast.ai stack).
- `scripts/seed-demo-workflow.py`, which named `["runpod", "vastai"]` in two nodes, is deleted in `e169cce` (see the follow-up below).
- **Known limit:** with `NEBIUS_PROJECT_ID` set, the registered `NebiusProvider` is still the legacy Compute one, which needs `NEBIUS_FOLDER_ID` (removed from config). gpu nodes therefore fail with `provision failed: NEBIUS_FOLDER_ID is not set …` until the Serverless rewrite (board P1) lands. That path cannot spend money.

### 3. Token Factory and Tavily clients: `packages/providers/{base,tokenfactory,tavily}.py`
- **`read_timeout`:** an explicit keyword on `chat` and `stream_chat`, through `_prepare`. It sets the request's read timeout for that call only (`httpx.Timeout(read_timeout, connect=10)`); `None` keeps the client's 120 s. It never reaches the JSON body.
  - backend-w2 asked for exactly this shape by message, so I sent no reply. Their planner tests strip the kwarg until this merges.
- **Key pairing after `.strip()`:**
  - The client key is stripped once at construction; the ModelRef key and `NEBIUS_API_KEY` are stripped at comparison.
  - A padded copy of the Token Factory key is refused for another base_url. The stripped key is also what goes into the header.
- **Non-transport failures → `ProviderError` kind `bad_output`, never retried:**
  - `base.request`: `httpx.DecodingError` (an unreadable body on a 2xx reply) → `bad_output`. It is not a TransportError, so before this it escaped raw.
  - New `base.json_of(resp, provider)`: a 2xx reply that is not a JSON object → `bad_output`.
    - It is used by `chat`, by every JSON read in `TokenFactory._call` (new `raw=True` for `files.content` and `lora.delete`, whose bodies are not JSON) and by `Tavily._post`.
  - `stream_chat`: a malformed chunk (not JSON, not an object, or a DecodingError mid-stream) → `bad_output`. Transport errors mid-stream stay `server`.
- **Tests:**
  - `test_tokenfactory.py`:
    - `test_token_factory_key_refused_off_token_factory_even_padded`: chat and stream_chat × 4 key cases. This includes the stream_chat key-refusal test the review asked for. Each strip is isolated by its own case.
    - `test_read_timeout_is_per_call_and_not_in_the_body`.
    - `test_a_2xx_reply_that_cannot_be_read_is_bad_output_not_retried`: not JSON / not an object / undecodable × `chat` and `fine_tuning.get`.
    - `test_malformed_stream_chunk_is_bad_output`: 3 shapes.
  - `test_tavily.py`: `test_a_2xx_reply_that_is_not_json_is_bad_output_not_retried`, which also checks that nothing is billed.
  - All of these fail on the old code, except the two unpadded key cases, which add the missing stream_chat coverage.
- **Mutation check:** I removed each of the 10 new guards one at a time: init strip, ref strip, env strip, read_timeout, the stream DecodingError, the stream wrong-shape, `_call` json_of, chat json_of, the JSON-object check, and request's DecodingError. The suite caught all 10.
- **Doc:** docs/contracts.md, in its own commit `34779db`, 3 lines: the chat signature plus a `read_timeout` sub-bullet; "compared after `.strip()`" in the pairing rule; a "2xx that cannot be read → bad_output" line under Errors and retries.

### 4. `infra/docker-compose.dev.yml`
- api publishes `8001:8000`. Dropped: `ANTHROPIC_API_KEY`, `JUDGE_MODEL` (the 253B judge), `NEBIUS_FOLDER_ID`, `NEBIUS_SUBNET_ID` and `CLOUDFLARE_TUNNEL_TOKEN`; all are on the contract's removed list.
- The api now gets exactly the contract's 28 Config variables, with the contract defaults. Storage, database and redis point at the compose services; MinIO's region is `auto`.
- The web service points at `http://localhost:8001` / `ws://localhost:8001`.
- The obsolete `version:` key is gone; it printed a warning on every compose command, `make up` included.
- The header now lists `make up` and the three demo keys.
- **Test:** `tests/providers/test_env_example.py::test_compose_api_gets_the_contract_config_on_8001`. It checks the api ports, that the api's variables equal `.env.example`'s, the web URL, and that no removed name or "253B" appears.
- **Validation:** `env -i PATH="$PATH" HOME="$HOME" docker compose -p orchapod-hack-validate -f infra/docker-compose.dev.yml config --quiet` exits 0. It runs with an empty environment, so no secret is interpolated, and I printed only the structure: api ports `[('8001', 8000)]`, 28 env vars, web `http://localhost:8001`. Nothing was started.
- **Doc:** the compose header. contracts "Config" already says 8001.

## Orchestrator follow-up: "the default still names vastai"
- **On hack/platform-w2 the default was already `[\"nebius\"]`.** `76a7f7d` changed it, and that commit is only on this branch.
  - ml-w2 read the unmerged base: every other worktree (orchapod-hack, backend-w2, data-w2, devrel-w2, ml-w2, qa-w2) still shows `["nebius", "vastai"]`. They pick up the fix when this branch merges.
- **The original test already guarded it.** I reverted only that default line and `tests/providers/test_provider_selector.py` failed: "DID NOT RAISE NoCapacity".
- **New end-to-end test:** `tests/api/test_provider_selection.py::test_default_resources_never_provision_on_vastai_without_nebius` (`e169cce`).
  - It runs the real executor on an `unsloth-train` node with no `resources` (so `ResourceSpec()` defaults), with `VASTAI_API_KEY` set and `NEBIUS_PROJECT_ID` / `NEBIUS_IAM_TOKEN` unset. vast.ai's quote and provision are faked and recorded.
  - It asserts that vast.ai is never quoted or provisioned, and that the node error is exactly `no gpu provider: none of ['nebius'] is configured with 1xH100 capacity (nebius needs NEBIUS_PROJECT_ID)`.
  - The fix passes it. With only the default reverted, and on the base code (c75c119 default and selector), it fails with `assert ['quote', 'provision'] == []`: vast.ai is quoted and then provisioned, which is the hole ml-w2 saw.
- **`scripts/seed-demo-workflow.py` is deleted.**
  - It is the old YC demo: Qwen, `provider_pref ["runpod", "vastai"]` on two gpu nodes.
  - It POSTs to `/api/workflows`, but the API mounts `/workflows`, and it targets `http://localhost:8000`, which is complychip2 on this Mac. It could not seed anything, and nothing references it.
  - The ponytail audit (item 12) already lists it for deletion, with platform as a co-owner. If you would rather keep it, revert the deletion in `e169cce`; I would then switch its two `provider_pref` lines to nebius.
- **Other explicit names left, as intended:** `apps/api/routes/inference.py` writes `provider_pref: vastai` into its generated YAML. That is the hidden Vast.ai stack, which frontend-w2 took out of navigation. No `vastai` remains in `scripts/` or the agent templates.

## Not done / open
- `apps/api/config.py`: deferred to wave 3 by the brief (R18 stands).
- The `tests/providers/conftest.py` workaround (lines 11–15) stays until ml-w2's `sys.modules` fix merges. It is a 5-line deletion after that; tell me, or delete it at merge.
- Wrong-shaped JSON objects in non-stream replies still raise `KeyError`. Examples: a chat choice without `message`, or `events` without `data`. Non-objects are now `bad_output`. This is unlikely from an OpenAI-compatible API; say if you want it covered too.
- Pre-existing, not on the demo path: the compose `api` service cannot run nodes. Its image has no docker CLI or socket, and node containers could not resolve `api:8000` / `minio:9000`. `make up` starts only postgres, redis and minio; on this Mac the API runs from the venv on 8002.
- Pre-existing, outside the gate: `ruff check tests` reports one F841 at `tests/providers/test_vastai.py:181`. `make check` lints `apps packages containers` only.

## For the Orchestrator to record
- DECISION: gpu nodes default to `provider_pref ["nebius"]`. vastai runs only when a node's `provider_pref` names it. nebius registers on `NEBIUS_PROJECT_ID`.
- DECISION: LocalDocker containers run without `--rm`. An exit code that cannot be read fails the node (`internal: docker wait failed: …`); `terminate` removes the container.
- DECISION: every Token Factory and Tavily JSON reply must be a JSON object, else `bad_output`, never retried. `httpx.DecodingError` and malformed stream chunks are also `bad_output`.
- Contract edit `34779db` (3 lines) is ready to merge with the branch.

## Merge notes
- `packages/workflow_schema/models.py`: my hunk is only the `ResourceSpec` field (about lines 63–68). Wave-2 node blocks elsewhere in the file should not overlap.
- `docs/contracts.md`: additive lines in the TokenFactory and "Errors and retries" sections.
- backend-w2's `chat(..., read_timeout=300)` works once this merges.

## Pre-merge fixes (`fa519f1`, after the approving review)
1. **Unreadable exit code:** regression test `test_an_unreadable_exit_code_fails_instead_of_reading_as_success`.
   - A fake `create_subprocess_exec` returns returncode 1 with stderr "No such container", and the test expects `pytest.raises(ProvisionError, match="docker wait failed")`.
   - I re-added the old "No such container → 0" mapping and the test failed: "DID NOT RAISE ProvisionError".
2. **Dead second `pick_provider`:** deleted from `packages/providers/vastai.py`. It had no callers and defaulted to `["vastai"]`. `PROVIDERS` and `register_providers` stay; main.py and internal.py still use them.
3. **`scripts/seed-demo-workflow.py`:** already deleted in `e169cce`.
4. **`read_timeout` sets read only:** `httpx.Timeout(120.0, connect=10.0, read=read_timeout)`; `None` still means the client default.
   - The test now pins the whole timeout: `{"connect": 10, "read": 300, "write": 120, "pool": 120}`. It failed before the change, with write and pool at 300.
5. **`test_local_docker.py` hygiene:** provision now runs inside the `try`; `terminate` runs only if a pod exists, and the image is always removed. A `CalledProcessError` from the image build calls `pytest.skip` with the build's last stderr.
6. **`get_cost_estimate`** quotes only the configured providers in the node's `provider_pref` (default `["nebius"]`). The UI never shows a vast.ai price for a node that cannot run there.
   - Test: `test_cost_estimate_prices_only_providers_the_node_may_use`. A default `ResourceSpec` gives `[]` and vast.ai is never asked; an explicit `["nebius", "vastai"]` gives the vastai quote. It failed before the change.
   - The two selector tests now share one `asked` fixture.
- **Covering tests:** `pytest tests/providers tests/api/test_provider_selection.py` → 105 passed.
- **`make check` at `fa519f1`:** ruff clean; `319 passed, 67 warnings`; stub e2e SKIP; exit 0. No throwaway containers or images left.
