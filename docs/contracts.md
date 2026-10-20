# Contracts (change here first; every agent reads this)
## Node I/O
- Inputs: ORCHAPOD_NODE_INPUTS JSON; outputs: io.write_output(name, path, kind, metadata); every node also writes cost.json {provider, model, in_tokens, out_tokens, usd} and metrics.json.
- Runtimes: cpu (local Docker), gpu (Nebius Serverless Job), api (CPU container that only calls APIs: tf-finetune, tf-deploy, judge-eval, serverless-endpoint).
- Artifact URIs: r2://<bucket>/runs/{run_id}/{node_id}/{name} (MinIO locally, Nebius Object Storage on Nebius).
## New nodes (inputs → outputs)
- web-research: seed_urls | query, max_pages → corpus.jsonl
- synth-distilabel (grounded + structured modes): corpus | schema, n_rows, teacher_model → dataset.jsonl, cost_summary.json
- tf-finetune: train_jsonl, val_jsonl, base_model, epochs, lora → job_id, checkpoint_id, loss_curve.json
- tf-deploy: job_id, checkpoint_id, base_model → model_name
- judge-eval: test_jsonl, base_model_ref, tuned_model_ref, judge_model → eval_summary.json (win/tie/loss, per-sample verdicts)
- serverless-train / serverless-endpoint (Lane B): see platform provider interface
## Provider interfaces
- TokenFactory: chat(), stream_chat(), files.create(), fine_tuning.create/poll/checkpoints(), lora.deploy()/status()/delete()
- Tavily: search(), extract()
- NebiusServerless: jobs.create/get/cancel/delete(), endpoints.create/get/delete(); ObjectStorage: put/get/list
## Run state machine
PENDING → RUNNING → (per node: RUNNING → SUCCEEDED | FAILED) → SUCCEEDED | FAILED | CANCELLED; retry-node re-runs one failed node idempotently.
## Agent API
POST /agent/plan, POST /agent/run, GET /agent/runs/{id}/report — JSON shapes TBD by backend on D2, reviewed by frontend.
