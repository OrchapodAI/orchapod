# Orchapod.ai

> From data to deployed model in 25 minutes. Under $5. Open source.

Orchapod is an open-source agentic orchestration platform for the full post-training lifecycle.
Type what you want your model to do — Orchapod generates the workflow, trains on the cheapest
available GPU, and gives you a live OpenAI-compatible endpoint.

**Demo:** Fine-tune Qwen3-4B → distill to 1.7B → quantize for Ollama + vLLM → evaluate all three → deploy. Total cost: ~$3.20.

---

## MVP pipeline (7 nodes)

```
data-prep → unsloth-train → distill-sft → quantize (GGUF + AWQ)
                                        → lm-eval
                                        → vllm-serve
```

---

## Repository structure

```
orchapod/
├── apps/
│   ├── web/                        # Next.js 15 frontend
│   │   ├── app/
│   │   │   ├── workflows/          # Workflow list + create
│   │   │   ├── canvas/[id]/        # Visual canvas editor (React Flow)
│   │   │   └── runs/[id]/          # Run viewer (live logs, eval report, chat box)
│   │   └── components/canvas/      # React Flow node components
│   └── api/                        # FastAPI control plane
│       ├── routes/                 # REST + WebSocket endpoints
│       ├── models/db.py            # SQLModel: Workflow, Run, NodeRun, Artifact
│       ├── agent/workflow_builder.py  # Claude Sonnet: NL → workflow YAML
│       └── executor/
│           ├── run_workflow.py     # Asyncio DAG executor
│           └── dag.py             # YAML → DAG compiler
│
├── packages/
│   ├── sdk-py/orchapod/            # Node SDK (used inside containers)
│   │   ├── io.py                   # read_inputs / write_output → R2
│   │   ├── log.py                  # Streaming logs to control plane
│   │   └── checkpoint.py          # Checkpoint every N steps → R2
│   ├── providers/                  # GPU provider adapters
│   │   ├── base.py                 # GPUProvider Protocol
│   │   ├── runpod.py              # Primary (official MCP)
│   │   └── vastai.py              # Fallback (community MCP, forked)
│   └── workflow-schema/models.py  # Pydantic node schemas + NODE_REGISTRY
│
├── containers/                     # One Dockerfile + run.py per node type
│   ├── data-prep/                  # CPU: load, validate, reformat to ChatML
│   ├── unsloth-train/             # GPU: LoRA SFT via Unsloth + TRL
│   ├── distill-sft/               # GPU: teacher inference → student SFT
│   ├── quantize/                  # CPU/GPU: GGUF (llama.cpp) + AWQ (AutoAWQ)
│   ├── lm-eval/                   # GPU: lm-evaluation-harness + LLM-as-judge
│   └── vllm-serve/                # GPU: OpenAI-compatible endpoint (stays alive)
│
├── infra/
│   ├── terraform/                  # Postgres, Redis, R2 buckets, control-plane
│   └── docker-compose.dev.yml     # Local dev (Postgres + Redis + MinIO + API)
│
├── scripts/
│   ├── seed-demo-workflow.py      # Seeds the YC demo workflow into DB
│   └── build-and-push-containers.sh  # Build + push all 6 images to GHCR
│
├── tests/
│   ├── e2e/                        # End-to-end on real GPU (CI on RunPod)
│   ├── workflow/                   # DAG compiler + executor unit tests
│   └── agent/                      # Agent tool-use tests (mocked)
│
└── docs/
    ├── NODE_CONTRACT.md            # ← Read this first if adding a node
    ├── WORKFLOW_SPEC.md            # YAML workflow schema reference
    └── ARCHITECTURE.md             # System architecture + key invariants
```

---

## Quick start (local dev)

```bash
# 1. Clone and install
git clone https://github.com/orchapod/orchapod
cd orchapod

# 2. Copy env template
cp .env.example .env
# Fill in: RUNPOD_API_KEY, VASTAI_API_KEY, ANTHROPIC_API_KEY

# 3. Start control-plane dependencies
docker compose -f infra/docker-compose.dev.yml up -d

# 4. Start API
cd apps/api && uvicorn main:app --reload

# 5. Start frontend
cd apps/web && pnpm dev

# 6. Seed demo workflow
python scripts/seed-demo-workflow.py

# Open http://localhost:3000
```

---

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Backend API | FastAPI + Python 3.12 | Same lang as ML stack |
| Workflow runtime | Custom asyncio + Redis | Prefect/Temporal too heavy for MVP |
| Database | PostgreSQL 16 | Runs, workflows, artifacts |
| Object storage | Cloudflare R2 | Zero egress fees for multi-GB checkpoints |
| Frontend | Next.js 15 + React Flow | React Flow = de-facto canvas library |
| Training | Unsloth + TRL | 2-5x faster, 80% less VRAM |
| Inference | vLLM 0.8 | Highest throughput, multi-LoRA built-in |
| Eval | lm-eval-harness + Claude judge | Standard benchmarks + free-form |
| Agent | Claude Sonnet 4.5 + tool use | NL → workflow YAML |
| GPU (primary) | RunPod official MCP | Reliable, mature API |
| GPU (fallback) | Vast.ai community MCP | Cheapest H100s |
| Auth | Clerk (alpha) | Zero-effort for MVP |
| Containers | GHCR | Free for OSS |

---

## License

Fair-code — free to self-host, source-available.
Commercial use above the free tier requires a license.
Modeled on [n8n's Sustainable Use License](https://github.com/n8n-io/n8n/blob/master/LICENSE.md).
