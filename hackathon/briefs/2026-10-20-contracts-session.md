# Brief — contracts session (2026-10-20) · agents: platform, data-engineering, ml-engineering, backend
Repo: /Users/hari/src/orchapod-hack (NebiusHackathon @ c866d7f). Read-only task: do not edit code, do not commit, do not dispatch subagents.

## Task
Propose the contract text for your area, grounded in the code that exists today. Read first: your role file (.claude/agents/<role>.md), docs/contracts.md (the skeleton you are replacing), docs/NODE_CONTRACT.md, docs/agent_knowledge.md, hackathon/ORCHESTRATOR.md §3–§4, and the code in your area.
Write your proposal to hackathon/briefs/2026-10-20-contracts-<role>.md: at most 80 lines of markdown, ready to paste into docs/contracts.md (exact names, fields, types, env vars, error behaviour), then "Open questions" (at most 5 lines). Where today's code disagrees with the skeleton, say which wins and why. Prefer what exists over new shapes.

## Your area
- platform: provider interfaces with signatures and return shapes — TokenFactory (chat, stream_chat, guided JSON, files, fine-tuning create/poll/events/checkpoints, LoRA deploy/status/delete, per-call usage and $), Tavily (search, extract, credits), NebiusServerless (jobs, endpoints) and ObjectStorage; error and retry policy (rate limit, quota, 5xx); config: every env var (including ORCHAPOD_IMAGE_PREFIX and the budget caps) with its default. Code: apps/api/services/nebius_token_factory.py, apps/api/services/provider_selector.py, packages/providers/, .env.example.
- data-engineering: node I/O for web-research, synth-distilabel (grounded and structured modes: how a schema is passed, row formats for chat JSONL vs structured rows), data-prep (splits, stats.json); dataset schemas in packages/workflow_schema; the cost.json and metrics.json fields these nodes emit. Code: containers/synth-distilabel, containers/data-prep, packages/workflow_schema, packages/sdk-py.
- ml-engineering: node I/O for tf-finetune, tf-deploy, judge-eval (eval_summary.json and the per-sample verdict schema), quantize, hf-download, and Lane B train/serve; one "model ref" format that Evaluate and the playground both accept (TF base id, TF LoRA model name, endpoint URL + token). Code: containers/unsloth-train, vllm-serve, quantize, hf-download, lm-eval.
- backend: the run/node state machine as the executor implements it today vs what long-polling nodes, cancel and retry-node need; SDK conventions (cost.json, metrics.json, progress); the events the UI and the agent monitor consume; Agent API request/response JSON for POST /agent/plan, POST /agent/run, GET /agent/runs/{id}/report, and how a plan maps onto the existing workflow spec. Code: apps/api/executor, apps/api/routes, apps/api/models, apps/api/agent, packages/sdk-py, docs/WORKFLOW_SPEC.md.

## Done when
The proposal file exists. Final message at most 10 lines: file path, the three most important interface choices, open questions.
