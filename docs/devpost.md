# Devpost entry: Orchapod.ai

Copy each section into the matching Devpost field; clear every TODO(D8) before submitting.

## Title

Orchapod.ai

## Tagline

Describe the specialist model you want in one sentence. Orchapod plans the pipeline, runs it on Nebius with NVIDIA Nemotron, evaluates the result against its base model and shows what it cost.

## Description

### What it does

Orchapod is an open-source platform for the whole post-training lifecycle of a language model: research, synthetic data, fine-tuning, deployment, evaluation and side-by-side comparison. It has two front doors:

- **The Orchapod Agent.** Type one sentence. Nemotron 3 Super drafts a pipeline from the node catalog, the server validates it against the model and cost rules, and a plan card shows the nodes, the models and the estimated dollars and minutes. Press Run and Orchapod executes the plan, streams logs and cost, evaluates the result and writes a report. Or skip the typing: a template card runs a ready-made plan in one click.
- **The canvas.** Drag nodes onto a React Flow canvas. The YAML workflow is the source of truth, and any plan the Agent writes opens on the canvas for editing.

A finished run shows what it made: an eval view (win rate; wins, ties and losses; the judge's consistency between the two answer orders; exact match where it applies; every judged sample with the judge's reasoning), a dataset card with a download link and per-field stats and, when the run serves a model, a compare playground that streams one prompt to the base and tuned models side by side, with the keys kept on the server.

Three intents define "done", and each must run from the chat box with no manual edits: a Llama 3B fine-tuned on US real-estate compliance, synthetic data of movie likes, shares and subscribes, and a quantized maths model. Two more templates distil a Nebius docs specialist from the Nebius AI Cloud and Token Factory docs: the golden path. It ran live twice on the hosted demo, https://app.orchapod.dev, on 2026-10-25: 24.2 and 23.5 min, $1.61 and $1.58, against a $2.66 estimate. The second run was typed on the hosted /agent page as a rehearsal of the demo. Intents #2 and #3 have run live through the Agent on real Token Factory: 928 rows of movie events for $0.1007, and a maths model quantized and judged by Nemotron 3 Ultra for $0.0175. A third live run, on real-estate compliance in five states, was the first to quantize the 8B student and judge it on CPU, with no endpoint. It took 50.7 min and cost $1.35. Ultra scored it 11 wins, 19 ties and 0 losses on 30 held-out questions. Those questions are held-out rows of its own synthetic set, so this measures how well the model learned the collected corpus, not legal knowledge, and none of it is legal advice. On stubs (deterministic stubs, no keys, $0), the three intents and the golden path pass end to end through the Agent API (4 PASS). A Playwright smoke of the web app passes 5 of 5 tests. One of them clicks the golden path's template card, which runs its reduced plan, through the run, the eval view and the compare playground.

