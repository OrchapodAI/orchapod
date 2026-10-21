# ml-w3 report: wave 3 (2026-10-21)

Branch `hack/ml-w3`, worktree `.claude/worktrees/ml-w3`. Base check: `git merge-base --is-ancestor b6c26ff HEAD` passes (branched at ef00bb7). Status: **DONE, with two real re-checks pending on Docker** (Docker Desktop has been down since the Mac rebooted at 03:24Z; per your ruling I did not start it). Spend: **$0**. I made no Token Factory or Tavily call, rented no GPU, and sent no key anywhere. The only network use was public Hugging Face downloads and reading TF's public OpenAPI.

## Commits (not pushed)
| SHA | What |
| --- | --- |
| fd92191 | fix(tf-finetune): a create reply that is not an object is looked up by suffix and cancelled (item 0) |
| a88f5e6 | fix(hf-download): harden per contracts (item 2) |
| be19973 | feat(quantize): GGUF on CPU, keep_f16, metadata/metrics, STUB, llama.cpp b11223 image (item 2) |
| 3b6179a | feat(judge-eval): the node, registry block, Dockerfile, CI line, WORKFLOW_SPEC lines (item 1) |
| a23f730 | fix(judge-eval): wait up to 30 min for a llama-server answer instead of re-sending at 120 s (found in the real run) |
| 2b7e4a4 | docs(agent-knowledge): maths shortlist and the intent #3 wiring (item 2) |
| fa3979c | test(judge-eval): a cancel mid-phase starts no more paid judge calls |
| 640b91f | fix(judge-eval): a cancel returns at once instead of waiting for calls in flight (found in the real run) |
| bca8599 | fix(judge-eval): kill the node's llama-server at the end of its phase (found in the real run) |
| 1a81e50 | test(judge-eval): wider timing margin for the cancel test on a loaded host |

## Your three eval-view checks (frontend-w3): all hold, with one addition
1. `exact_match` is `{"base": float, "tuned": float}`. Each value is a fraction from 0 to 1, rounded to 4 places, or `null` when no row's reference has a number. The whole field is `null` when `exact_match` is off. Tested values include 0.5/0.5 and 0.0/1.0.
2. `metrics_json` is exactly the summary without `samples`. It holds `n, judged, wins, ties, losses, errors, win_rate, consistency, exact_match, base, tuned, judge_model, decoding`, plus `stub`. `stub` is listed in contracts' eval_summary, and the SDK adds it to every metrics_json anyway.
   - `base` and `tuned` are ModelRefs with only `base_url, model, api_key_env, base_model`, so they carry env-var names and never keys.
   - A test asserts the token values ("tf-key", "endpoint-token") appear nowhere in the file, the metadata or the metrics.
   - The internal local GGUF path is dropped.
3. Per-sample verdicts live only in the `eval_summary` file. The `eval_summary` artifact's **metadata** is also the summary without `samples` (same dict as metrics), so the view can read the summary from `Artifact.meta` and fetch the file (GET /artifacts/{id}/download) only for samples.

## Item 0: ml-w2 re-review carry-overs
- **`isinstance(job, dict)` guard** (fd92191). There are two guards:
  - `run.py:113` now reads `if not isinstance(job, dict) or not job.get("id")`.
  - The first line of `finally` resets a non-object `job` to `{}`, so the R19 suffix lookup and cancel still run. This also covers a SIGTERM that lands between the two.
  - Test `test_a_create_reply_that_is_not_an_object_is_found_by_suffix_and_cancelled` (create returns a list) asserts exit 1, the cancel POST and the bill. Removing either guard alone fails it, which I checked by mutation.
- **R19 dependency (suffix echo, newest-first).** This is spike 1's question; with no key I could only check the docs. TF's live OpenAPI (`/openapi.json`, version `20261020-1a55a96cb`, read 2026-10-21) shows:
  - `FineTuningJob` **has `suffix`** (string, maxLength 64, nullable).
  - `GET /v1/fine_tuning/jobs` takes `limit` (no documented maximum) and `after` (cursor) and returns `{object, data, has_more}`.
  - **The order is not documented**, so newest-first is still open for spike 1. I left `limit=20`, because raising it without knowing TF's cap could make the R19 lookup itself fail with a 422.
  - If spike 1 shows oldest-first: page with `after` until `has_more` is false. That is platform's `fine_tuning.list`, which drops `has_more` today.
  - Side finding: our suffix is `<run_id[:8]>-<node_id>`, and the 64-char cap means a node id over 55 chars is refused at create. The planner does not cap id length.

