# backend-w5 report: wave 5 (2026-10-24 brief)

**Status:** DONE. Brief items 1–2, plus the Orchestrator's mid-task items: the IAM token (with its correction), GPU wall-time billing, /internal/ttl expiry with a startup sweep, the vllm-serve start time, `pod.error` and FORWARD. The orphan-by-name sweep was skipped by ruling and carries a `ponytail:` note.
**Branch:** `hack/backend-w5`, worktree `.claude/worktrees/backend-w5`.
- Base 23b0a57; `git merge-base --is-ancestor 23b0a57 HEAD` passes.
- 17 commits, 48a7de5..04f999f. Not pushed.
**Spend:** $0. No key was used, no network call left localhost, and Docker was not touched.

## Commits (oldest first)
| SHA | What |
| --- | --- |
| 48a7de5 | docs(contracts): cancel token, RunOut.workflow_name, executor gpu refusal, R22 acronyms + access_key, incremental cost_json |
| 5beb774 | fix(api): the planner's STUB template match ignores stopwords (near-miss intents) |
| d49b88f | feat(api): tf-finetune priced from trained tokens once the base has a fine-tune price |
| f9d2332 | fix(sdk): cost_json never waits for worker-thread joins at exit |
| b639073 | docs(contracts): IAM token scope, rents_gpu in the gpu guard, executor bills a gpu pod's wall time |
| 3d4b5f1 | fix(api): rents_gpu counts as a gpu node; the executor refuses gpu nodes for runs launched below scale 1 |
| 4e9d838 | feat(api): fresh NEBIUS_IAM_TOKEN at node start; NEBIUS_IAM_TOKEN leaves FORWARD |
| 52e0ecf | fix(api): /internal/ttl deletes the endpoint at expiry by endpoint_id; the startup sweep re-arms expiries |
| ed1d83a | fix(api): only api nodes marked rents_gpu (vllm-serve) get the token; gpu nodes never do (correction) |
| 9132096 | feat(api): a node without an ERROR line takes its provider's `pod.error` as its error |
| 430d1af | feat(api): a gpu pod that ends without its cost_json is billed its wall time; orphan-sweep `ponytail:` note |
| cc7bd82 | feat(api): vllm-serve's estimate bills from endpoint creation (+5 min start) |
| 1b94952 | refactor(api): `gpu_nodes` byte-identical to NebiusHackathon's 18fcc8e, so that hunk merges clean |
| d76b175 | feat(api): RunOut carries `workflow_name` |
| 8b5df1b | feat(api): anonymous cancel needs the run's cancel token |
| 1dd234f | fix(api): the R22 key rule catches acronym camelCase and `access_key` |
| 04f999f | fix(sdk): cost_json bookkeeping follows the cost record (qa-w4's in-process drills) |

## What was built
### Brief item 1: review follow-ups
- **STUB template match ignores stopwords** (`planner.STOPWORDS`, `_words`).
  - "us" is not a stopword, because it is the US.
  - Near-miss tests:
    - "Distill an expert in the Nebius documentation" and "Distill an expert in Nebius" → the docs template;
    - "A model which is an expert in US real-estate compliance" → real-estate.
  - All three picked maths before the change.
- **tf-finetune estimate from trained tokens.**
  - Formula: rows × 250 tokens a row × epochs × `PRICES["token_factory_finetune"][model]`.
  - Rows are synth-distilabel's `n_samples`, directly or through data-prep's `train_jsonl` (× `train_split`).
  - `hyperparameters.n_epochs` wins, as in the node.
  - With no price, or rows that cannot be traced, TYPICAL $0.50 stands with a warning, either "no fine-tune price … (spike 1)" or "the rows of train_data are unknown".
  - The price table is empty, so **all four templates' estimates and `fits` are unchanged by this item**.
  - At a sample $0.40 per 1M tokens, the docs template's finetune node drops from $0.50 to $0.048, and its reduced plan to about $0.055. That fits the anonymous $0.30 cap, so `fits` flips to true for docs once spike 1 fills the price.
  - A plan whose data-prep lacks `dataset` used to raise KeyError (a 500) in my first draft; it is fixed and tested.
- **SDK cost_json without waiting for joins** (`packages/sdk-py/orchapod/io.py`).
  - Root cause: CPython joins the threads (a ThreadPoolExecutor's workers, via `threading._register_atexit`) before atexit runs.
  - cost_json now goes out at three points:
    1. From `threading._register_atexit` as soon as main ends. It is registered after importing `concurrent.futures.thread`, so it runs before the pool's join hook; I checked this empirically on 3.12.
    2. From a daemon thread started by the SIGTERM handler, so the node's own cleanup (cancelling remote jobs) is never delayed.
    3. At atexit, as a top-up for calls that were still in flight.
  - Each registration's metadata `usd` is the increase since the node's previous cost_json; the file is always the whole envelope. If nothing changed, no new cost_json is written.
  - The control plane already sums cost_json per node, so totals stay exact.
  - 04f999f keys that bookkeeping to the cost record (`cost._items`). qa-w4's drills run several nodes in one process with a fresh record each; on the dry-merged tree they showed a -4.8e-05 increment before this fix.
- **`RunOut.workflow_name`.** GET /runs joins the name in the same query (500 runs, one query); the single-run routes read it. It is null for a standalone run.

### Brief item 2: D6 leftovers
- **Cancel token.**
  - start returns RunOut plus `cancel_token`; /agent/run returns `{run_id, workflow_id, estimate, cancel_token}`.
  - The token is 256 bits (`token_urlsafe(32)`). Only its SHA-256 is kept, in a new `cancel_token` table, committed in the same transaction as the move that starts the run.
  - A new table instead of a column on Run, because create_all adds a table to an existing database, while a new column would break an existing Postgres volume.
  - POST /runs/{id}/cancel answers 403 unless the caller is the admin or sends `X-Orchapod-Cancel-Token` (compared with compare_digest). The order is 404, then 403, then 409.
  - Retry keeps the token. A never-started run, or one /inference/deploy started, can be cancelled only by the admin.
- **Executor gpu refusal.**
  - At each node boundary, after the kill switch and before any grant or provider: `scale < 1 and budget.gpu_nodes([type])` fails the node with `admin only: <type> runs on a rented GPU`.
  - `gpu_nodes` also reads `rents_gpu`. Since 1b94952 it is byte-identical to NebiusHackathon's 18fcc8e.
- **R22 key rule.**
  - Keys split at acronym boundaries: HFToken → hf_token, APIToken → api_token, AWSAccessKeyId → aws_access_key_id.
  - `access_key` joins the list.
  - One shared `_secret()` serves both redaction on the way out and the drop at ingest.
  - GPUHours, HFModel and TokenFactory are not caught.

### Orchestrator items (mid-task)
- **NEBIUS_IAM_TOKEN, as corrected.**
  - Only an `api` node whose registry row has `rents_gpu` (vllm-serve) gets it. gpu nodes (Nebius Jobs) and every other node never do, even when the API's NEBIUS_IAM_TOKEN is set.
  - The token is the API's own NEBIUS_IAM_TOKEN when set (the contract's "CLI fallback" rule); otherwise `nebius iam get-access-token` runs on the API host at each start of such a node (10 s, asyncio subprocess).
  - Failure fails the node with one of: `no Nebius IAM token: … no nebius CLI`, `… exited <n>: <stderr tail>` or `… took over 10 s`. STUB skips it.
  - NEBIUS_IAM_TOKEN left FORWARD in 4e9d838, so the platform-w5 re-review's FORWARD item is already done here.
  - The token is never logged, and never put in inputs or meta; a test checks caplog and NodeRun.inputs.
- **GPU wall-time billing** (`_bill_gpu_time`).
  - When a gpu pod is gone (after teardown) and this attempt registered no cost_json, the executor bills provision-to-teardown wall time × `provider.quote(gpu_spec).price_per_hour` (PRICES for Nebius).
  - The bill is a cost_json artifact `{usd, gpu_hours, billed_by: "executor"}` with uri `<provider>:<pod id>`. It is added to Run.cost_usd and emits `run_cost`.
  - A cost_json from an earlier attempt does not count (`created_at >= started_at`).
  - Scenarios tested: preempted, cancelled, the node billed itself, and a retry.
  - `ponytail:` queueing counts (over, never under); a pod a cancel caught still provisioning is not billed; endpoints keep their own lifecycle.
- **/internal/ttl.**
  - `endpoint_id` is required, and `keep_alive_min` must be 1–120 (else 422).
  - At expiry: `NebiusServerless().endpoints.delete(endpoint_id)` behind `internal._endpoints()` (platform-w5's signature, mocked in tests).
    - A 404 counts as done, a `stub-*` id is never sent, and a failed delete is retried every 5 min.
    - **`meta.deleted_at` is recorded on the `endpoint_url` artifact that the route creates**, not on model_ref or outputs: /compare's pair rule already reads `deleted_at` there, so a deleted endpoint stops receiving the token at once. That artifact also stores `endpoint_id`.
  - Expiry changes no status (as 18fcc8e), and the vast.ai branch is deleted.
  - Tasks are keyed by artifact, so a retried vllm-serve's two endpoints both expire.
  - The T-10 min warning (event and email) is kept.
  - The startup sweep `resume_ttls()` runs in lifespan after the run sweep: every registered endpoint not yet deleted gets its task back, and one whose expiry has passed is deleted at once.
- **vllm-serve estimate.** (5 typical start minutes + keep_alive_min)/60 × the platform's rate. This **moves real-estate's estimate: $1.62 → $1.75 full, $0.83 → $0.96 reduced** (tests/api/test_agent.py updated). Its `fits` is unchanged: false for anonymous callers (gpu, and over $0.30), true for the admin. Movie ($0.15 / $0.03), maths ($0.10 / $0.02) and docs ($0.77 / $0.55) are unchanged.
- **`pod.error`.** When a node fails without an ERROR line of its own, `getattr(pod, "error", None)` becomes its error, for example `FAILED NotEnoughResources: …`. A node's own last ERROR line still wins.
- **Orphan-by-name sweep: skipped** (ruling allowed it). `ponytail:` note in `executor.sweep`. It needs platform-w5's `jobs.list()` and `endpoints.list()`, plus a rule for a project two API instances share: the hosted VM and a dev Mac on one NEBIUS_PROJECT_ID would delete each other's jobs.

## Proof
- **`make check`** on 04f999f: exit 0.
  - `All checks passed!`
  - `725 passed, 2 warnings` (base: 702)
  - web `pass 27, fail 0`
  - `SKIP stub e2e`
- **Dry merge** (`git merge-tree` against NebiusHackathon @ 387357b, which includes ml-w4 and qa-w4).
  - One conflict: `apps/api/routes/internal.py`. **Resolve by taking hack/backend-w5's side**: NebiusHackathon's side of that hunk is only the `TODO(backend-w5)` comment this branch resolves, and both sides drop the same imports.
  - Everything else auto-merges, including contracts.md, agent_knowledge.md and budget.py.
  - Merged tree, exported, with that resolution: ruff clean, `761 passed, 2 skipped`. Deselected: `tests/providers/test_hosting.py::test_deploy_never_ships_or_deletes_the_vms_secrets_and_refreshes_node_images`, which needs `.git` and fails the same way on a plain NebiusHackathon export.
- **Mutation checks: 35 of 35 caught.** Every one is a clean failure, none a hang. Every new test also failed before its fix; for example, the stopword cases picked maths 3 of 3, and the estimate stayed at $0.50 with a price set.

  | Area | Count | Mutations |
  | --- | --- | --- |
  | SDK | 6 | no pre-join flush, pool hook not registered first, no SIGTERM flush, total instead of increase, a second cost_json for no change, no top-up |
  | IAM token | 7 | every node; every fresh token; STUB fetches; the set token ignored. Correction: gpu nodes too, every api node, FORWARD carries it |
  | TTL | 10 | endpoint_id optional, no delete, 404 retried, stub deleted, no deleted_at, keep_alive unbounded, sweep re-arms nothing, sweep re-arms deleted ones, wait re-reads the clock, failed delete not retried |
  | Billing | 4 | double count, no billing, no run_cost, an old attempt's cost_json exempts a retry |
  | Cancel token | 5 | no check, the admin needs a token, plain-text storage, start keeps no token, /agent/run keeps no token |
  | R22 | 3 | no acronym split, no access_key, split before every capital |

- **gitleaks** over 23b0a57..HEAD: `17 commits scanned … no leaks found`.

## Contract lines changed (the Orchestrator approves)
- **Node SDK.**
  - cost_json is written at SIGTERM (thread), when main ends (before thread joins) and at exit.
  - Its metadata `usd` is the increase since the node's previous cost_json, and the summary sums them.
  - The executor env line says NEBIUS_IAM_TOKEN goes only to vllm-serve.
- **Config.**
  - NEBIUS_IAM_TOKEN leaves "forwards exactly these".
  - A new sentence gives the rents_gpu api-node rule: the API's token, else a fresh CLI token; `no Nebius IAM token: <why>`; STUB skips; never logged or stored.
- **Run state machine.**
  - Node error strings add `admin only: <type> runs on a rented GPU`, `no Nebius IAM token: <why>`, and the provider's `pod.error` when a node has no ERROR line.
  - A new long-polling bullet: the executor bills a gpu pod's wall time when it has no cost_json.
- **Run control API.**
  - cancel: 403 without the token.
  - A new **Cancel token (D6)** bullet: start/agent-run return it once, SHA-256 kept, `X-Orchapod-Cancel-Token`, the admin cancels any run, retry keeps it, deploy runs are admin-only; RunOut carries `workflow_name`. This is the line frontend-w5 consumes.
  - /internal/ttl: `deleted_at` on the `endpoint_url` artifact, `endpoint_id` required, keep_alive_min 1–120, stub ids never sent, retry every 5 min.
  - Public app (D6): the gpu guard covers `rents_gpu`, and the executor refusal is named.
- **Agent API.** /agent/run returns `cancel_token`.
- **R22.** The key rule splits camelCase acronyms and adds access_key.
- **docs/NODE_CONTRACT.md:**
  - the SDK does not wait for worker threads;
  - NEBIUS_IAM_TOKEN goes to vllm-serve only.
- **docs/agent_knowledge.md:** the estimate line now covers tf-finetune (trained tokens) and vllm-serve (its start).

## DECISIONs to record
1. **Cancel token.** It travels as the `X-Orchapod-Cancel-Token` header; SHA-256 is stored in its own `cancel_token` table (no migration); retry keeps it; never-started and deploy runs are admin-cancel only.
2. **cost_json registrations are increments.** Metadata `usd` is the spend since the node's previous cost_json. The SDK registers at SIGTERM, at the end of main (pre-join hook) and at exit.
3. **NEBIUS_IAM_TOKEN goes only to api nodes with `rents_gpu`.** The API's set token wins, else the CLI runs per node start (10 s). gpu nodes never get it.
4. **Endpoint expiry.** `deleted_at` is recorded on the `endpoint_url` artifact. `endpoint_id` is required, keep_alive_min is 1–120, and a failed delete is retried every 5 min.
5. **Executor bills a gpu pod's wall time** (provision to teardown × quote) when the attempt registered no cost_json.
6. **Estimates.** tf-finetune assumes 250 trained tokens a row; vllm-serve adds a 5-minute start, which moves real-estate to $1.75 full and $0.96 reduced.

## Notes for others
- **frontend-w5.**
  - Keep `cancel_token` from start's reply (`StartOut`) and from /agent/run's, and send it as `X-Orchapod-Cancel-Token` on Cancel. Until then the run page's Cancel answers 403 for anyone but the admin.
  - The 403 detail reads: "cancelling this run needs its cancel token (X-Orchapod-Cancel-Token, returned when it started) or the admin".
  - Name runs from `RunOut.workflow_name`.
- **qa.**
  - `scripts/e2e_demo.py` `poll_run` cancels anonymously after LIMIT_S; that cancel now gets 403, which its `except RuntimeError` swallows. It should send the token from start's or /agent/run's reply.
  - In tests/api, a test that leaves expiry tasks pending can hang pytest-asyncio's teardown, so `tests/api/test_internal.py` gives each test its own `_ttl_tasks` and caps `expiries()` at 5 s.
- **platform-w5.**
  - The code depends on `NebiusServerless().endpoints.delete(id)` (a 404 may raise `ProviderError` with status 404, or return) and on `pod.error` after a failed `wait()`.
  - The orphan sweep waits on `jobs.list()` and `endpoints.list()`.
- **ml.** vllm-serve already sends `endpoint_id`. A `keep_alive_min` above 120 is now refused at the API too.

## What does not work / limits
1. **Orphan-by-name sweep:** not built (see above).
2. **A SIGTERM during the SDK's own exit writes** can break that write. The window is sub-second; the background flush re-registers cost_json, but `logs` would be lost. I removed a guard for it because no test could observe it.
3. **`threading._register_atexit` is CPython-internal** (3.9 and later). Every image is 3.10–3.12; vllm/vllm-openai:latest floats.
4. **The IAM token comes from the API's NEBIUS_IAM_TOKEN when that is set.** Its precedence over the CLI mirrors the contract's "CLI fallback"; a stale static token is the operator's to rotate.
5. **/inference/deploy returns no cancel token,** so only the admin can cancel deploy runs (that route is off the demo path).
6. **Live checks wait on the key:** the IAM CLI against Nebius, `endpoints.delete`, and a real job's wall time. The CLI was mocked with a shell script on PATH; Nebius was mocked at `_endpoints()`.

---

## Fix round 1 (Orchestrator review; all 8 items done)
### Commits (tip f3a905f)
| SHA | Items | What |
| --- | --- | --- |
| 410f6b5 | 2, 4 | The IAM token comes from the CLI first; stdout's last line must match platform's `TOKEN`; fixed errors, never the CLI's stderr |
| b94cb62 | 3, 7, 8a | `endpoint_id` must be an id; a 4xx other than 404/429 ends the delete retries; a re-register supersedes; `_expire` guards a vanished artifact |
| 886fac4 | all | docs(contracts): the round's lines, in their own commit |
| f3a905f | 1, 5, 6 | A gpu attempt costs max(wall-time bill, node-reported) in either order; cost_json `seq`; rollback on a failed bill |

### Per item
1. **GPU time billed twice.**
   - `budget.attempt_cost(metas)` = max(the executor's `wall_usd`, what the node reported).
   - Both sides compute what they add as `attempt_cost(earlier + [new]) - attempt_cost(earlier)`, under one in-process lock (`budget.cost_lock`):
     - the executor's bill (`_bill_gpu_time`) adds only what exceeds the node's reports so far;
     - a node's cost_json (`internal._reconcile`) adds only what exceeds the bill.
   - `meta.usd` = what each row added, so the summary equals Run.cost_usd; `meta.reported_usd` = the node's figure.
   - **Decision 5 updated:** "either order" means the executor now also records its bill when the node reported first, adding only the excess.
   - Hardening added in the same path: a node's figure is clamped at 0, and a node meta's `billed_by`, `wall_usd` and `reported_usd` are dropped, so a gpu Job cannot lower its cost or pose as the bill.
   - Tests (FakeProvider now registers through the real /internal/artifact):
     - late flushes after the bill: $1.00 → total stays $2.25; then $3.00, a re-send, and a larger re-send → $3.50;
     - the cancel;
     - the node reporting first: $0.40, then the bill adds $1.85;
     - a retry, for a new attempt;
     - a race: the node's POST lands between the executor's read and its insert. The test uses per-request sessions as in production; it fails without the lock.
   - The unreachable "second bill per attempt" guard was deleted: billing runs once per attempt by construction.
2. **CLI stderr.**
   - Node errors are fixed text: `no Nebius IAM token: nebius iam get-access-token exited <rc>`, `… printed no token`, `… took over 10 s`, `… the API host has no nebius CLI, and NEBIUS_IAM_TOKEN is blank or malformed`.
   - The token is stdout's last line, required to fullmatch platform's `TOKEN`. On NebiusHackathon it is imported from packages/providers/nebius.py; a one-line fallback copy is marked `ponytail:` for deletion once the merge brings platform-w5 in.
   - The test's fake CLI prints a warning line before the token, and puts a profile and tenant in stderr.
3. **`endpoint_id` in the REST path.**
   - /internal/ttl requires `^[a-z0-9][a-z0-9-]{0,62}$` (422; tested with `../jobs/x`, an empty id, upper case, a leading hyphen, 64 characters, and a trailing newline).
   - `_arm`, which both entry points use, refuses a stored id that does not match.
   - A delete refused with a 4xx other than 404 (done) or 429 (tried again) stops the retries. The next API start tries again.
4. **CLI first.** A fresh CLI token beats a static NEBIUS_IAM_TOKEN; the static one is used only on a host without the CLI.
5. **`seq`.**
   - The SDK sends `{"usd": increase, "seq": n}`.
   - A registration that failed goes again under the same seq with whatever was spent since.
   - The API counts a seq once, at its largest, and stores no re-send of a seq it has already counted.
6. **`_bill_gpu_time`** rolls back on failure (suppressed, so the node's own outcome stands).
7. **Re-register.** Earlier live rows with the same `endpoint_id` get `superseded_at` and their timer is cancelled. `resume_ttls` and /compare's pair rule ignore superseded rows.
8. **Nits.**
   - `_expire` tolerates a vanished artifact.
   - **cost_json rows are not consolidated:** one row per registration, because reconciliation needs each seq's `reported_usd`, and the summary sums `meta.usd`.

### Proof
- **`make check`** on f3a905f: exit 0. `All checks passed!`, `734 passed`, web `pass 27`, `SKIP stub e2e`.
- **Dry merge** with NebiusHackathon @ 90d34a6 (platform-w5, ml-w5, qa-w4 and devrel-w5 merged).
  - Still one conflict, `apps/api/routes/internal.py`; take this branch's side.
  - NebiusHackathon's only edit there since 23b0a57 is 18fcc8e, which this branch already contains.
  - Merged tree: ruff clean, `825 passed, 1 skipped`. Only the `.git`-dependent hosting test is deselected; qa-w4's drills pass.
- **Mutations this round: 21 of 21 caught**, all clean failures.

  | Area | Count | Mutations |
  | --- | --- | --- |
  | IAM | 3 | whole stdout as the token, stderr in the error, static token first |
  | TTL | 8 | no id pattern, `_arm` sends any id, 4xx retried, 429 not retried, no supersede, superseded timer kept, /compare trusts superseded, sweep re-arms superseded |
  | Reconciliation | 10 | late report adds in full, no de-dup, seq counted every time, bill plus report, bill ignores an earlier report, negative report, node posing as the bill, no lock (race test), SDK never records a seq, SDK seq never advances |

- **gitleaks** 23b0a57..HEAD: no leaks.

### Contract lines changed this round (886fac4)
- Node SDK: cost_json metadata carries `seq`; a seq counts once, at its largest.
- Config: the IAM token comes from the CLI first; it is stdout's last line matching TOKEN; a static token only without the CLI; fixed public errors.
- Run state machine, the billing bullet (:245), now the late-cost_json rule: max(wall bill, node-reported), each side adds only the excess, `meta.usd` / `meta.reported_usd`, one lock.
- /internal/ttl: the `endpoint_id` pattern, the 4xx stop rule, and superseded rows.

### Notes
- After the merge, delete run_workflow.py's `TOKEN` fallback; the import from packages/providers/nebius.py is then always found.
- **Still open, with a `ponytail:` note:** a job that never got capacity is billed its provision-to-teardown wait (over, never under). Skipping that bill would need platform's `pod.error` code to be parsed.