The demo video shows a fourth live run, typed as one sentence on the hosted /agent page on 2026-10-27: a Q3 2026 bank-earnings analyst ([6bf36882](https://app.orchapod.dev/runs/6bf36882-b221-4b63-9890-181101b6395f)). Tavily read 40 pages of the eight banks' third-quarter results, Nemotron 3 Super wrote 550 grounded Q&A pairs from them, Unsloth trained NVIDIA Nemotron Nano 8B on an H100 Serverless Job, llama.cpp quantized it to a 4.92 GB GGUF on CPU, and Nemotron 3 Ultra judged it against its base on 54 held-out questions: 15 wins, 27 ties and 12 losses, in 51 minutes for $1.36 against a $2.54 estimate. The base model declined every question; the losses are figures the tuned model misremembers.

### Why

Every team wants a cheaper, faster, private specialist model, and today that takes an ML engineer and a pile of GPU plumbing. Orchapod turns it into a costed, capped and observable workflow.

- **Who it is for.** Teams that need a model fluent in their own material but have no ML engineer to build one: an analyst desk that wants this quarter's earnings figures (the demo video's run), a compliance team working from its rulebook, a support team working from its product docs. They describe the model in one sentence, see the plan and its cost before anything runs, and get a judged comparison with the base model before anyone relies on it.
- **It makes models, not only calls them.** Nemotron teaches and judges new specialist models, and every one is measured against its base.
- **An evaluation you can trust.** Base and tuned models get identical prompts and decoding. A Nemotron 3 Ultra judge sees the question, the reference answer and the source passage, and scores the two answers in both orders; a win counts only if it holds in both. On the two live golden runs (`d20d30f3` and `0ee1e20a`), Ultra judged 30 held-out questions each. The tuned model won 7, lost 1 or 3, and tied the rest: win rates of 0.60 and 0.57, with 0.73 and 0.67 of the verdicts holding in both answer orders. The two runs agree within noise, and we report both. In one win the base model answered generically, while the tuned model said: "When a Serverless AI job completes, the container disk is automatically deleted, and the computing resources are released."
- **Cost is a first-class output.** Every billed call (tokens, Tavily credits, GPU hours) is metered per node, estimated before a run and capped during it.

### How we built it

A typical run: research the topic, generate grounded synthetic data, prepare the splits, fine-tune and serve, judge the tuned model against its base, compare side by side. Every step is a node: a Docker container that reads its inputs as JSON and writes artifacts, logs and a cost record through one SDK. A FastAPI control plane with a DAG executor runs the nodes, and a Next.js app shows the run live: node timeline, logs, cost and artifacts. The fine-tune-and-serve step has two lanes, and a plan can take either without changing the rest.

The golden path is NVIDIA end to end. Nemotron 3 Super plans, writes the synthetic data and writes the report. Nemotron 3.5 Lightning can filter the data. Nemotron 3 Ultra judges. The student is NVIDIA's `nvidia/Llama-3.1-Nemotron-Nano-8B-v1`, trained on a Nebius Serverless Job and served from a Serverless Endpoint, so every model call runs on Nebius. Its template is estimated at $2.66 at full scale, and its worst case under our spend rules is $2.92, under the $3 run cap. A CPU variant, estimated at $2.15, trains the same student, then serves it as a GGUF q4_k_m plus a GGUF LoRA with llama.cpp on the API host, with no endpoint, for Ultra to judge. The other templates are not NVIDIA end to end: real estate fine-tunes Llama 3.2 3B on Token Factory, because its intent names Llama 3B, and maths quantizes Qwen2.5-Math-1.5B-Instruct.

Where each sponsor piece is used:

- **NVIDIA Nemotron on Nebius Token Factory.** A run planned from a sentence starts with a Nemotron call (the plan); a run started from a template skips it. Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`) plans the pipeline and teaches, writing the synthetic data. Nemotron 3 Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`) judges base against tuned. When the run ends, Nemotron 3 Super writes the report in the background: one call of at most 30 s, with thinking off, or a deterministic template when `STUB=1` is set or that call fails. Spike 2 measured about 2 s per report on Super, against 16–110 s on Lightning. Nemotron 3.5 Lightning (`nvidia/Nemotron-3_5-Lightning`) can filter data quality, scoring each row 1 to 5 and dropping rows under 3 (opt-in `quality_filter`; no template enables it yet). All calls go to `https://api.tokenfactory.nebius.com/v1` through one client that prices every call and refuses to send our key to any other host. On each golden run, Super wrote 300 grounded Q&A rows (in 2.1 and 2.55 min, for about $0.03), and Ultra judged 30 pairs in 85 s for about $0.08. Super also planned intents #2 and #3 live and wrote their reports (runs 84e57f84 and 59786797).
- **Nebius Token Factory fine-tuning (Lane A).** `tf-finetune` runs a LoRA fine-tune of a Llama model and keeps the checkpoint with the lowest validation loss. Token Factory does not fine-tune Nemotron, so Nemotron teaches and judges the Llama model instead; the real-estate template takes this lane. Spike 1 fine-tuned 50 rows on `meta-llama/Llama-3.1-8B-Instruct` live, in 6 min 45 s. Per-token LoRA deploy is retired (`POST /v0/models` answers 410), so `vllm-serve` serves the adapter beside its base on a Serverless Endpoint. Token Factory does not publish its price per trained token, so the client refuses to start a fine-tune until the rate is known.
- **Nebius AI Cloud Serverless Jobs (Lane B).** `unsloth-train` runs as a Job on an H100 with a 1-hour timeout. Unsloth trains a 16-bit LoRA on NVIDIA's student, `nvidia/Llama-3.1-Nemotron-Nano-8B-v1`, which a spike on a rented A100 outside Nebius chose: 60 steps took 62.5 s at a 15.9 GiB peak, and the merged model served from vLLM. The docs templates skip the 16 GB merged copy (`merge: false`). Nodes on a Job report to a public https control URL, so the golden run ran from the hosted API. Its Job took 11.2 min on both runs, for $0.8408 and $0.839. The image pull from a Nebius Container Registry in the same project, with no credentials, took about 6 min and then 4.6 min. Both ran 60 of 60 steps; the loss fell from 7.75 to 1.68, then from 7.20 to 1.31.
- **Nebius AI Cloud Serverless Endpoints (Lane B).** `vllm-serve` creates one L40S endpoint that serves the base model and the adapter side by side with vLLM behind a bearer token, so Nemotron 3 Ultra judges the tuned student pairwise against its base. It registers an expiry (15 minutes in the docs template, 30 by default), at which the control plane deletes it, as it did on both runs. vLLM loaded the adapter next to the base model (`--enable-lora`), and the serve step took 9.3 and 8.25 min, for $0.63 and $0.60, its 15-minute keep-alive included.
- **Nebius Object Storage.** An S3-compatible bucket holds datasets, checkpoints and artifacts (MinIO locally). The hosted app's bucket is in eu-north1, beside the GPUs.
- **Tavily.** `web-research` calls Tavily Search and Extract and splits the pages into passages with their source URLs, metering credits per call. The passages ground the synthetic Q&A, so every grounded answer carries its source URL. On each golden run it read 20 Nebius docs pages in 3 s for $0.032 (4 credits).

