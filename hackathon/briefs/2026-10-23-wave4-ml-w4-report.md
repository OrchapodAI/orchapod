# ml-w4 report: wave 4 (2026-10-21)

Branch `hack/ml-w4`, worktree `.claude/worktrees/ml-w4`. Base check `git merge-base --is-ancestor 5d64ed1 HEAD` passes. Status: **DONE**: item 0, the G1 measurement and items 1 and 2.

Spend: **$0**. There were no Token Factory or Tavily calls and no GPU of any kind. The only network use was public Hugging Face downloads and Docker pulls. VASTAI_API_KEY stayed unset. A read-only `vastai show instances` lists only the two pre-existing stopped instances of other projects (54041703, 54062531).

## Commits (not pushed)
| SHA | What |
| --- | --- |
| d474c0e | fix(judge-eval): ml-w3 review minors 1–5 (cancel, slots, r2 refs, test_data first, 10 % pin) |
| aa18847 | fix(hf-download, quantize): log the LFS files actually checked; base_model is the Hub id (minor 6) |
| 3840ad2 | fix(judge-eval): drop ggml's arm64 fp16 CPU variants (intent #3's f16 baseline was garbage on Apple silicon) |
| 089ee4a | feat(vllm-serve): Serverless Endpoint node (item 1) |
| 0f222bf | feat(unsloth-train): Lane B container on spike 4's lock (item 2) |
| 433c984 | feat(registry): vllm-serve `rents_gpu` (needed by backend's gpu guard after merge; see Merge notes) |

**Gate:** `make check` gives ruff clean, **584 passed**, 22 web tests and the E2E SKIP line.

## Item 0: ml-w3 review minors

### 1. Cancel during a Token Factory phase
- **Fix.** A module-level `STOP` Event is set when `each()` unwinds on any exception (cancel, budget). `judge()` checks it before each order, so a row in flight never starts its second paid order.
- **Test.** The cancel test now runs the node in a **subprocess**.
  - It uses the SDK's own SIGTERM handler (`orchapod.io._sigterm`) and times the `atexit`, where the SDK writes cost_json, not `main()`.
  - A real SIGTERM arrives while every worker holds a 3 s judge call.
  - It asserts exit 143, exactly `WORKERS` judge calls (all started before the TERM) and atexit within delay + 2 s.
  - Before the fix the same test saw **16 judge calls**: the 8 second orders started after the cancel.
- **Root cause, backend's (not changed, as asked).** The SDK writes cost_json from `atexit`. CPython's `threading._shutdown()` runs first and joins every non-daemon thread, including the pool's workers (concurrent.futures' `_python_exit`).
  - So a Token Factory call in flight holds cost_json for up to its read timeout (120 s), plus the client's retries.
  - Two possible fixes:
    - write cost_json in `_sigterm` before raising `SystemExit(143)`;
    - or register `_at_exit` with `threading._register_atexit`, whose callbacks run (in reverse order) before the joins.
- **Real check** in a container on the final image. `docker stop -t 30` mid GGUF phase returned in **9.9 s** with **exit 143**, and `cost_json` (`{"usd": 0, "items": []}`) and `logs` were uploaded. The ~10 s is the client retrying the killed llama-server (1, 2, 4 s backoff), which is unpaid.

### 2. One constant for rows in flight and slots
- `WORKERS = 4` drives both the pool and llama-server's `-np` (and `-c = WORKERS × (max_tokens + 2048)`). The GGUF test asserts `-np == WORKERS`.
- 4 was kept: with 4 slots the CPU already reaches ~30 tok/s in total (measurement below).

### 3. The 10 % boundary (R23)
- Integer form `10 * len(errors) > len(samples)`.
- The test is now pinned at 1 of 10 failed (passes) and 2 of 10 failed (exits 1, "2 of 10 rows failed…").
- The float form was already correct at this boundary, so the test pins it against a future `>=` or a different denominator.

### 4. r2 refs
- An r2 object that is neither GGUF nor JSON exits 1 with `refused ModelRef <input>: <uri> is neither a GGUF file nor a model_ref JSON`. Before, a plain-text object became a bare Token Factory id and was sent.
- A JSON string or list read from r2 is also refused, never a bare id.
- The endpoint-token clause now also requires `url != $NEBIUS_BASE_URL`.
- Parametrised cases: token outside a model_ref, token sent to Token Factory, plain text, JSON string. Each sends nothing.

### 5. test_data before refs
- `read_rows` and "no test rows" now run before `model_ref()`.
- The test feeds GGUF refs with an unresolved and with an empty test_data, and asserts no GGUF download.

