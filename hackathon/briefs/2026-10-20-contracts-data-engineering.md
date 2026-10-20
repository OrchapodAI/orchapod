# Contracts proposal: data-engineering (2026-10-20, NebiusHackathon @ c866d7f)
Paste as a new section of docs/contracts.md; it replaces the web-research and synth-distilabel lines under "New nodes". It is aligned with backend's section (SDK cost/metrics, refs, executor env), platform's (clients, retries, STUB) and ml-engineering's (row shapes, wiring).

## Data nodes: web-research → synth-distilabel → data-prep (owner: data-engineering)
### Shared rules
- **Runtime `cpu`** (LocalDocker). These nodes only call APIs and finish in minutes.
- **Build.** The image name is the node type, built from the repo root with `docker build -t orchapod/<node>:dev -f containers/<node>/Dockerfile .`; the Dockerfile does `COPY packages/sdk-py/orchapod /app/orchapod`, `COPY packages/providers /app/packages/providers`, `pip install httpx` and `COPY containers/<node>/run.py /app/run.py`. The repo root wins over data-prep's `COPY run.py` and synth's vendored `sdk/` (which is deleted), because CI, build-and-push-containers.sh and local_docker.py all build from `.`.
- **Outputs.** Names match `^[a-z][a-z0-9_]*$`, because refs split on dots, so the skeleton's `corpus.jsonl` and `dataset.jsonl` become `corpus` and `dataset`.
  - The R2 key is the bare name, so every dataset artifact is UTF-8 JSONL whatever it is called. Every declared output is always written, empty if need be, so consumers never fail with `unresolved ref`.
- **API calls go only through platform's clients** (platform section): `TokenFactory(on_usage=cost.add)` and `Tavily(on_usage=cost.add)` from `packages.providers`, with no openai SDK, tavily-python or urllib.
  - `teacher_kind`, the OpenAI/Anthropic code paths and synth's legacy api.studio.nebius.ai URL are deleted.
  - Generation calls `tf.chat(messages, model, json_schema=…, thinking=False)` and reads `parsed`. `NEBIUS_BASE_URL`, retries, prices (`orchapod.cost.PRICES`) and STUB all live in the client.
- **Cost and metrics go through the SDK** (backend section). `on_usage=cost.add` records every billed call (Token Factory tokens, Tavily credits), and the SDK writes `cost_json` at exit.
  - Each node calls `io.write_metrics(dict)` once with the keys below, and the SDK fills in `stub`.
  - Together these replace synth's `cost_summary_json`, data-prep's `stats_json` (nothing reads either) and synth's stale price table ($0.18/$0.60).
- **`STUB=1`.** Nodes run their normal path against the clients' deterministic stubs (minimal schema instances, Tavily pages of ≥ 400 chars), so outputs keep their shapes with `usd: 0`. data-prep skips its quality filter: a stub score of 0 would drop every row.
  - Without STUB, a missing key is fatal. Today synth silently stubs when `NEBIUS_API_KEY` is "" and reads `STUB_TEACHER`; the contract wins.