## Item 1: judge-eval (contracts "ML nodes → judge-eval", "ModelRef")
`containers/judge-eval/run.py` (257 lines), runtime `api`, image `python:3.12-slim-trixie` + llama.cpp `llama-server` (CPU build b11223) + the SDK and providers.

### Flow
- **Answers.** Both models answer the first `max_samples` rows (`messages[:-1]`; the reference is never sent) with identical decoding (`temperature`, `max_tokens`). They run one phase at a time (base, then tuned), with 8 rows in flight, through `TokenFactory.chat` with the ModelRef's `base_url`, key and `base_model`.
- **Judging.** Nemotron 3 Ultra judges the first `n_judge` rows (default = `max_samples`) in both orders (`tuned_first`, `base_first`). It uses guided JSON `{"reasoning", "winner": "A"|"B"|"tie"}`, read from `parsed`, at temperature 0 with `thinking=False` and `max_tokens` 1024. A reply without a valid winner is a row error: model output is untrusted, even under guided JSON.
- **Verdicts** are from the tuned side: a win needs both orders to pick tuned, a loss needs both to pick base, and anything else is a tie.
  - `win_rate` = (wins + ½·ties) / judged.
  - `consistency` is the share of judged rows whose two orders agree.
  - Both are `null` when nothing was judged (`n_judge: 0`).