### 6. Nits
- **hf-download** logs the LFS files it checked. The real run logged "SHA-256 verified for 1 LFS files"; the Hub lists 2 LFS files, and one is ignored.
- **quantize's `base_model` is the Hub id for an `hf_model` input.**
  - hf-download writes `hf_model/orchapod_source.json` (`{model_id, revision}`), and quantize reads it from the downloaded directory.
  - The auto-registered Model is then "qwen2-5-math-1-5b-instruct-gguf-q4_k_m" instead of "hf_model-gguf-…".
  - The real convert accepted the extra file.
  - Under STUB, quantize downloads nothing, so `base_model` stays the input as given.

## G1 risk: intent #3's evaluate on this Mac

### Setup
- Images built as `orchapod/{judge-eval,quantize,hf-download}:ml-w4`. No `:dev` image was retagged.
- The template's chain ran directly against the compose MinIO (network `orchapod-hack_default`, no control plane):
  - hf-download `Qwen/Qwen2.5-Math-1.5B-Instruct`: 50 s, 11 files (including the sidecar).
  - data-prep `hf://openai/gsm8k` main `test[:50]` qa: 7 s, 50 rows. This was data-eng's `:dev` image, run read-only.
  - quantize keep_f16: 51 s (convert 15 s, q4_k_m 31 s); f16 3.09 GB → q4_k_m 0.99 GB.
- judge-eval: template inputs with n_judge 0, so no key was needed.

### Finding: the f16 baseline is garbage on arm64
**The f16 GGUF answered garbage on this Mac.** Every base answer ran to `max_tokens` 512, at 2.1 tok/s per slot: about 4 min per batch of 4 rows, or ~50 min for 50 rows. The f16 baseline would have scored 0.

Diagnosis, each check asking GSM8K row 0:
| Variant | Result |
| --- | --- |
| q4_k_m | correct, `\boxed{18}`, 276 tokens in 32 s |
| f16 | "…at the farmers' market,??????…" after 13 tokens |
| bf16 (converted fresh) | "????" |
| q8_0 (converted fresh) | "????" |
| f16 with `--no-repack` | same garbage |
| f16 with `-t 1` (so not a race) | same garbage |
| f16 with `-fa off` | garbage from the first token |
| q4_k_m with `-fa off` | correct |
| f16 on the latest build b11783, arm64 | same breakdown ("GGGG…") |
| f16 on the **amd64** build under emulation | **correct**: 290 tokens, `\boxed{18}`, finish "stop" (4.4 tok/s even emulated) |
| f16 with only `libggml-cpu-armv8.0_1`/`armv8.2_1` left in the arm64 image | **correct**, and fast |

- The Docker VM's CPU (M1 Pro: `fphp asimdhp asimddp`, no bf16/i8mm/sve) makes ggml load the `armv8.2_2` variant, which has fp16 vector arithmetic. That variant (and every variant above it) breaks Qwen2.5's non-K-quant inference.
- **Fix (3840ad2):** judge-eval's image removes `libggml-cpu-armv8.2_[23]`, `armv8.6_*` and `armv9*`. This is a no-op on amd64 builds (CI, Nebius CPU VMs). A guard test fails without the line. quantize runs no inference and is unaffected.

### Measurement with the fixed image
Full template evaluate (50 rows, both GGUFs, exact_match, n_judge 0, max_tokens 512) at host load 10–20 from other agents:
| Phase | Time | Detail |
| --- | --- | --- |
| total | **18 min 01 s** | exit 0, **0 of 50 rows failed** |
| f16 | 8 min 38 s | 50 answers, mean 306 tokens, 4 hit 512, 8.3 tok/s per slot |
| q4_k_m | 9 min 07 s | mean 304 tokens, 2 hit 512, 7.5 tok/s per slot |

- **exact_match: f16 0.78, q4_k_m 0.84.** No garbage answer appeared.
- **Decision under the ruling: the template is unchanged** (gsm8k `test[:50]`, max_samples 50).
  - The full evaluate is about 18 min plus the judge phase. That is 20 rows × 2 orders on Ultra, 4 in flight, roughly 2–4 min, but it cannot be measured without a key.
  - That gives about 20–22 min, under the ~25 min bar. `reduced_inputs` is untouched.
- **Caveat:** the shared `orchapod/judge-eval:dev` (built before this branch) still has the arm64 bug. Rebuild it after merge, before any real intent #3 run on this Mac; otherwise the f16 baseline scores 0 and the run takes ~50+ min.
- Cleanup: all `mlw4-*` containers, the `runs/mlw4-*` MinIO objects, my `:ml-w4` images and the images I pulled (`ghcr.io/ggml-org/llama.cpp:server` b11783 arm64 + amd64, `alpine:3`) are removed.

## Item 1: vllm-serve rewrite (089ee4a, 433c984)
`containers/vllm-serve/run.py` is an `api` node (no `long_running`) per contracts "vllm-serve", R10, R11.

