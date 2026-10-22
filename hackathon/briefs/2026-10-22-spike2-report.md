# Spike 2 report: Nemotron on Token Factory (role backend) · 2026-10-22

Branch `hack/spike2` (base 791d700): `574386b` (probe + results), `55fe944` and `07e65e8` (docs/feedback.md; full pytest suite 865 passed, ruff clean). Calls ran 03:12:41–03:32:42Z.
**Spend:** $0.0055 recorded by the client's own bill (32 chat calls plus 1 free GET). The worst case is $0.0073: the 4 timed-out attempts of one Lightning call and 1 stopped call may have billed without returning usage. The cap was $1.
**Evidence:** `scripts/spikes/spike2/results.jsonl`, one line per call. Each line holds the request body as sent, the status, the reply body, the latency and the $. No headers are recorded; a check found no key, key prefix, `Bearer` or `Authorization` in it.
**Reproduce:** `set -a; . .env; set +a; python scripts/spikes/spike2/probe.py prices|reasoning|schema|planner|report|repeat|alt|judge`. With `DRY=1` it runs offline on the client's STUB fake. Every call goes through `TokenFactory.chat`; raw shapes (`json_object`, `reasoning_effort`) go through its `**params`.

**Prices:** `GET /v1/models?verbose=true` → 200, 28 models. Its `pricing` matches `PRICES`: Super 0.30/0.90, Ultra 1.00/3.00, Lightning 0.06/0.24 per 1M. Nano (not in PRICES; spike 1's) is 0.06/0.24. It also lists `input_cache_read` (Super 0.06, Ultra 0.12), `per_request_limits` and `quantization` (Super fp4).

## Answers
### 1. `response_format` json_schema (strict): accepted, enforced, valid. Keep it.
| Super, small schema (untyped `enum`) | reasoning | in | out (reasoning) | s | JSON vs schema |
| --- | --- | --- | --- | --- | --- |
| json_schema strict, prompt "Describe one classic movie." | default | 22 | 480 (439) | 2.78 | valid |
| json_schema strict | `thinking=False` | 22 | 37 (0) | 0.91 | valid |
| json_schema strict | `reasoning_effort:"none"` | 22 | 37 (0) | 0.98 | valid |
| json_object + the schema in the prompt | default | 125 | 215 (176) | 2.51 | valid |
| json_object + the schema in the prompt | `thinking=False` | 125 | 38 (0) | 0.86 | valid |
| json_object + the schema in the prompt | `reasoning_effort:"none"` | 125 | 38 (0) | 0.65 | valid |

- **Enforced, not just accepted.** The prompt never names a key, yet the reply was `{"title": "Casablanca", "year": 1942, "genres": [...], "rating": "PG"}`. The prompt counted 22 tokens, so the schema was not added to it: the decoder held the shape.
- **Other schemas and models.** It also held on Lightning (data-prep's integer-enum SCORE schema, 10 of 10 calls), on Ultra (an untyped enum, see the R23 section) and on the planner's schema (section 3).
- **Reasoning on.** Super reasons first, in `reasoning`/`reasoning_content`, then puts the JSON in `content`, so `json.loads(content)` still works.
- **json_object.** It was valid on this four-field schema too, but there the prompt carries the shape, which costs 103 more prompt tokens. A fallback is not needed.
- **The docs.** TF's OpenAPI ("only json_object | text") is wrong; the live API follows its JSON docs page. Super's `system_fingerprint` is `vllm-0.1.dev1+g5001743e3-tp2-…`.

### 2. Reasoning switch: Token Factory honours both. Keep `thinking=False`.
| Super, same prompt (train 14:35→17:10) | out (reasoning) | s | $ |
| --- | --- | --- | --- |
| default (no switch), 2 runs | 129 (118), 139 (128) | 1.58, 3.26 | 0.000130, 0.000139 |
| `chat_template_kwargs: {"enable_thinking": false}`, 2 runs | 7 (0), 7 (0) | 0.76, 0.72 | 0.000020 each |
| `reasoning_effort: "none"`, 2 runs | 7 (0), 7 (0) | 0.81, 0.66 | 0.000020 each |

- **Effect.** Both switches give the same 7-token answer ("2 hours 35 minutes"), 0 `reasoning_tokens` and `reasoning: null`. Ultra (`thinking=False`: 0 reasoning) and Lightning (both switches: 0 reasoning) agree.
- **Lightning's default differs.** With no switch, Lightning wrote its thinking into `content` ("Here's a thinking process: …", 1,200 of 1,200 tokens counted as reasoning, `finish_reason: length`), and `reasoning`/`reasoning_content` were null.
- **Latency.** On Lightning, `reasoning_effort:"none"` was slower in 5 of 7 interleaved pairs, but both switches spread over 1–110 s, so latency does not separate them. On Super they are equal.
- **R12 stands.** No move to `reasoning_effort`.

### 3. Planner call for intent #2: valid first time
- **Request.** planner.py's `make_plan` first call exactly: `_system_prompt()` (23,164 chars), `_answer_schema()`, `thinking=False`, `max_tokens` 4096, `read_timeout` 300. The read timeout never reaches the body; the body is verified below.
- **Reply.** 200, `finish_reason: stop`. 6,871 tokens in, 447 out, 0 reasoning (0 cached). 7.27 s, $0.002464.
- **Validation.** The JSON validates against the answer schema, and `review(plan)` returns errors `[]` and warnings `[]`. Estimate: $0.30, 9.0 min.
- **The plan.** It is the canonical shape:
  - `synth_distilabel`: synth-distilabel, structured, Super, `n_samples` 1000. Its `row_schema` has user_id, movie_title, action ∈ {like, share, subscribe}, timestamp (date-time) and device. Its instructions set 60/25/15 % actions and the last 30 days.
  - `data_prep`: data-prep, structured, `dataset` = `${{ nodes.synth_distilabel.outputs.dataset }}`, `train_split` 0.9, `test_split` 0, `quality_filter` false.
  - It differs from the template in `n_samples` (1000 against 500), leaves `max_usd`/`max_tokens` at their defaults, and uses devices {mobile, desktop, tablet, smart_tv}.
- **Open objects stay open.** The schema's open `"inputs": {"type": "object"}` came back populated; guided decoding does not close it to `{}`.

### 4. Lightning report call: works, cheap, slow
- **Request.** `write_report`'s call exactly: REPORT_PROMPT plus 2,644 chars of facts (the intent #2 plan, estimate and a fake summary), `max_tokens` 1200, `thinking=False`.
- **Reply.** 200, `finish_reason: stop`. 1,211 tokens in, 160 out, 0 reasoning. **$0.000111**, 16.02 s.
- **Content.** Markdown with all 4 sections, 71 words, only the facts given. One flaw: "Win rate (like): 61%", which follows the prompt's example "such as win rate".
- **Latency.** The same call took 16.0, 31.5, 98.3 and 110.1 s (both switches). Once it failed after 4 × 120 s ReadTimeout (490 s, `token_factory server None`).
  - 7-token quality-filter-shape calls took 1.0–37.2 s (10 calls).
  - At 03:31–03:33Z, while Lightning still took 16–18 s, the report prompt took **2.11 s on Super** (251 out, $0.000589) and **1.58 s on Nano** (121 out, $0.000102), and Ultra's judge call 0.71 s.
- **The plan name.** No live report (Lightning ×5, Super, Nano) names the plan. `scripts/e2e_agent.py:103` requires it, so a live agent e2e fails on this report. STUB passes only because `template_report` starts with the plan name.

### Extra: R23's open item is closed
Ultra with judge-eval's schema (`winner: {"enum": ["A","B","tie"]}`, untyped), strict, `thinking=False`: 200, valid, `"winner": "B"`, 91 tokens in, 44 out, 0 reasoning, 0.71 s, $0.000223.

## The client and the planner against the live API: nothing to change in the request
| What we send (packages/providers/tokenfactory.py `_prepare`) | Live result |
| --- | --- |
| `json_schema=` → `response_format {"type":"json_schema","json_schema":{"name":"output","schema":…,"strict":true}}` | accepted and enforced (Super, Lightning, Ultra) |
| `thinking=False` → `chat_template_kwargs {"enable_thinking": false}` | honoured (0 reasoning tokens on all three) |
| `read_timeout` kept out of the body; `temperature`, `max_tokens`, `**params` verbatim | as sent; `reasoning_effort` also accepted |
| parse `choices[0].message.content` only | correct: reasoning arrives in `reasoning` and `reasoning_content` (duplicates), never in `content` on Super |

**The planner's request shape is right for the live API. Change nothing in it, nor in the client.** Exact bodies sent (contents over 600 characters and the planner's schema elided):
```
{"model":"nvidia/nemotron-3-super-120b-a12b","messages":[{"role":"system","content":"<23164 chars>"},{"role":"user","content":"Create synthetic data of movie likes, shares and subscribes."}],"temperature":0.0,"max_tokens":4096,"response_format":{"type":"json_schema","json_schema":{"name":"output","schema":"<planner._answer_schema()>","strict":true}},"chat_template_kwargs":{"enable_thinking":false}}
{"model":"nvidia/Nemotron-3_5-Lightning","messages":[{"role":"system","content":"You write the report of one Orchapod Agent run for the person who asked for it: Markdown, at most 250\nwords, with the sections \"## What ran\" (one line per node), \"## Results\" (the metrics that matter, such as win rate,\nrows, loss), \"## Cost\" (spent against the estimate) and \"## How to use it\" (download links from the artifacts'\ndownload_url, or the model to call). Use only the facts given. If the run failed, name the failed node and its error,\nand say that Retry node resumes from it."},{"role":"user","content":"<2644 chars>"}],"temperature":0.0,"max_tokens":1200,"chat_template_kwargs":{"enable_thinking":false}}
{"model":"nvidia/nemotron-3-super-120b-a12b","messages":[{"role":"user","content":"Describe one classic movie."}],"temperature":0.0,"max_tokens":4096,"response_format":{"type":"json_schema","json_schema":{"name":"output","schema":{"type":"object","additionalProperties":false,"required":["title","year","genres","rating"],"properties":{"title":{"type":"string"},"year":{"type":"integer"},"genres":{"type":"array","items":{"type":"string"}},"rating":{"enum":["G","PG","PG-13","R"]}}},"strict":true}},"chat_template_kwargs":{"enable_thinking":false}}
{"model":"nvidia/nemotron-3-super-120b-a12b","messages":[{"role":"user","content":"A train leaves at 14:35 and arrives at 17:10. How long is the trip? Answer in one line."}],"temperature":0.0,"max_tokens":4096,"reasoning_effort":"none"}
{"model":"nvidia/nemotron-3-super-120b-a12b","messages":[{"role":"user","content":"Describe one classic movie. Answer with only a JSON object that matches this JSON Schema:\n{\"type\": \"object\", \"additionalProperties\": false, \"required\": [\"title\", \"year\", \"genres\", \"rating\"], \"properties\": {\"title\": {\"type\": \"string\"}, \"year\": {\"type\": \"integer\"}, \"genres\": {\"type\": \"array\", \"items\": {\"type\": \"string\"}}, \"rating\": {\"enum\": [\"G\", \"PG\", \"PG-13\", \"R\"]}}}"}],"temperature":0.0,"max_tokens":4096,"response_format":{"type":"json_object"},"chat_template_kwargs":{"enable_thinking":false}}
```

## For backend to fix after (evidence above; no apps/api change in this spike)
1. **The report blocks the GET (P1).**
   - **The problem.** `write_report` runs inside `GET /agent/runs/{id}/report` (apps/api/routes/agent.py:94). Lightning took 16–110 s, and once 490 s before failing. The first GET after the run ends blocks that long, and every poll meanwhile (e2e polls every 2 s) starts its own Lightning call; the race note at agent.py:95–96 assumes that is rare.
   - **Smallest fix.** In `planner.write_report` change `LIGHTNING` to `SUPER`: 2.11 s, about $0.0006 a report against $0.0001. Alternatively use `NANO` (1.58 s, Lightning's price) once spike 1 puts it in PRICES.
   - **Either way, add `read_timeout=60`.** The client retries timeouts 3 times, so a hung call still takes up to about 4 min before the template.
2. **Name the plan in the live report (P1, before a live `make agent-e2e`).** In `write_report`, return `f"## {agent_run.plan.get('name') or 'Agent run'}: {summary['status']}\n\n" + out["text"].strip()`. That is `template_report`'s first line, so `e2e_agent.check_report` holds for any model. Also ask the prompt for "the share of each action", so it does not write "Win rate (like)".
3. **data-prep's quality filter (data-engineering's node; P2, no template enables it).**
   - **Timeout.** `read_timeout=30` is below the observed 37.2 s; one more call took 29.7 s. A timed-out call is re-sent up to 3 times, each send may bill, and then the row counts as failed. More than max(2, 10 %) failed rows is fatal.
   - **Time.** At the observed median of 12.5 s a call, 300 rows take about an hour, not about 2 min.
   - **Fix.** Same as item 1: use Super or Nano, or a thread pool.
4. **Cached tokens are billed at list price (P2, optional).** TF reports `prompt_tokens_details.cached_tokens` (16 of 47 tokens on a repeated prompt) and prices them at `input_cache_read`; the client bills them at list price. That over-counts, which is the safe direction.

## DECISIONs for the orchestrator to record
- DECISION 2026-10-22 (spike 2): the reasoning switch stays `thinking=False` → `chat_template_kwargs.enable_thinking=false`. Token Factory honours it on Super, Lightning and Ultra (0 reasoning tokens); `reasoning_effort:"none"` is equivalent. R12 stands.
- DECISION 2026-10-22 (spike 2): structured output stays `response_format` json_schema strict. It is accepted and enforced on Super, Lightning and Ultra, including untyped enums and open objects, so no json_object fallback is needed. R23's open item is closed.
- OPEN DECISION: the reporter model. Lightning (the contract) took 16–110 s with one 490 s failure on 2026-10-22; Super takes 2.1 s at about $0.0006 a report, and Nano 1.6 s at Lightning's price once it is in PRICES.

## Not done, and why
- **Lightning's default reasoning given room to finish:** not run. At the ~15 tokens/s seen, it would outlast the 120 s read timeout, and every caller sends `thinking=False`.
- **One repeat call (report, `reasoning_effort:"none"` #2):** stopped as it started. That command passed 600 s because of the 4 × 120 s timeouts above, and the harness moved it to the background. I stopped only the process group I had started, and nothing kept running.