- **`exact_match`** compares the last number of each answer (commas stripped) with the last number of the reference, which in GSM8K is the `#### n` answer. `*_correct` is `null` when exact_match is off or the reference has no number.
- **R18.** Question, reference, context and both answers reach the judge only inside `<question>`, `<reference>`, `<context>`, `<answer_a>` and `<answer_b>`.
  - Tag starts are stripped from the content to a fixpoint (data-w2's approach), so `<<context/context>` cannot reassemble a tag.
  - The system and user messages both say the tagged text is untrusted data, not instructions.
- **Errors.** A `ProviderError` after the client's retries (including `bad_output`) becomes that row's `error`, and the row is excluded from all counts.
  - The node writes `eval_summary` and metrics first.
  - It then exits 1 if errors > 10% of the rows, with the line `"<k> of <n> rows failed (more than 10%); first: <error>"`.
  - An empty `test_data` exits 1 with "no test rows".

### ModelRef inputs
- **Accepted forms:** the JSON object or its JSON string; a bare Token Factory model id; or an `r2://` URI. An r2 object starting with magic `GGUF` is served locally; any other is a `model_ref` artifact read as JSON.
- **Pairing rule, enforced before any call:**
  - `NEBIUS_API_KEY` only with `$NEBIUS_BASE_URL`.
  - `ORCHAPOD_ENDPOINT_TOKEN` only in a ref read from a `runs/<run>/<node>/(model_ref|base_model_ref)` artifact, never inline.
  - No key only for the node's own llama-server.
  - Anything else (inline endpoint token, TF key with another URL, another env var, a bare URL) exits 1 with `refused ModelRef <input>: …` before any request.
  - The client's own last-hop check still applies.
- **GGUF.** `llama-server -m <file> --host 127.0.0.1 --port 8081|8082 --alias <r2 uri> --jinja -np 4 -c 4·(max_tokens+2048)` runs for its phase only.
  - The node waits on `/health` for up to 300 s; if the server dies first, it exits 1 with the server log's last line.
  - The ref becomes `{"base_url": "http://127.0.0.1:<port>/v1", "model": "<r2 uri>", "api_key_env": "", "base_model": null}`.
  - Calls to it use `read_timeout=1800`, and the server is SIGKILLed when its phase ends.
- **STUB=1** runs the same path against the client's offline fake and starts no server.
- **Registry, CI, docs.** The registry block (`JudgeEvalInputs`/`Outputs`, `NodeType.JUDGE_EVAL`, row `runtime: api`) is appended at the end of models.py (R3). The CI matrix gains `judge-eval`. WORKFLOW_SPEC.md gains judge-eval, hf-download and updated quantize sections.

## Item 2: intent #3 path
- **hf-download.**
  - The old node passed `resume_download=True`, which huggingface_hub 2.x (the version in its image and the venv, 2.2.0) rejects with a TypeError. The tests mocked the call, so they never saw it. The new tests autospec `snapshot_download` against the real signature.
  - The SHA-256 check covers only the LFS files the ignore patterns let through. Before, every repo with flax or tf weights failed as "MISSING". It also checks at the requested revision.
  - A mismatch or a missing file exits 1 with one line.
  - Gated repo → "set HF_TOKEN and accept the licence on huggingface.co".
  - The `hf_token` input is removed, and `revision` defaults to "main".
  - metrics `{files, bytes, sha256_verified}`; the `.cache` bookkeeping is not uploaded.
  - STUB writes a fixed one-file directory.
  - The Dockerfile pins `huggingface_hub==2.2.0` and drops `hf_transfer`, which huggingface_hub no longer uses.
- **quantize.**
  - `model` may be an HF id or hf-download's `hf_model`. The directory is now fetched with `io.download_directory`; the old code used `download_input`, which fetches one object.
  - The steps are `convert_hf_to_gguf.py --outtype f16`, then `llama-quantize <PRECISION>` → `gguf_file`. `keep_f16` also writes `gguf_f16`, the R11 baseline.
  - metadata `{format, precision, base_model, size_bytes}`; metrics `{method, precision, size_bytes, f16_size_bytes, wall_s}`.
  - `awq` exits 1 with "AWQ needs a GPU job; use gguf". An unresolved ref or an unknown precision exits 1 before any download. A failed llama.cpp step exits 1 with one line.
  - STUB writes 4-byte `GGUF` files.
  - Image: `ghcr.io/ggml-org/llama.cpp:full-b11223` (CPU, Python 3.12, convert dependencies and binaries included) plus boto3. It replaces a CUDA devel image that compiled llama.cpp.
- **Maths shortlist** in docs/agent_knowledge.md (≤ 2B, short chain of thought, licence, why). Sizes and licences come from the HF API on 2026-10-21.
  - **Qwen2.5-Math-1.5B-Instruct** (default): 1.54B, Apache-2.0. Its chat template asks for step-by-step reasoning with the answer in `\boxed{}`.
  - **nvidia/AceMath-1.5B-Instruct**: 1.78B, CC-BY-NC-4.0, on the Qwen2.5-Math base.
  - Left out, with reasons: R1-Distill-1.5B and OpenMath-Nemotron-1.5B reason at length; Qwen3-1.7B is 2.03B and thinks by default; the general and gated models.
  - The intent #3 line now spells out the wiring backend's template already uses.

## Proof
- **Gate.** `make check` gives ruff clean, **412 passed, 3 skipped**, 12 web tests and the E2E SKIP line.
  - The third skip is `test_local_docker` ("needs a docker daemon"). Before the reboot it was 413 passed, 2 skipped.
- **Unit tests** (tests/containers/test_judge_eval.py, 24 tests).
  - They run against the real `TokenFactory` over a fake Token Factory/endpoint transport.
  - The GGUF ones use a **fake `llama-server` on PATH**: a real subprocess and real HTTP. It ignores SIGTERM like the real one, refuses to answer with an Authorization header and records its argv.
  - quantize has 9 tests and hf-download 8.
- **Mutation check.** I broke 18 judge-eval guards one at a time, and every one fails a test:
  - verdict and position-swap mapping, fence fixpoint, both pairing rules, the artifact-name rule, the 10% threshold;
  - thinking off, the untrusted marker, the context fence, n_judge, retrying errored rows, GGUF detection;
  - no key to llama, 127.0.0.1 only, the reference never sent;
  - exact-match off (that test was added after this pass found the gap).
  - "server never stopped" was equivalent at the time (the 30 s wait then killed it). bca8599 removed that wait.
- **Real chain, containers run directly against the compose MinIO (before the reboot):**
  - hf-download `Qwen/Qwen2.5-Math-1.5B-Instruct`: 10 files, 3,098,973,424 bytes, `sha256_verified: true`, 108 s.
  - quantize `keep_f16`: f16 3.09 GB → q4_k_m 0.99 GB (934.69 MiB, 5.08 BPW). Convert took 89 s and the whole node 315 s.
  - data-prep (data-eng's existing `:dev` image): `hf://openai/gsm8k` main `test[:20]` qa → 20 rows.
  - In the judge-eval image, llama-server served that q4 file. GSM8K test item 1 came back as `… \boxed{18}`, which is correct: 276 tokens in 214 s, 1.3 tok/s.
  - Qwen2.5-0.5B-Instruct: download 50 s, quantize 63 s (f16 942 MiB → q4_k_m 374 MiB).
- **Real runs found three bugs, all fixed with tests:**
  1. The client re-sent slow CPU answers at its 120 s read timeout, and llama-server cancelled and restarted them, so no row ever finished. Fixed in a23f730.
  2. `docker stop` during a GGUF phase ended in SIGKILL (exit 137) with no cost_json, because the thread pool waited for requests in flight. Fixed in 640b91f.
  3. llama-server, measured in the image, was **still running 60 s after SIGTERM** with 4 busy slots, so `terminate + wait(30)` used up the whole grace. Fixed in bca8599: it is killed.
- **STUB intent #3 through this branch's real API, executor and LocalDocker.** The plan was backend's `3-maths-quantize.json` template from NebiusHackathon, run as a workflow. Run `ec2f556c` **succeeded in 171 s, cost $0**: download, gsm8k, quantize and evaluate all succeeded.
  - `quantize/gguf_file` and `gguf_f16` had `size_bytes` 4.
  - The `evaluate/eval_summary` metadata equalled metrics_json (no samples): n 20, judged 20, ties 20, win_rate 0.5, consistency 0.0, exact_match {0.0, 0.0}.
  - The downloaded file held 20 samples with both judgments.
  - That run used the judge-eval image from a23f730. The later fixes do not touch the STUB path.

## Not done / pending (needs Docker)
1. **Real cancel re-check on bca8599:** `docker stop -t 30` during a GGUF phase. I expect exit 143 within the grace and `cost_json` registered. Unit-tested, not yet re-run in a container.
2. **A real judge-eval run to completion on GGUFs** (`n_judge: 0, exact_match: true`; no TF key needed). The 1.5B f16 baseline decoded at **0.09 tok/s per slot** in the 8 GB Docker VM on a host at load ~25–30: 137 tokens in 27 min. CPU stayed under 2 cores, which looks like memory pressure, so I stopped it. The 0.5B pair is in MinIO ready to use: `r2://orchapod-artifacts/runs/mlw3small-2313/quantize/{gguf_f16,gguf_file}`, rows at `runs/mlw3real-2210/gsm8k/dataset`.
3. **Rebuild `orchapod/judge-eval:dev`** after merge. The local image is from 640b91f.
   - `orchapod/hf-download:dev` and `orchapod/quantize:dev` are from this branch (I replaced the old hf-download:dev, which had the `resume_download` bug).
   - Scratch to clean when Docker is back: image `llama-slim-test`, tags `orchapod/{hf-download,quantize}:ml-w3`, and MinIO `runs/mlw3real-2210/` (~8 GB) and `runs/mlw3small-2313/` (~2.4 GB).

## For the Orchestrator
- **DECISION (contract reading): judge-eval's failure threshold is errors > 10% of `n` (rows answered), not of `judged`.** `judged` = wins + ties + losses, and it is also the consistency denominator. With intent #3's `n_judge 20` of 50 rows, the literal reading would fail a run on 3 errors in 50. Cost if wrong: one comparison.
- **DECISION:** llama.cpp is pinned at **b11223** (ggml-org images `server-b11223` / `full-b11223`, 2026-09-28) for both quantize and judge-eval, so the converter and the server match.
  - The quantize image is now the CPU full image (3.9 GB), with no AWQ code: a GPU job adds it once there is GPU quota.
  - The judge-eval image uses `python:3.12-slim-trixie` because the Ubuntu 24.04 binaries need trixie's glibc/libstdc++; bookworm is too old. It sets `LD_LIBRARY_PATH`, because the binary's RUNPATH only covers the working directory.
- **DECISION:** maths default = Qwen2.5-Math-1.5B-Instruct; AceMath-1.5B-Instruct is the NVIDIA option, non-commercial only.
- **G1 risk (intent #3 on CPU):** CPU decoding of the f16 baseline is the slow part. 50 rows at up to 512 tokens is minutes on a dedicated multi-core CPU node, but impractical on this Mac's shared Docker VM. For a local G1 demo, consider `max_samples` ~10 and `max_tokens` 384 in backend's template, or the 0.5B model. quantize's `base_model` metadata is the input as given (the r2 URI for an `hf_model` input; the HF id is not known there).
- **Contracts lines to update when convenient:** judge-eval's threshold reading above; and that judge-eval fences question and answers as well as context and reference.
- **Merge notes:** a trial merge onto NebiusHackathon@1bb2ee4 (`git merge-tree`) conflicts only in **`.github/workflows/ci.yml`**: keep both `- web-research` and `- judge-eval`. models.py (my block appended after backend-w2's), WORKFLOW_SPEC.md and agent_knowledge.md auto-merge.
- The legacy `/inference` route still writes `hf_token` into quantize/vllm-serve inputs. QuantizeInputs ignores extra fields, so nothing breaks, but the token still lands in stored YAML (ponytail audit item; backend/frontend's surface).