### Flow
- **Checks, before anything is created:**
  - an unresolved ref fails;
  - `keep_alive_min` must be 1–120;
  - the price comes from `PRICES["nebius_serverless"][platform]` (unpriced → exit 1), and the estimate is checked against `ORCHAPOD_MAX_COST_USD`;
  - `ORCHAPOD_ENDPOINT_TOKEN` and `ORCHAPOD_CONTROL_URL` are required outside STUB, because the backend deletes the endpoint at expiry;
  - an r2 input from another bucket is refused.
- **Create.** `NebiusServerless().endpoints.create(name, "vllm/vllm-openai:v0.18.0-cu130", args=…, env=…, platform, preset, port=8000, auth_token=ORCHAPOD_ENDPOINT_TOKEN, volumes=("s3://<bucket>:/mnt/artifacts:ro",))`:
  - `name` is `orchapod-<run8>-<node>`;
  - `env` carries `HF_TOKEN` only for a Hub id;
  - the mount is added only when an input is r2.
- **Args.** `<hf id | /mnt/artifacts/<key>> --served-model-name <base> --port 8000 --max-model-len --dtype --gpu-memory-utilization`. With `lora_adapter`, `--enable-lora --lora-modules tuned=/mnt/artifacts/<key> --max-lora-rank 64`; vLLM's default rank of 16 would refuse r 32/64 adapters.
- **Wait.** Poll `endpoints.get` every 15 s (with progress) until RUNNING within 15 min. ERROR or STOPPED exits at once.
- **Smoke.** One 16-token completion through `TokenFactory` with `base_url=url/v1` and the token. 5xx is retried until the deadline while vLLM loads.
- **Register.** `log.post("/internal/ttl", {action, keep_alive_min, endpoint_url, endpoint_id})`. Today's route ignores the extra `endpoint_id` until backend adds it.
- **Outputs.** `model_ref` is `{base_url, model: "tuned"|served name, api_key_env: "ORCHAPOD_ENDPOINT_TOKEN", base_model}`, with metadata adding `endpoint_id`, `expires_at` and `proof`. With an adapter, `base_model_ref` is the same endpoint with model = the base. The token never appears in a file, metadata or metrics (test).
- **Failure or cancel before registration** deletes the endpoint. A failed delete is logged as an ERROR telling the operator to delete it in the console.
- **Cost:** `nebius_serverless` `<platform>/<preset>`, with gpu_hours counted from creation, plus keep_alive_min once registered.
- **STUB=1:** no Nebius call. The endpoint is `http://stub.invalid`, and it is **still registered through /internal/ttl** (qa-w3 and Orchestrator requirement), so /compare's pairing accepts the refs. $0.

### Lane B wiring
- A test feeds vllm-serve's `model_ref` as written to judge-eval's `model_ref()`. It is accepted with ORCHAPOD_ENDPOINT_TOKEN.
- /compare accepts it once it is registered.
- All templates validate in the planner, including real-estate (vllm-serve + lora_adapter → judge-eval: no errors, $1.62 estimate).
- The docs template's fallback is the same chain: `tf-finetune.lora_adapter → vllm-serve(model=<base>, lora_adapter) → judge-eval(base=serve.base_model_ref, tuned=serve.model_ref)`.

