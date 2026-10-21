# Wave 4 report: data-w4 (role data-engineering)

**Branch:** hack/data-w4, based on NebiusHackathon @ 5d64ed1 (`git merge-base --is-ancestor 5d64ed1 HEAD` passed).

**Commits:**
- a93c629 docs(contracts): GET /agent/templates adds the Nebius docs specialist (PLAN's golden path)
- 81eca84 feat(agent): Nebius docs specialist template: 20 docs seed URLs, Llama 3.1 8B on Token Factory, reduced variant
- b472e58 docs(agent): the planner's expected plan for the Nebius docs specialist, with its 20 seed URLs

**Status:** item 1 is done in STUB. Nothing ran live because no keys are set.

**Cost:** $0. No model call and no Tavily call were made. The only network traffic was anonymous GETs of public docs pages and the two docs sitemaps.

## What was built (item 1: "Distill a Nebius docs specialist")

### The template
File: `apps/api/agent/templates/4-nebius-docs-specialist.json`.
- **Slug:** `nebius-docs-specialist`
- **Title:** "Llama 8B tuned as a Nebius docs specialist"
- **Intent:** "Distill a Nebius docs specialist: fine-tune Llama 3.1 8B on the Nebius AI Cloud and Token Factory docs"
- **Fields:** `rationale` (R20) and `reduced_inputs` (R22).

It copies intent #1's shape and its node ids: research, synth and prep, then finetune, **deploy** and evaluate. The brief's chain is:

1. **research** (web-research): `seed_urls` is the 20 pages below, with `max_pages` 20 and no queries.
2. **synth** (synth-distilabel, grounded): Super as teacher, `n_samples` 300, `max_usd` 0.5, `max_tokens` 800 (R18). The instructions ask for questions a developer building on Nebius would ask, answered in at most three sentences from the passage alone, with its exact names, commands and numbers.
3. **prep** (data-prep): chatml, `train_split` 0.8, `test_split` 0.1.
4. **finetune** (tf-finetune): `meta-llama/Llama-3.1-8B-Instruct`, `n_epochs` 2.
5. **deploy** (tf-deploy): `job` ← `finetune.job`.
6. **evaluate** (judge-eval): needs prep and deploy.
   - `test_data` ← `prep.test_jsonl`.
   - `base_model_ref` = the plain Token Factory id `meta-llama/Llama-3.1-8B-Instruct`, a form R20 allows.
   - `tuned_model_ref` ← `deploy.model_ref`.
   - Ultra judges, with `max_samples` 30.

**reduced_inputs:**
- research: `max_pages` 6, which reads the first 6 seeds. That is the minimum for one STUB test row, as data-w3 found.
- synth: `n_samples` 40, `max_usd` 0.05.
- finetune: `n_epochs` 1.
- evaluate: `max_samples` 5.

### The validator passes
The plan has no gpu node, so it needs no GPU provider. Both scales return `errors []`. The two warnings are the same at both scales:
- `finetune: no fine-tune price for meta-llama/Llama-3.1-8B-Instruct yet (spike 1); the estimate assumes $0.50`
- `deploy: per-token LoRA deploy is unverified until spike 1; if it fails, serve the lora_adapter with vllm-serve`

| Scale | Total | Time | research | synth | prep | finetune | deploy | evaluate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Full | $0.766 | 54.5 min | 0.032 | 0.09 | 0 | 0.50 | 0 | 0.144 |
| Reduced | $0.552 | 49.0 min | 0.016 | 0.012 | 0 | 0.50 | 0 | 0.024 |

`fits` is False for anonymous callers (cap $0.30) and True for an admin. So the docs template is admin-only at the default `ORCHAPOD_ANON_SCALE` 0.1, like real-estate.

### Agent knowledge and contract
- **docs/agent_knowledge.md:** one line, expected plan #4. It gives the chain, the base model, the deploy fallback, the judge-eval refs and the 20 seed URLs in full. The planner reads only this file and NODE_REGISTRY, so it can only propose the same seeds if they are listed here.
- **docs/contracts.md "Agent API":** the templates line now reads "the three canonical intents plus PLAN's golden path …". It was edited in place, in its own commit before the code, as backend-w4 does. No R number is added.

## Seed URLs: all 20 load today
WebFetch is not in my toolset. I made the equivalent GET with `curl -sS -L -A "Mozilla/5.0 (Macintosh)"` and stripped the HTML with a small script to measure the server-rendered `<main>` text.

Checked at 2026-10-21T12:40:57Z: every page answered **HTTP 200 with 0 redirects**, with server-rendered content. I picked the pages from each host's sitemap.xml.

Token Factory docs live on **docs.tokenfactory.nebius.com**; `docs.nebius.com/studio/` redirects to its quickstart. AI Cloud docs are on docs.nebius.com.

| # | URL | HTTP | Page title | Text chars |
| --- | --- | --- | --- | --- |
| 1 | https://docs.tokenfactory.nebius.com/post-training/how-to-fine-tune | 200 | Supervised Finetuning | 17,148 |
| 2 | https://docs.tokenfactory.nebius.com/post-training/models | 200 | Models for fine-tuning in Nebius Token Factory | 7,174 |
| 3 | https://docs.nebius.com/serverless/overview | 200 | About Serverless AI | 4,133 |
| 4 | https://docs.nebius.com/serverless/tutorials/deploy-model | 200 | Deploying a large language model and chatting with it by using Serverless AI endpoints | 6,808 |
| 5 | https://docs.nebius.com/serverless/quickstart/jobs | 200 | Getting started with Serverless AI jobs: Run nvidia-smi within a job | 7,753 |
| 6 | https://docs.nebius.com/serverless/pricing-quotas | 200 | Pricing and quotas in Serverless AI | 1,420 |
| 7 | https://docs.tokenfactory.nebius.com/post-training/datasets | 200 | Dataset formats for fine-tuning | 7,953 |
| 8 | https://docs.tokenfactory.nebius.com/ai-models-inference/dedicated-endpoints/custom-weights | 200 | Custom model weights (LoRA / custom-weight deploy: beta, on request) | 475 |
| 9 | https://docs.tokenfactory.nebius.com/ai-models-inference/dedicated-endpoints/overview | 200 | Overview (Dedicated endpoints) | 1,668 |
| 10 | https://docs.tokenfactory.nebius.com/ai-models-inference/overview | 200 | Overview (inference: available models, flavors) | 4,062 |
| 11 | https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits | 200 | Rate Limits & Scaling | 4,845 |
| 12 | https://docs.tokenfactory.nebius.com/other-capabilities/billing-new | 200 | Billing & Consumption | 4,705 |
| 13 | https://docs.nebius.com/serverless/jobs/manage | 200 | Managing jobs in Serverless AI | 21,639 |
| 14 | https://docs.nebius.com/serverless/quickstart/endpoints | 200 | Getting started with Serverless AI endpoints: Deploy an nginx server with authentication | 10,061 |
| 15 | https://docs.nebius.com/serverless/endpoints/manage | 200 | Managing endpoints in Serverless AI | 25,956 |
| 16 | https://docs.nebius.com/serverless/tutorials/fine-tuning | 200 | Fine-tuning a large language model by using a Serverless AI job and Axolotl | 7,902 |
| 17 | https://docs.nebius.com/object-storage/overview | 200 | About Object Storage | 4,320 |
| 18 | https://docs.nebius.com/object-storage/quickstart | 200 | How to get started with Object Storage: Create your first bucket | 6,524 |
| 19 | https://docs.nebius.com/overview/quotas | 200 | Quotas in Nebius AI Cloud | 2,781 |
| 20 | https://docs.nebius.com/compute/resources/quotas-limits | 200 | Quotas in Compute | 3,743 |

**Order matters.** The first 6 are what the reduced plan reads: TF fine-tuning, TF models, the Serverless overview, endpoint deploy, the jobs quickstart and pricing/quotas.

**Rough size of a live corpus.** This is an estimate from the HTML text divided by 2,000 chars; Tavily's `raw_content` will differ.
- Full plan: about 86 passages. Synth then makes up to 4 pairs per passage and stops at 300 rows.
- Reduced plan: about 25 passages, 2 pairs each, so about 40 rows. That splits 32/4/4 live.

**Candidates I fetched (all 200) and left out:**
- Post-training overview: thin.
- public-serverless: about region guarantees.
- TF quickstart: generic.
- Structured output & JSON.
- The August 2026 deprecation notice.
- Serverless jobs/failure.
- Object Storage AWS CLI.

## Tests (TDD: red with 8 failures before the template, then green)
**tests/api/test_agent.py** (backend's file, edited as the dispatch asked; 21 lines):
- The templates are the three canonical intents plus `DOCS`, in that order.
- The reduced estimates are `[0.83, 0.03, 0.02, 0.55]`.
- `fits` is `[False, True, True, False]` anonymously and all True for an admin.
- New test `test_the_docs_specialist_validates_at_both_scales_on_10_to_20_docs_pages`:
  - `review()` returns no errors on the full plan and on `planner.reduced()`.
  - There are 10–20 unique seeds, each matching `https://docs.(tokenfactory.)?nebius.com/<path>`.
  - Every seed appears in docs/agent_knowledge.md, the live planner's source.
- The STUB test zips `INTENTS + [DOCS]` with the templates using `strict=True`, so each canonical intent maps to its own template. "Distill a docs specialist" maps to the new template, and "make me a GGUF of a math model" still maps to maths.

**tests/containers/test_synth_distilabel.py** (data-eng's file):
- data-w3's `test_intent1_data_half_through_the_real_sdk` became `test_template_data_half_through_the_real_sdk`. It is parametrized over intent #1, the docs template, and the docs template with `reduced_inputs` applied, each × {STUB teacher, five-pair teacher}.
- It runs the real `orchapod.io` and the executor's `_resolve_inputs`, as before.
- For the docs template, the corpus URLs equal the seeds, and for the reduced plan the first 6 seeds.
- Splits:
  - Full: 16/2/2 (STUB) and 80/10/10 (five pairs).
  - Reduced: 5/0/1 and 24/3/3. There is always at least one test row for judge-eval.
- Stratification: every five-row source puts 4 rows in train and 1 in held-out.

**STUB planner mapping** (the same `max(word overlap)` rule; ties go to the earlier file, so `4-` sorts last):

| Intent | Template it maps to |
| --- | --- |
| Fine-tune Llama 3B on US real-estate compliance: … | real-estate-compliance |
| Generate synthetic data of movie likes, shares and subscribes | movie-engagement |
| Quantize a model which is an expert in maths | maths-quantize |
| make me a GGUF of a math model | maths-quantize |
| Distill a docs specialist | nebius-docs-specialist |
| Distill a Nebius docs specialist from docs.nebius.com and docs.tokenfactory.nebius.com | nebius-docs-specialist |
| Fine-tune a model on the Nebius documentation | nebius-docs-specialist |

**Mutation checks.** I broke the template three ways, ran the docs tests, then restored the file (cmp confirmed it):
- A 3B base: tf-deploy has no per-token LoRA, so the validator test failed.
- Reduced `max_pages` 4: both docs-reduced data-half cases failed.
- A seed with a trailing slash: the validator test and both docs data-half cases failed.

Removing the agent_knowledge.md line fails the knowledge guard.

## Proof
`python -m pytest tests/api/test_agent.py tests/containers/test_synth_distilabel.py -v -k "docs or canonical or reduced_scale or closest or data_half"` returned **10 passed**:
- `test_templates_are_the_three_canonical_intents_and_the_docs_specialist`
- `test_run_it_yourself_clones_each_template_at_reduced_scale`
- `test_the_docs_specialist_validates_at_both_scales_on_10_to_20_docs_pages`
- `test_stub_plans_with_the_closest_template_and_calls_nothing`
- `test_template_data_half_through_the_real_sdk`, six cases:
  - `[intent1-stub-teacher]` and `[intent1-five-pair-teacher]`
  - `[docs-stub-teacher]` and `[docs-five-pair-teacher]`
  - `[docs-reduced-stub-teacher]` and `[docs-reduced-five-pair-teacher]`

Both full files: 78 passed (73 before).

`make check` in the worktree:
- ruff: "All checks passed!"
- pytest: **603 passed**, 2 warnings, 13.2 s.
- Web tests: 22 pass, 0 fail.
- "SKIP stub e2e: set E2E=1 (orchestrator/integration only)".

## Not done, and its limits
- **Nothing ran live.** There are no keys. The seeds were checked by HTTP GET, not through Tavily.
- **The data half is proven in-process** through the real SDK, the same harness data-w3 used for intent #1. It did not run through Docker and the API, because `make check E2E=1` rebuilds the shared `orchapod/*:dev` images and is for the Orchestrator only.
- **The ML half did not run in STUB through the executor.** That half is tf-finetune → tf-deploy → judge-eval, and those are ml's nodes and tests.
  - What I did check by reading the code: judge-eval turns a bare id into a Token Factory ModelRef (`containers/judge-eval/run.py:90`) and accepts tf-deploy's `model_ref` URI. In STUB, tf-deploy skips its price check.
  - Once qa-w3 merges, the full STUB chain is one command (its free-text path): `python scripts/e2e_agent.py --stub --intent "Distill a Nebius docs specialist"`.

## For the Orchestrator

### Open questions and notes
1. **tf-deploy, not vllm-serve.** The dispatch note says intent #1 runs "→ tf-deploy →", but `1-real-estate-compliance.json` actually serves with **vllm-serve** (3B has no per-token LoRA).
   - I followed the brief's chain, tf-deploy, which is also PLAN's Lane A. The validator then forces a Llama 3.1 8B base (`SERVERLESS_LORA_BASES`), and that is PLAN's golden-path model.
   - If spike 1 shows that /v0/models refuses it, swap one node to intent #1's shape:
     - `serve` = vllm-serve with model `meta-llama/Llama-3.1-8B-Instruct`, `lora_adapter` ← `finetune.lora_adapter`, `keep_alive_min` 30.
     - judge-eval base/tuned ← `serve.base_model_ref` / `serve.model_ref`.
   - The swap costs about $0.78 more per full run (30 min of L40S) and needs GPU quota.
2. **The exact 8B id.** I used `meta-llama/Llama-3.1-8B-Instruct`: the TF how-to's example, TFFinetuneInputs' default and the contract's TF base ModelRef. TF's models page lists `meta-llama/Meta-Llama-3.1-8B-Instruct` instead.
   - Both ids are in `SERVERLESS_LORA_BASES`. Spike 1 decides.
   - Switching changes 3 strings: finetune `model`, judge-eval `base_model_ref` and the knowledge line.
3. **Live runs wait on spike 1's prices.** PRICES has no Llama-3.1-8B inference or fine-tune rate, so a live run would be refused in three places:
   - tf-finetune ("no fine-tune price");
   - tf-deploy, before deploying (`containers/tf-deploy/run.py:47`);
   - judge-eval's base answers.

   This is the same gap as intent #1's tf-finetune.
4. **`fits` should be recomputed after spike 1.** The $0.55 reduced estimate is mostly TYPICAL's placeholder of $0.50 for tf-finetune.
   - 40 rows over 1 epoch is about 12k trained tokens, which may price well under $0.30. The docs template could then run anonymously at scale 0.1.
   - Today it needs scale ≥ 0.2.
5. **No seeded golden run for this template.** frontend-w4's `fits === false` card links "watch the golden run" to `/runs?q=nebius-docs-specialist-llama-8b`, but the only seeded run (scripts/golden-run.json) is real-estate's.
   - If Hari picks the docs topic, `make demo`'s fixture must be re-recorded from the docs run. Until then the link finds nothing.
6. **No Token Factory "pricing" page in the docs.** TF prices live on nebius.com (a marketing page); the TF docs sitemap has none. Billing & Consumption (TF) and Serverless "Pricing and quotas" (AI Cloud) stand in. I kept to the docs hosts, as the brief asked.
7. **The reduced eval split is empty in STUB.** 6 rows split 5/0/1, so STUB tf-finetune runs without validation (`eval_data` empty = none, per the contract). A live reduced run has about 40 rows.
8. **Stale "three templates" wording outside my paths** (one-line fixes for their owners):
   - `apps/api/routes/agent.py:10` and the `planner.templates()` docstring (backend);
   - `apps/web/app/agent/page.tsx:43` comment (frontend).
   - README:143 ("one of the three intents above") is still true.
9. **qa-w3's e2e_agent.py** finds intent #1 as the first template containing tf-finetune. Sorted order (`1-` before `4-`) keeps that, so I did not change the script.

### DECISIONs to record
- DECISION 2026-10-21 (data-w4): the "Distill a Nebius docs specialist" template is Lane A per PLAN: tf-finetune on meta-llama/Llama-3.1-8B-Instruct → tf-deploy (per-token LoRA). If spike 1 refuses per-token LoRA for the 8B, the deploy node becomes vllm-serve + lora_adapter, as in intent #1.
- DECISION 2026-10-21 (data-w4): Token Factory seed pages come from docs.tokenfactory.nebius.com (docs.nebius.com/studio redirects there), and AI Cloud pages from docs.nebius.com. 20 seeds, all HTTP 200 on 2026-10-21.
- Board: data-engineering, "P0 D6 'Distill a Nebius docs specialist' template + reduced variant, validator clean, STUB data half, planner knowledge": DONE (data-w4; live waits on keys and spike 1).

## Files
- /Users/hari/src/orchapod-hack/.claude/worktrees/data-w4/apps/api/agent/templates/4-nebius-docs-specialist.json (new)
- /Users/hari/src/orchapod-hack/.claude/worktrees/data-w4/docs/agent_knowledge.md
- /Users/hari/src/orchapod-hack/.claude/worktrees/data-w4/docs/contracts.md
- /Users/hari/src/orchapod-hack/.claude/worktrees/data-w4/tests/api/test_agent.py
- /Users/hari/src/orchapod-hack/.claude/worktrees/data-w4/tests/containers/test_synth_distilabel.py

## Fix round 1 (2026-10-21)
**Commits:**
- a587b1f docs(contracts): data-prep keeps one test and one eval row from 3 rows on; the docs template's vllm-serve fallback
- 14a3f09 fix(data-prep): from 3 rows on a requested test or eval split keeps a row, from the largest source (G1)
- e73c646 fix(agent): docs specialist seeds carry prices: Compute and Object Storage pricing, Dedicated deploy API, manage pages last

This section supersedes the earlier seed table and the reduced split of 5/0/1.

### G1 blocker: real-estate's reduced plan had no test row (qa-w3)
I fixed the root cause in data-prep rather than turning the template knob. The fix covers every small run of any template, user-made plans included. It keeps real-estate's reduced research at 4 pages, and it touches no backend file.

What `split()` does now:
- **Floors.** From 3 rows on, a requested `test_split` keeps at least one row. So does an eval share above 0, with a tolerance of 1e-9, because 1 − 0.9 − 0.1 is 3e-17, not a share.
- **Where the rows come from.** They come off the end of the stratified order, which holds the largest sources' last rows.
- **Tie-break.** At equal positions the larger source now sorts later. Without it, the shape qa-w3 hit (a 3-row source plus a 1-row source, n=4) held out the 1-row source.
- **Below 3 rows** a split can still be empty, and the existing warning still fires.

| n at train/test | Before | After |
| --- | --- | --- |
| 2 at 0.8/0.1 | 2/0/0 | 2/0/0 |
| 3 at 0.8/0.1 | 2/1/0 | 1/1/1 |
| **4 at 0.8/0.1 (real-estate reduced, STUB)** | **3/1/0** | **2/1/1** |
| 4 at 0.9/0 | 4/0/0 | 3/1/0 |
| 5 at 0.9/0.1 | 4/1/0 | 4/0/1 |
| **6 at 0.8/0.1 (docs reduced, STUB)** | **5/0/1** | **4/1/1** |
| 12 at 0.8/0.1 | 10/1/1 | 10/1/1 |
| 20 at 0.8/0.1 | 16/2/2 | 16/2/2 |

Live runs of 20 rows or more are unchanged.

Through the real SDK in STUB, both templates' reduced data half now leaves judge-eval a row:
- `[intent1-reduced-stub-teacher]`: 4 rows → 2/1/1.
- `[docs-reduced-stub-teacher]`: 6 rows → 4/1/1.

The five-pair cases give 16/2/2 and 24/3/3, with every source putting 4 rows in train and 1 in held-out.

**Before re-running qa-w3's gallery check:** LocalDocker runs `orchapod/data-prep:dev`, so rebuild that shared image after the merge. `make check E2E=1` rebuilds it as part of intent #2.

### Seeds (all 20: HTTP 200, 0 redirects, 2026-10-21T13:08:51Z)
**Out:**
- the nginx endpoint quickstart;
- overview/quotas;
- the thin Dedicated-endpoints overview (1,668 chars), as the third swap.

**In:**
- Compute pricing (12,870 chars);
- Object Storage pricing (5,414 chars);
- TF dedicated-endpoints/deploy-api (4,185 chars).

**What deploy-api covers.** It has no LoRA-specific text. It is the Dedicated-endpoint API how-to: GET `/v0/dedicated_endpoints/templates`, POST `/v0/dedicated_endpoints`, `routing_key` and regional base URLs. That is the deploy path TF's models page names for Meta fine-tunes; custom weights there stay "beta, on request" (seed 8).

**Order.** The first six, which the reduced run reads, are unchanged. The two `manage` pages are now 19 and 20.

The final order:

| # | URL |
| --- | --- |
| 1 | https://docs.tokenfactory.nebius.com/post-training/how-to-fine-tune |
| 2 | https://docs.tokenfactory.nebius.com/post-training/models |
| 3 | https://docs.nebius.com/serverless/overview |
| 4 | https://docs.nebius.com/serverless/tutorials/deploy-model |
| 5 | https://docs.nebius.com/serverless/quickstart/jobs |
| 6 | https://docs.nebius.com/serverless/pricing-quotas |
| 7 | https://docs.tokenfactory.nebius.com/post-training/datasets |
| 8 | https://docs.tokenfactory.nebius.com/ai-models-inference/dedicated-endpoints/custom-weights |
| 9 | https://docs.tokenfactory.nebius.com/ai-models-inference/dedicated-endpoints/deploy-api |
| 10 | https://docs.tokenfactory.nebius.com/ai-models-inference/overview |
| 11 | https://docs.tokenfactory.nebius.com/ai-models-inference/rate-limits |
| 12 | https://docs.tokenfactory.nebius.com/other-capabilities/billing-new |
| 13 | https://docs.nebius.com/compute/resources/pricing |
| 14 | https://docs.nebius.com/object-storage/resources/pricing |
| 15 | https://docs.nebius.com/serverless/tutorials/fine-tuning |
| 16 | https://docs.nebius.com/object-storage/overview |
| 17 | https://docs.nebius.com/object-storage/quickstart |
| 18 | https://docs.nebius.com/compute/resources/quotas-limits |
| 19 | https://docs.nebius.com/serverless/jobs/manage |
| 20 | https://docs.nebius.com/serverless/endpoints/manage |

**What the 300-row cap trims.** Synth walks the corpus in order (`generate`, i = 0, 1, …) and stops at `n_samples`.
- My HTML measure gives about 65 passages before the `manage` pages and about 89 in all; your 47k-char measure of those two pages gives about 113.
- So k is 3 or 4 pairs per passage, every page before 19 is used in full, and the cap trims only the `manage` pages.
- This assumes Tavily returns extract results in request order. STUB does; live behaviour is for spike 3 to check.

**Instructions** now end: "Where a page lists prices by date, quote the latest (as listed after October 1, 2026), never an older one." The Compute page has three price columns: before Oct 1, Oct 1–8, and from Oct 8 (preemptible). "Latest" covers the Oct 8 change too.

**Estimates** are unchanged at $0.766 full and $0.552 reduced. They depend on `max_pages`, not on which pages are read.

### Minors
- **Knowledge line:**
  - It now names `n_samples` 300, `max_tokens` 800, `max_samples` 30 and the price-date rule.
  - It now says spike 1 settles the 8B spelling (`Meta-Llama-3.1-8B-Instruct` on TF's models page) and that PRICES is keyed by it.
  - The drift guard is now exact and ordered: `re.findall(r"https://docs\.[\w./-]*[\w-]", knowledge) == seeds`. agent_knowledge.md has no other docs URLs.
- **contracts.md:** the templates line adds "(or vllm-serve if spike 1 refuses per-token LoRA)". The data-prep `test_split` bullet states the floors.
- **test_agent.py:** checks that every template's estimate is under $3, not only templates[0].
- **test_synth_distilabel.py:** uses `planner.reduced(template)["plan"]`, and adds the intent #1 reduced case.

### Proof
- **Covering tests** (`pytest tests/containers/test_synth_distilabel.py tests/containers/test_data_prep.py tests/api/test_agent.py -v -k "data_half or keeps_a_row or largest_source or empty_requested or docs or canonical or reduced_scale or closest"`): **22 passed**. That is the data half ×8 (intent1, intent1-reduced, docs and docs-reduced, each with both teachers), the split table ×8, largest-source, the empty-split warning, and the four agent template tests.
- **`make check`:** ruff "All checks passed!", **610 passed** (2 warnings), 22 web tests pass, stub e2e SKIP (orchestrator only).
- **Mutation checks** (each restored, confirmed by cmp):
  - With no floor: 8 failures, including the intent1-reduced and docs-reduced STUB data halves.
  - With no size tie-break: the largest-source test fails.
  - With the two `manage` seeds swapped in the template only: the drift guard fails.

**Cost:** $0.