Where Token Factory accelerated our workflow:

- **Frontier models without hosting them.** Five roles (planner, teacher, quality filter, judge, reporter) run on three Nemotron models behind one OpenAI-compatible endpoint, so a 120B teacher and a 550B judge cost us no GPUs, no serving stack and no capacity planning. The only GPUs we rent are the student's: a Serverless Job to train it and, on the endpoint lane, a Serverless Endpoint to serve it.
- **Plans that validate on the first call.** Strict `json_schema` output makes the planner's answer a workflow drawn from the node catalog: in spike 2 the first call came back valid in 7.3 s for $0.0025. The server then checks models, inputs and cost, with up to two repair rounds.
- **Data and evaluations in minutes, for cents.** Nemotron 3 Super wrote 300 grounded Q&A rows in about 2 minutes for $0.03 on each golden run, and 550 rows from 627 passages in 8.7 minutes for $0.16 on the finance run. Nemotron 3 Ultra judged 30 held-out questions in both answer orders in 85 s for $0.08. With thinking off, a bulk Super call took 0.66 to 0.81 s.
- **Costs we can estimate before a run.** `GET /v1/models?verbose=true` publishes a price per token for every model, so each call is priced before it is sent, the Agent shows a plan's estimate before Run, and the caps hold while it runs.

Beyond the sponsor pieces:

