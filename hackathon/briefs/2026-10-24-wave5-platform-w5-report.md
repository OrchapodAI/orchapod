# platform-w5 report — NebiusServerless + NebiusProvider on Jobs (wave 5, items 1–2 + the orchestrator's list() addition)

## For ml-w4 first: signatures
The contract signatures are unchanged: `NebiusServerless().endpoints.create(name, image, *, args="", env, platform, preset, port=8000, auth_token, volumes=())` returns the id, plus `.get(id)` and `.delete(id)`; the same holds for jobs. Three additions, all backward compatible:
- `jobs.list()` and `endpoints.list()` are new (orchestrator, mid-task).
- `get()` and `list()` share one view, `{id, name, state, url, code, message}`, so `jobs.get` returns two keys more than the contract's `{id, state, code, message}`.
- A blank `auth_token` raises `bad_request` before any call, because Nebius would otherwise serve the endpoint without authentication.

`delete` treats a 404 as done.

## Status
DONE on branch `hack/platform-w5` (base 23b0a57):
- c45b4b2 docs(contracts): NebiusServerless adds jobs.list/endpoints.list and recovery by metadata.name; NebiusProvider guards
- 90ac230 docs(contracts): endpoints.create refuses a blank auth_token
- 673ef77 feat(providers): NebiusServerless (Jobs, Endpoints) over REST ai/v1 and NebiusProvider on Jobs

Files:
- packages/providers/nebius.py: full rewrite. The legacy Compute code and the api.studio.nebius.ai constant are gone, and so are the NEBIUS_FOLDER_ID and NEBIUS_SUBNET_ID reads.
- tests/providers/test_nebius.py: new, 27 tests.
- tests/providers/test_prices.py: the quote tests now follow the 1×H100/1×L40S mapping.
- tests/providers/test_env_example.py: the two legacy allow-list entries are removed. Its stale-entry check would fail if any code still read them.
- docs/contracts.md: the NebiusServerless section only.

## Proof
- `pytest tests/providers/test_nebius.py -q` → `27 passed in 0.45s`
- `make check` → exit 0: `All checks passed!` (ruff on apps/packages/containers), `729 passed, 2 warnings`, web `pass 27 fail 0`, `SKIP stub e2e: set E2E=1`.
- Mutation check. I broke each rule in turn and checked that a test fails:

  | Rule broken | Result |
  | --- | --- |
  | create=False on creates | 3 failed |
  | 401 renewal disabled | 1 failed |
  | newest-first sort removed | 1 failed |
  | adopt-by-name disabled | 1 failed |
  | 404 delete treated as an error | 1 failed |
  | blank auth_token accepted | 1 failed |

  After each, the file was restored and compared byte for byte (`cmp` IDENTICAL).
- The tests run on faked replies in the documented shapes, through the existing `replay` fixture on httpx.MockTransport. The CLI fallback runs a fake `nebius` script on PATH, so the real subprocess path is exercised. The STUB test patches `httpx.HTTPTransport.handle_request` to raise, which proves STUB makes no network call.

## What the code does
- **REST.** Base `https://api.nebius.cloud/ai/v1`, parent `NEBIUS_PROJECT_ID`, `Authorization: Bearer <IAM token>`.
- **Jobs.** `POST /jobs` → id from the Operation's `resourceId`. `GET /jobs/{id}`. `GET /jobs?parentId=` (paged). `POST /jobs/cancel {"id"}`. `DELETE /jobs/{id}`.
- **Endpoints.** The same routes under `/endpoints`, with no cancel.
- **Create body.**
  - `metadata {parentId, name}`.
  - `spec`: `image`, `args`, `environmentVariables [{name, value}]` (blank values are not sent), `platform`, `preset`, `disk {type: NETWORK_SSD, sizeBytes: 250 GiB}`, `shmSizeBytes: 16 GiB` and `volumes`.
  - Jobs add `timeout: "3600s"`. Endpoints add `ports [{containerPort, protocol: HTTP}]` and `authToken`.
  - Volumes accept only `s3://<bucket>:<container_path>:ro|rw` and map to `{source: "s3://<bucket>", containerPath, mode: READ_ONLY|READ_WRITE, s3Config {endpoint, region, credentials {accessKeyId, secretAccessKey}}}`, with s3Config from ORCHAPOD_R2_*.