- **Errors.** A fatal error is `log.error("<reason>")` then exit 1; the executor shows that last ERROR line.
  - `ProviderError` kinds `auth`, `bad_request` (including a model with no price) and `quota` are fatal.
  - `rate_limit`, `server` and `bad_output` (raised after the client's retries) are counted in `failed_calls` and skipped.
- **Progress.** Call `log.progress(done, total)` once per batch.

### web-research (new: `NodeType.WEB_RESEARCH = "web-research"`, containers/web-research/; models and registry row in packages/workflow_schema/models.py)
- Inputs (`WebResearchInputs`):
  - `queries: list[str] = []`: each one becomes `search(q, search_depth="advanced", include_raw_content=True, max_results=⌈max_pages / len(queries)⌉)`. The skeleton's single `query` becomes this list, because intent #1 spans several topics.
  - `seed_urls: list[str] = []`: passed to `extract(urls)`. At least one of `queries` and `seed_urls` is required (validator).
  - `max_pages: int = 20` (1–100): caps pages extracted, and with them credits.
- Output `corpus` (`WebResearchOutputs`): one `{"url": str, "text": str}` per line.
  - Passages are 200–2,000 chars, split at paragraph breaks; shorter fragments (navigation, banners) are dropped.
  - URLs are normalised (no fragment, no trailing slash) and deduped. Exact-duplicate passages are dropped.
- metrics: `{queries, urls, urls_failed, passages, duplicates_dropped}`.
- Errors: a failed URL (Tavily `failed_results`) is skipped and counted. 0 passages is fatal.

### synth-distilabel (adds two templates; existing input names stay)
- Inputs (`SynthDistilabelInputs`):
  - `pipeline_template`: "self-instruct" | "evol-instruct" | "magpie" | "grounded" | "structured", default "self-instruct". This is the only mode selector; there is no `mode` input.
  - `n_samples: int = 1000` (≥ 10). It wins over the skeleton's `n_rows`, because the schema, canvas defaults and README already use it.
  - Unchanged: `teacher_model` (default `nvidia/nemotron-3-super-120b-a12b`), `seed_prompts`, `temperature` and `max_tokens`.
  - `corpus: str | None`: the r2 URI of a web-research corpus. Required for grounded. Optional for structured, where it supplies real values (e.g. movie titles).
  - `row_schema: dict | str | None`: the JSON Schema of one row; a str is parsed as JSON. Structured only. It is not named `schema`, which shadows `BaseModel.schema` (pydantic warns).
  - `instructions: str = ""`: domain, audience and style hints for the teacher. For structured, the target value distributions.
  - `max_usd: float = 1.0`: before each call, stop if its worst case (prompt + `max_tokens`) would push spend past min(`max_usd`, `ORCHAPOD_MAX_COST_USD`). The node writes what it has, exits 0 and sets `metrics.stopped = "max_usd"`, before the SDK's `BudgetExceeded` would fire.
- Output `dataset` (`SynthDistilabelOutputs`), chat templates (self-instruct, evol-instruct, magpie, grounded):
  - Row: `{"messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}], "context": str, "source_url": str}`. Only grounded rows have `context` and `source_url`. The old `_meta` key is dropped.
  - The user turn is the question alone (closed-book). The passage lives only in `context`, which judge-eval passes to the judge.
  - Grounded makes one pass over the corpus: one guided-JSON call per passage returns `{"pairs": [{"question": str, "answer": str}]}`, with k = min(5, ⌈n_samples / passages⌉) pairs. Answers are ≤ 3 sentences and answerable from the passage alone.
- Structured template: one object per line matching `row_schema`, with no extra keys.
  - Batches of ≤ 25 rows come from guided JSON `{"rows": [row]}`. Each row is checked with `jsonschema`; invalid rows are dropped and counted.
  - Intent #2 schema: `{"type":"object","additionalProperties":false,"required":["user_id","movie_title","action","timestamp","device"],"properties":{"user_id":{"type":"string"},"movie_title":{"type":"string"},"action":{"enum":["like","share","subscribe"]},"timestamp":{"type":"string","format":"date-time"},"device":{"enum":["mobile","tv","web","tablet"]}}}`.
- metrics: `{template, teacher_model, n_requested, n_rows, calls, failed_calls, invalid_rows, stopped}`. `stopped` is null, "max_usd" or "exhausted": the corpus ran out, or 3 batches in a row produced no valid row.
- Errors: grounded without `corpus`, or structured without `row_schema`, fails the validator and is fatal. Per-call errors follow the shared rule. 0 rows is fatal.

### data-prep (existing; adds a test split, dedupe, a quality filter, and structured and QA rows)
- Inputs (`DataPrepInputs`):
  - `dataset: str`: an r2:// URI, `hf://<id>` or `<org>/<name>`.
    - Today r2:// URIs reach the HF loader (`or` binds looser than `and`), and files without an extension are rejected. Fix: test r2:// first, and read JSONL unless the name ends in .csv.
  - New `hf_config: str | None = None` and `hf_split: str = "train"` (hard-coded today). Both are passed to `datasets.load_dataset`, so slices like `"test[:50]"` work.
  - `format`: "chatml" | "alpaca" | "sharegpt" | "qa" | "structured", default "chatml". `qa` maps `question` → user and `answer` → assistant verbatim. `structured` keeps rows as they are.
  - `train_split: float = 0.9`. The default stays, because two templates set 0.9 and read `eval_jsonl` as their eval set.
  - New `test_split: float = 0.0`. Eval gets 1 − train − test, and train + test ≤ 1 (validator). Plans that include judge-eval use 0.8 / 0.1.
  - `quality_filter: bool = False` (chat formats only): Lightning scores each row 1–5 via guided JSON `{"score": int}`, and rows below 3 are dropped.
- Steps: load → convert and validate (bad rows dropped) → exact dedupe on canonical JSON → near dedupe → quality filter → deterministic split (seed 42), stratified by `source_url` when present.
  - Near dedupe applies to chat only: char 5-gram Jaccard ≥ 0.9 on the normalised first user turn.
- Outputs (`DataPrepOutputs`):
  - `dataset`: every cleaned row, extra keys kept. This is the download link for intent #2 and the GSM8K eval set for intent #3.
  - `train_jsonl` and `eval_jsonl` (validation; existing names kept). Chat rows are reduced to `{"messages": [...]}` and must pass the TF rules; failing rows are dropped. Structured rows are written unchanged.
    - TF rules: roles are in {system, user, assistant}, with system only first; there is at least one user turn; the last turn is the assistant's; every content is a non-empty string.
  - `test_jsonl` (new): held out, keeps `context` and `source_url`.
- Wiring (agreed with ml-engineering): tf-finetune `train_data`/`eval_data` ← `train_jsonl`/`eval_jsonl`; judge-eval `test_data` ← `test_jsonl`.
- Intent #3 wiring: data-prep with `dataset: hf://openai/gsm8k`, `hf_config: main`, `hf_split: "test[:50]"`, `format: qa`; judge-eval `test_data` ← `dataset`.
- metrics: these replace stats.json and keep its keys: `{total, train, eval, test, skipped, exact_dupes, near_dupes, quality_dropped, avg_length_chars, max_length_chars, fields}`.
  - `fields` (structured only) gives per field `{distinct, nulls, top: [[value, count] ×≤10]}`; numeric and ISO-8601 fields add `min`/`max`. It feeds the intent #2 stats card, and with intent #2's 5 fields it stays under the SDK's 16 KB metadata cap.
- Errors: 0 rows after cleaning is fatal.

## Open questions
1. Spike 1: does TF fine-tuning reject extra top-level keys or a system turn, and is there a minimum row count? Until we know, train/eval rows carry `messages` only.
2. Spike 2 (platform's question 4): does TF honour `thinking=False` for Super? If it doesn't, reasoning tokens bill as output, and synth's `max_usd` caps the overrun.
3. frontend: canvas `buildYamlFromGraph` writes objects as `[object Object]`. It must `JSON.stringify` objects as it already does arrays, or `row_schema` breaks on canvas edits.
4. DECISION: add `jsonschema` to the synth image and requirements-dev.txt, because LLM rows cross a trust boundary there. No other new dependency: the platform clients need only httpx.