- **Quantization on a CPU (intent #3).** `quantize` turns Qwen2.5-Math-1.5B-Instruct into a 0.99 GB GGUF q4_k_m with llama.cpp, keeping the 3.09 GB f16 GGUF as the baseline, and `judge-eval` serves both files locally with llama.cpp's server. Measured on an M1 Pro Mac, a busy host, with no key: both answered the template's 50 GSM8K test questions in 18 min 01 s in all, with exact match 0.78 for f16 and 0.84 for q4_k_m, a gap of 3 questions that is within noise at n = 50. An earlier run on the same Mac had exposed llama.cpp's fp16 CPU kernels garbling the f16 answers on Apple silicon; the evaluation image now drops those kernels, and the timed run used it. Live through the Agent (run 59786797, $0.0175 in all), Super's plan downloaded a 3.1 GB maths model and quantized it to q4_k_m (0.99 GB) in 75 s on CPU. Nemotron 3 Ultra judged q4_k_m against f16 on 5 questions: 1 win, 4 ties, 0 losses, consistency 1.0. Exact match was 0.8 against 0.6, a gap of one question. Five questions is a smoke-scale sample.
- **Guards for a public demo.** Per-visitor rate limits, an origin allow-list, deep health checks and a kill switch; visitors run at a tenth of the caps, cannot start a node that rents a GPU and cannot change a workflow that has runs; secret-looking inputs are dropped before anything is stored. The hosted demo runs at https://app.orchapod.dev on one Nebius VM in eu-west1, with Docker Compose and Caddy for HTTPS.

## Built with

Nebius Token Factory, Nebius AI Cloud, NVIDIA Nemotron, Tavily, vLLM, Unsloth, llama.cpp, Hugging Face, Python, FastAPI, SQLModel, PostgreSQL, Redis, MinIO, Docker, Caddy, TypeScript, Next.js, React, React Flow, Tailwind CSS, Playwright

## Track

Best Apps and Agents

## Links

- Demo, free with no login until Dec 15, 2026: https://app.orchapod.dev (API: https://api.orchapod.dev). Visitors' runs are capped ($0.30 a run, $2 a day across all visitors) and steps that rent a GPU are admin-only, so the three fine-tune templates show their plan and estimate without running; the finished runs under Testing instructions show those steps end to end. TODO(D8): check it logged out before submitting.
- Video, 2:13, on YouTube, with no music or third-party marks: https://youtu.be/ULEYpAvsUxs. TODO(D8): it is Unlisted; set it to Public before submitting.
- Repository, public with the MIT license: https://github.com/OrchapodAI/orchapod (default branch main).
- Feedback: `docs/feedback.md`. TODO(D8): re-check the pages it cites, then paste it into the Devpost field and link it on GitHub.

## Testing instructions

No login and no key.

1. Open https://app.orchapod.dev/agent and press **Run** on *Synthetic movie likes, shares and subscribes*: a reduced plan that runs within the visitor caps (about a minute, under a cent) and ends with Super's report.
2. Or type a sentence and press **Plan**: Nemotron 3 Super drafts the pipeline, and the plan card shows its nodes, models and estimate.
3. The fine-tune runs, with their eval views, judged samples and reports: [6bf36882](https://app.orchapod.dev/runs/6bf36882-b221-4b63-9890-181101b6395f) (the video), [0ee1e20a](https://app.orchapod.dev/runs/0ee1e20a-468f-4651-8eee-c39fd094a804) and [d20d30f3](https://app.orchapod.dev/runs/d20d30f3-768f-4989-b974-cac3d9b47495).

## Gallery

Upload these in this order, each with its caption. Items 2 to 12 come from the rehearsal run 0ee1e20a on the hosted app, and item 13 from the multi-state run ca9838b7.

1. `docs/img/templates.png`: the public template gallery on app.orchapod.dev, each template with its estimate.
2. `docs/img/agent-plan.png`: Nemotron 3 Super's live plan for the golden sentence: six nodes, $2.66, no errors.
3. `docs/img/run-view-train.png`: NVIDIA Nemotron Nano 8B training on an H100 Nebius Serverless Job (RUNNING).
4. `docs/img/run-view.png`: base and LoRA served from one L40S Nebius Serverless Endpoint (RUNNING).
5. `docs/img/loss-chart.png`: the training loss over 60 steps.
6. `docs/img/eval-view.png`: Nemotron 3 Ultra's verdicts on 30 held-out questions: 7 wins, 20 ties, 3 losses.
7. `docs/img/eval-sample.png`: one judged sample, with the reference answer and both answer orders.
8. `docs/img/playground.png`: base and tuned side by side on a held-out question.
9. `docs/img/run-report.png`: Super's report of the run.
10. `docs/img/run-finished.png`: the finished run: $1.581 against the $2.66 estimate, and its artifacts.
11. `docs/img/canvas.png`: the plan on the canvas, each node coloured by its status.
12. `docs/img/run-logs.png`: every node's log lines, kept after the run.
13. `docs/img/multistate-eval.png`: the multi-state run judged on CPU: 11 wins, 19 ties, 0 losses on held-out rows of its own synthetic set.

## What changed during the submission period

Orchapod predates the submission period (Aug 26 – Oct 30, 2026): its first commit is May 4, 2026 (367c605), and `git log --before=2026-08-26` lists everything that existed before. That includes the React Flow canvas and YAML workflow format, the FastAPI control plane and DAG executor, the node SDK, the data-prep, hf-download, unsloth-train, distill-sft, quantize, lm-eval and vllm-serve nodes, run pages with live logs, a Try-it chat with an endpoint countdown, and a Vast.ai GPU provider that is not on the demo path.

During the period (the dated list is `CHANGELOG.md`):

- Oct 2 to 8: the first Nebius × NVIDIA integration: a Token Factory service, a Nebius provider, the Nemotron 3 Super teacher node (`synth-distilabel`), Token Factory model ids verified against the live catalog, executor fixes (database commits, `NEBIUS_API_KEY` forwarding, the container SDK) that let a CPU workflow run end to end, and quick-start docs.
- Oct 20: the Orchapod Agent (one sentence in, a validated Nemotron plan with cost and time estimates out; runs monitored and reported; spend caps per run and per day); Tavily web research, grounded and structured synthetic data, and Token Factory fine-tune and deploy nodes (the deploy node was retired after spike 1); one Token Factory client and one Tavily client; a run engine with retry, cancel, restart recovery and cost roll-up; the Agent page and a run page with a live cost meter; the Lane B student chosen by experiment; repo clean-up, interface contracts v1 (`docs/contracts.md`), the Agent's knowledge base (`docs/agent_knowledge.md`) and a green `make check` in CI.
- Oct 21: the evaluation (Nemotron 3 Ultra judges base against tuned in both orders) and its eval view; intent #3's CPU quantization with an f16 baseline, plus a fix for llama.cpp garbling f16 answers on Apple silicon; the compare playground; four one-click templates with reduced "Run it yourself" versions; the data-prep quality filter; the Serverless Endpoint serving node and the GPU training container; public-demo hardening (rate limits, an origin allow-list, deep health checks, GPU nodes for the admin only, secret-looking inputs never stored); hosting files for one VM, not deployed yet; stub end-to-end tests of the three intents, a browser smoke test that runs a template card on stubs through to the eval view and the compare playground, and failure drills.
- Oct 22: the first live runs, through the Agent on real Token Factory: intent #2 (Nemotron 3 Super planned it and wrote the report; 928 rows, 446 s, $0.10 in all) and intent #3 (a 3.1 GB maths model quantized to 0.99 GB on CPU in 75 s and judged by Nemotron 3 Ultra; $0.02), whose first attempt showed that Super's live plan can omit a dataset config, which data-prep now picks; run reports written by Super in the background when a run ends; the docs-specialist template, which trains NVIDIA Nemotron Nano 8B (Lane B) and serves base and LoRA from one L40S endpoint ($2.66 estimated), and its CPU variant without an endpoint; Token Factory's per-token LoRA deploy retired (410), so `vllm-serve` serves fine-tunes; `make agent-e2e` for one live intent with hard caps and `make e2e` for the live golden run on the hosted API; the golden path end to end in stub mode, through the Agent API and from its template card; keys passed to node containers by name only; a fresh clone green in under 7 minutes (warm caches).
- Oct 24: the golden path's data half live on real services: Tavily extracted 20 Nebius docs pages, Nemotron 3 Super wrote 300 grounded Q&A pairs from them, each with its source passage and URL, and data prep validated them (154 s, $0.07 in all); the Tavily spike turned the 20 pages into 98 passages for 4 credits.
- Oct 25: the hosted demo, live at https://app.orchapod.dev and https://api.orchapod.dev (a Nebius VM, Object Storage, HTTPS); the golden path live end to end on Nebius, twice, from the hosted demo (Tavily research on the Nebius docs, 300 grounded Q&A pairs from Nemotron 3 Super, a LoRA fine-tune of NVIDIA Nemotron Nano 8B on an H100 Serverless Job, base and tuned served from one L40S Serverless Endpoint, and Nemotron 3 Ultra judging base against tuned on 30 questions): 7 wins, 22 ties and 1 loss in 24 minutes for $1.61, then, typed as one sentence on the hosted /agent page, 7 wins, 20 ties and 3 losses in 23.5 minutes for $1.58; a third live run, on real-estate compliance in five states, that quantized the trained student and judged it on CPU with no endpoint: 11 wins, 19 ties and 0 losses on 30 held-out questions from its own synthetic set, in 51 minutes for $1.35; run pages that keep every node's logs, say where each step runs (a Nebius Job or Endpoint with its live state) and show the Agent's report in a Report tab; on the public demo, a plan that needs rented GPUs comes back as planned, marked admin-only, with a link to its golden run.
- Oct 27: the canvas's cost check before a run lists only the steps that rent a GPU, at the GPU they rent (`vllm-serve`'s L40S at $1.55 an hour); before, every step showed an H100 at $4.50, and a run with no GPU step still asked for a confirmation. The demo video's run, a Q3 2026 bank-earnings analyst (`6bf36882`), and two fixes it led to: grounded synthetic data keeps only answers whose figures appear in their source passage, and a plan that fine-tunes, quantizes and judges on CPU compares the tuned model with the same 4-bit base.
- Oct 29: the code public at https://github.com/OrchapodAI/orchapod.