### Proof
- 19 tests. The live path runs against a mocked client with the exact contract signatures (Orchestrator's note).
- 19 mutations were tried, and each is caught by a test. One survivor (ERROR detected only at the timeout) led to a tighter test.
- A container STUB run of the new slim image (python:3.12-slim, **269 MB**; it was the ~10 GB vllm-openai image) exited 0 and wrote both refs plus `cost_json {"usd": 0}`.

### Not done / needs
- The live path imports platform's `NebiusServerless().endpoints`, which is not built yet (platform-w5).
- **Missing from the contract:** `endpoints.list` (or get-by-name). It is needed to find and delete an endpoint whose create reply was lost, R19-style. The name is deterministic, so a sweep could use it.

## Item 2: unsloth-train (0f222bf)

### Behaviour
- **Data.** data-prep's chat rows come in through the SDK: `train_data`, and `eval_data` where "" or an empty file means no validation.
- **Recipe (spike 4's):**
  - Unsloth 16-bit LoRA by default (`load_in_4bit` false);
  - batch 2×4, adamw_8bit, LR linear, bf16, seed 3407, max length 2048;
  - **`max_steps` is the demo knob**.
- **BOS kept** in the text (spike 4's fix).
- **Targets.** `all-linear` uses Unsloth's q, k, v, o, gate, up, down. For `nemotron_h` it uses the spike's regex (attention, in_proj, shared experts), never Mamba out_proj or conv1d. A comma list or a regex is passed through.
- **Checkpoints and validation.** Every `checkpoint_steps`: eval, plus a `checkpoint_step_NNNNNN` upload (SDK). A retry resumes from `ORCHAPOD_RESUME_CHECKPOINT_URI`.
- **Outputs:**
  - `lora_adapter` (PEFT) and `merged_model` (16-bit; vllm-serve's `model`), both with metadata `{format, base_model}`;
  - `metrics_json.loss_curve` `[{step, train_loss, valid_loss}]` (frontend-w4's chart reads it), plus loss progress.
- **Billing.**
  - **GPU time is billed as it runs** (every log step), so `ORCHAPOD_MAX_COST_USD` stops training.
  - The GPU is priced by device name: H100 → `gpu-h100-sxm/1gpu-16vcpu-200gb`, L40S → `gpu-l40s-a/1gpu-8vcpu-32gb`.
  - Another GPU is unpriced and fails before the model download (R5).
- **Defaults.** Student `nvidia/Llama-3.1-Nemotron-Nano-8B-v1`. `train_metrics_json` is gone (metrics_json replaces it).
- **STUB=1:** no GPU library, small fixed directories, a 2-point curve, $0.
- **Rental.** It never rents a GPU by itself. The executor's `provider_pref` default is ["nebius"]; the node calls no provider.

### Image
- Spike 4's `pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel` + uv + `spike/requirements.lock.txt` (203 pins) + boto3, plus the Mamba-2 wheels.
- `apache-tvm-ffi` is restored from the lock last.
- The 2025 `requirements.txt` is deleted.

### Proof and limits
- 12 tests; 18 mutations, all caught.
- `docker build --check` passes, with one expected warning: the base image is linux/amd64.
- **Not built here.** The image is amd64 + CUDA, about 20 GB, which is impractical on this Mac. It has never run on a GPU in this form; spike 4 proved the stack itself.

## Merge notes
- `git merge-tree NebiusHackathon HEAD` is **clean**.
- On the merged tree, lint passes and **2 backend tests fail**, both from backend-w4 code that is newer than my base:
  1. **`test_budget.py::test_anonymous_callers_never_start_a_gpu_node`.** `budget.gpu_nodes()` keys on `runtime == "gpu"`. vllm-serve is now `api` (contract), so after merge an anonymous caller could create a paid endpoint.
     - I added `"rents_gpu": True` on vllm-serve's registry row (433c984).
     - The one-line fix in backend's `gpu_nodes`: `… if NODE_REGISTRY.get(t, {}).get("runtime") == "gpu" or NODE_REGISTRY.get(t, {}).get("rents_gpu")`.
     - Proven on a trial merge: 687 passed, with only the next test left failing.
  2. **`test_hardening.py::test_secret_looking_inputs_are_dropped_before_a_workflow_is_stored`.** At /agent/run, its vllm-serve plan with `hf_token` is now **422 "s: unknown input 'hf_token'"**, because the contract removed the input. Nothing is stored, so the test's goal holds; its expected 201 there should become 422 (backend's file).
- Image rebuilds after merge: `orchapod/{judge-eval,vllm-serve,hf-download,quantize}:dev`.
  - judge-eval for the arm64 fix.
  - vllm-serve is now a 269 MB slim image; this also clears qa-w3's 600 s e2e build concern.

## For the Orchestrator
- **DECISIONs:**
  - **judge-eval's image drops ggml's arm64 fp16 CPU variants** (an addendum to R23's llama.cpp pin): measured garbage for f16, bf16 and q8_0 on this M1 in b11223 and b11783; correct on amd64 and with armv8.2_1.
  - **intent #3's template stays `test[:50]`**: measured evaluate 18 min plus an estimated 2–4 min of judging, under 25.
  - **vllm-serve bills gpu_hours from creation to expiry.** The contract line says `keep_alive_min/60`, which leaves out the ~5 min start (and a failed start).
  - **vllm-serve carries `rents_gpu`.**
- **Contract lines to add when convenient:**
  - vllm-serve requires ORCHAPOD_CONTROL_URL outside STUB, registers in STUB too, and uses `--max-lora-rank 64`;
  - hf-download's `orchapod_source.json`;
  - unsloth-train bills per log step, prices the GPU by device, and its outputs are `lora_adapter` and `merged_model` plus metrics_json;
  - the missing `endpoints.list`.
- **Backend:** the SDK's cost_json waits on thread joins (root cause above).
- **CI:** the unsloth-train image is about 20 GB. GitHub's ubuntu-latest runner has ~14 GB free, so its matrix build likely needs a free-disk-space step (as the old 22 GB nvcr base already would).
- **ml-w3's scratch is still here; I did not touch it** because it is not mine:
  - images `llama-slim-test` and `orchapod/{hf-download,quantize}:ml-w3`;
  - MinIO `runs/mlw3real-2210/` (~8 GB) and `runs/mlw3small-2313/` (~2.4 GB).
  - Say if I should remove them.