- **Auth.** `NEBIUS_IAM_TOKEN`. When it is empty, or a call gets a 401, the client runs `nebius iam get-access-token` (60 s timeout) once for that call and sends it again. A 401 is refused before anything runs, so even a create may be re-sent. A second 401 raises `auth`. With no CLI on PATH it raises `auth` before any request is sent, with the message "NEBIUS_IAM_TOKEN is empty or expired and the nebius CLI is not installed to renew it". The token is never logged or put in an error.
- **Retries.** These use the shared `base.request`. A create goes again only after a 429 or a connect error (and after the 401 renewal above). A 5xx, read timeout or dropped connection raises at once. A reply without `resourceId` raises `bad_output`, and the error never echoes the Operation, whose `request` may carry env values.
- **list().** Pages with `pageToken`/`nextPageToken` until the end. Sorts newest first by parsed `metadata.createdAt`, because the List call has no order, and a string sort is wrong within a second ("…07.500Z" vs "…07Z").
- **Recovery by name (R19-style).** It matches `metadata.name`, which is unique per project and kind: both services have GetByName, and `common/v1/metadata.proto` says GetByName exists where the name is unique within `<resource_type, parent_id>`. The caller adopts the match or deletes it.
- **NebiusProvider.**
  - `quote` reads `orchapod.prices`. Only 1×H100 → gpu-h100-sxm/1gpu-16vcpu-200gb and 1×L40S → gpu-l40s-a/1gpu-8vcpu-32gb are mapped; anything else raises LookupError, and so does an unpriced platform.
  - `provision` refuses, before any call, unless `ORCHAPOD_CONTROL_URL` and `ORCHAPOD_R2_ENDPOINT` are https. This avoids paying for a job that cannot post its logs or read its inputs. It names the job `orchapod-<run_id[:8]>-<unix time>-<node_id>`. After a lost reply (kind `server` or `bad_output`) it lists jobs and adopts the one with that name; a refused create (`bad_request`, `auth`, `rate_limit`) looks nothing up.
  - `wait` polls `jobs.get` every 15 s. COMPLETED → 0. FAILED, CANCELLED or ERROR → logs `"nebius job <id> <state>: <code> <message>"` to the `orchapod.nebius` logger and returns 1. A 5xx or 429 that outlasts the client's retries is logged and polled through, so an API blip never cancels a paid job.
  - `terminate` runs cancel (any ProviderError suppressed: cancel is refused once the job has ended), then delete (404 = done).
  - `stream_logs` yields nothing. The sync client runs through `asyncio.to_thread`.
- **STUB=1.** Offline MockTransport. Jobs come back COMPLETED and endpoints RUNNING at `http://stub.invalid`. Ids are `aijob-stub-<h>` and `aiendpoint-stub-<h>`, deterministic per request. list() returns []. No token or project is needed.

## Sources, per field (fetched 2026-10-21)
- Routes, verbs and bodies, from https://docs.nebius.com/serverless/jobs/manage, https://docs.nebius.com/serverless/quickstart/jobs, https://docs.nebius.com/serverless/endpoints/manage and https://docs.nebius.com/serverless/quickstart/endpoints:
  - Jobs: `POST/GET/DELETE https://api.nebius.cloud/ai/v1/jobs[/{id}]`, `GET …/jobs?parentId=`, `POST …/jobs/cancel {"id"}`, and the job id in `resourceId`.
  - Body fields: `metadata.parentId`, `metadata.name`, `spec.image`, `args`, `environmentVariables[].name/value`, `platform`, `preset`, `timeout` ("3600s"; minimum 3600s, maximum 604800s, default 86400s), `disk.type` NETWORK_SSD, `disk.sizeBytes` (the docs send it as a string, 268435456000), `shmSizeBytes`, `volumes[].source/containerPath/mode` READ_ONLY|READ_WRITE.
  - Endpoints: `ports[].containerPort/protocol` HTTP, `authToken`, and the URL as `.status.publicEndpoints[] | select(startswith("https://"))`.
- States and codes (NotEnoughResources → ERROR after 30 min; StartFailed, ContainerFailed, TimeoutExceeded): https://docs.nebius.com/serverless/lifecycle
- Errors as HTTP, from https://docs.nebius.com/rest-api/errors:
  - 401 = UNAUTHENTICATED.
  - 429 = RESOURCE_EXHAUSTED, meaning quotas exhausted.
  - 504 = DEADLINE_EXCEEDED, which "may occur even if the request completed successfully". That is why a create is never re-sent after a 5xx.
- Auth: Bearer access token, `nebius iam get-access-token`, valid 12 h. Sources: https://docs.nebius.com/rest-api/authentication and https://docs.nebius.com/iam/authorization/access-tokens. The token-on-stdout form `$(nebius iam get-access-token)` is from https://github.com/nebius/api README.
- CLI volume form `s3://BUCKET:/container_path[:MODE[:PROFILE]]`: https://docs.nebius.com/cli/reference/ai/job/create
- Egress without a public IP (so no `publicIp` is sent): the "default egress gateway" uses "a dynamic public IP address from a common pool". Source: https://docs.nebius.com/vpc/routing/overview
- From the protos only (https://github.com/nebius/api, `nebius/ai/v1/job.proto`, `endpoint.proto`, `job_service.proto`, `endpoint_service.proto`, `common/v1/metadata.proto`). The REST spelling is inferred from proto3 JSON camelCase, which matches every docs example (`resourceId`, `publicEndpoints`, `parentId`):
  - `status.stateDetails.{code,message}`
  - `volumes[].s3Config {endpoint, region, credentials {accessKeyId, secretAccessKey}}`, with `source` as an "S3 URI (e.g. s3://bucket-name)"
  - `items`, `nextPageToken`, `pageToken`
  - `metadata.createdAt`
  - "auth_token: if not provided, authentication will be disabled"
  - the endpoint's `disk` is required
  - JobService and EndpointService are served at `apps.msp.api.nebius.cloud:443` over gRPC (endpoints.md)

## Could not confirm (no key, no project; nothing reached a Nebius API)
- I could not get the REST reference's per-endpoint pages: https://docs.nebius.com/rest-api/reference is an interactive index. So `pageToken` as a query parameter, and the exact JSON of the Operation and error bodies, come from the protos and the guides.
- Whether `subnetId` may be omitted. The proto says the project's default subnet is used; the guide says it is "Required if the project has multiple subnets". A fresh project has one `default-subnet`. Not sent.
- Whether `cancel` gives the container a SIGTERM and a grace period. The guide says it "immediately stops the underlying VM". If so, a cancelled gpu node never writes its `cost_json` (see open question 1).
- What `cancel` returns for an already-ended job. Any ProviderError there is suppressed.
- Whether a create can return HTTP 200 with a completed, failed Operation. Only `resourceId` is read; without it the call raises `bad_output`, and callers look the resource up by name.
- Name charset limits (`ResourceMetadata.name` only says ≤ 1024 bytes). Names are `[a-z0-9-]` and ≤ 63 characters, as in vllm-serve.
- The list order the API returns. We sort it ourselves.

## Cost and network
$0. No Nebius API was called, with no key and no project. WebFetch was not in my tool list, so I read public documentation with curl: docs.nebius.com pages and llms.txt, the nebius/api protos on raw.githubusercontent.com, and one api.github.com tree listing. Nothing ran from the downloads; I only read them as text.

## Open questions and follow-ups (for the Orchestrator)
1. **Cancelled gpu jobs may record no cost.** Nebius cancel seems to stop the VM at once, so the node's SIGTERM `finally` and `cost_json` may never run. The executor (backend) could record `gpu_hours` for `nebius` pods from its own wall clock at terminate.
2. **The hosted vllm-serve gets no IAM token (backend; affects G2).** R15 puts the CLI only in the API image, and `NEBIUS_IAM_TOKEN` stays blank on the host. vllm-serve runs in its own container, so it gets a blank token and no CLI, and `endpoints.create` fails with `auth`. Proposed fix: `_build_env` forwards a fresh token. Platform would expose a public `iam_token()` (the renew path above, 3 lines) for it to call; I did not add it, since nothing calls it yet. Locally, today, `NEBIUS_IAM_TOKEN` must be set by hand (it lasts 12 h).
3. **Endpoint names collide on retry-node (ml-w4).** Names are unique per project, so vllm-serve's `orchapod-<run8>-<node_id>` gets a 409 if the previous attempt's endpoint still exists. It can now `endpoints.list()` before create and adopt or delete the match (R19).
4. **Nebius 429 is reported as `rate_limit`.** It means RESOURCE_EXHAUSTED (quota), but the shared policy retries it 3 times and then reports `rate_limit`. That is harmless for spend. Map it to `quota` for a clearer message? Not done.
5. **terminate's delete removes failed jobs.** Deleting right after a job ends may also drop `nebius ai job logs` for a failed job. Node logs still arrive through the SDK. Kept, as the contract says.
6. **Orphaned jobs after an API crash (backend sweep).** If the API dies mid-create, the job is not in `gpu_pod_id`. The 3600 s timeout bounds it. The sweep could cancel non-terminal `orchapod-*` jobs from `jobs.list()`.
7. **Pre-existing lint error.** ruff F841 at tests/providers/test_vastai.py:181. `make check` does not lint tests; left for the vast.ai deletion.

## DECISIONs to record
- DECISION 2026-10-21: NebiusServerless speaks REST `https://api.nebius.cloud/ai/v1`, confirmed by the docs' REST examples. Job cancel is `POST /ai/v1/jobs/cancel {"id"}`. `jobs.list()` and `endpoints.list()` page through everything, newest first, and recover a lost create by `metadata.name` (unique per project and kind). get and list share the view `{id, name, state, url, code, message}`. delete treats a 404 as done. Source: platform-w5, from the orchestrator's wave-5 addition.
- DECISION 2026-10-21: `endpoints.create` refuses a blank auth_token, because Nebius would disable authentication. NebiusProvider:
  - runs only 1×H100 or 1×L40S
  - refuses non-https ORCHAPOD_CONTROL_URL or ORCHAPOD_R2_ENDPOINT before creating a job
  - adopts its job by name after a lost reply
  - polls through Nebius API blips

  Source: platform-w5.
