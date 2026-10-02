# Orchapod.ai

> Fine-tune NVIDIA Nemotron on Nebius AI Cloud. Deploy to a live endpoint. In 25 minutes. Under $5.

Orchapod is an open-source drag-and-drop workflow platform for the full LLM post-training lifecycle —
dataset prep → LoRA fine-tune → distillation → quantization → evaluation → live serving.

**Powered by NVIDIA Nemotron models on Nebius AI Cloud.**  
**Evaluated by Nemotron Ultra via Nebius Token Factory.**

[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Nebius x NVIDIA Hackathon

**Track:** Best Apps and Agents

**How Orchapod uses Nebius + NVIDIA:**

| Component | Nebius / NVIDIA technology |
|-----------|---------------------------|
| GPU compute (training, serving) | **Nebius AI Cloud** — H100 SXM instances, eu-north1 |
| Synthetic training data teacher | **Nemotron Super 49B** via **Nebius Token Factory** |
| Base model to fine-tune | **Nemotron Mini 4B** from HuggingFace |
| LLM-as-judge (lm-eval) | **Nemotron Ultra 253B** via **Nebius Token Factory** |
| Data quality scoring | Cleanlab TLM (CPU, runs locally) |
| CPU nodes (import, prep, synth) | LocalDockerProvider — no GPU API key needed |
| One-command local stack | docker-compose.dev.yml (Postgres + Redis + MinIO + API + Web) |

**The full demo pipeline:**
```
HF Import (databricks/dolly-15k from HuggingFace)
  → Synth Data (Nemotron Super 49B as teacher — generates 1K synthetic rows via Token Factory)
    → Data Prep (format, dedup, split)
      → HF Download (Nemotron Mini 4B model)
        → Unsloth Train (LoRA SFT on Nebius H100)
          → LM-Eval (benchmarks + Nemotron Ultra judge via Token Factory)
          → vLLM Serve (OpenAI endpoint on Nebius)
```

**Nemotron is used at every intelligence layer:**
- **Nemotron Super 49B** → synthetic training data generation (teacher)
- **Nemotron Mini 4B** → the model being fine-tuned (student)
- **Nemotron Ultra 253B** → evaluation judge (Token Factory, no GPU needed)

---

## Quick start (hackathon demo)

### Prerequisites
- Docker (for Postgres + Redis)
- Python 3.12+
- Node.js 20+ and pnpm

### 1. Get your credentials

| Service | Where to get it |
|---------|----------------|
| **Nebius Token Factory key** | [studio.nebius.ai](https://studio.nebius.ai) → API Keys |
| **Nebius IAM token** | Nebius Console → IAM → Service Accounts → `nebius iam get-access-token` |
| **Nebius Folder ID** | Nebius Console → top-left dropdown |

### 2. Clone and configure

```bash
git clone https://github.com/bangadpurva/orchapod
cd orchapod
git checkout NebiusHackathon

cp .env.example .env
```

Edit `.env` — minimum required for the demo:

```bash
# Nebius Token Factory — Nemotron inference (OpenAI-compatible)
NEBIUS_API_KEY=your_key_from_studio.nebius.ai

# Nebius AI Cloud — GPU compute for training/serving
NEBIUS_IAM_TOKEN=your_iam_token
NEBIUS_FOLDER_ID=your_folder_id

# Local Postgres
DATABASE_URL=postgresql+asyncpg://postgres:orchapod@localhost:5432/orchapod
```

### 3. Start infrastructure (one command)

```bash
# Starts Postgres, Redis, MinIO, API, and the Next.js frontend
docker compose -f infra/docker-compose.dev.yml up -d
```

This runs everything. MinIO serves as a local R2 stand-in (S3-compatible). CPU nodes (HF Import, Synth Data, Data Prep) run via LocalDockerProvider — no GPU API key needed.

**OR** start services manually:

```bash
# Postgres + Redis + MinIO
docker run -d --name orchapod-pg -e POSTGRES_PASSWORD=orchapod -e POSTGRES_DB=orchapod -p 5432:5432 postgres:16
docker run -d --name orchapod-redis -p 6379:6379 redis:7
docker run -d --name orchapod-minio -e MINIO_ROOT_USER=orchapod -e MINIO_ROOT_PASSWORD=orchapod_dev -p 9000:9000 minio/minio server /data
```

```bash
# API
pip install -r apps/api/requirements.txt
cd apps/api && alembic upgrade head
uvicorn api.main:app --reload
# → http://localhost:8000  (Swagger: http://localhost:8000/docs)
```

```bash
# Frontend
cd apps/web && pnpm install && pnpm dev
# → http://localhost:3000
```

### 6. Run the demo workflow

Open `http://localhost:3000/workflows`, click **+ New Workflow**, then drag these nodes onto the canvas:

1. **HF Import** — `dataset_id: databricks/databricks-dolly-15k`
2. **Synth Data** — `teacher_kind: nebius`, `teacher_model: nvidia/Llama-3.3-Nemotron-Super-49B-v1`, `n_samples: 1000`  *(uses Nemotron Super as teacher via Token Factory)*
3. **Data Prep** — `dataset` = output of step 2, `format: chatml`
4. **HF Download** — `model_id: nvidia/Nemotron-Mini-4B-Instruct`
5. **Train** — base model from step 4, train data from step 3
6. **LM-Eval** — judge model: `nvidia/Llama-3.1-Nemotron-Ultra-253B-v1`
7. **vLLM Serve** — model from step 5

Click **▶ Run** → approve the Nebius cost estimate → watch live logs → open the "Try it" chat tab.

---

## What Nebius Token Factory enables

The `lm-eval` node now uses **Nemotron Ultra 253B** as the evaluation judge instead of a closed-source model. This means:

- The entire pipeline — training, evaluation, and serving — runs on **NVIDIA open-source models**
- The judge call is a single HTTP request to `https://api.studio.nebius.ai/v1/chat/completions`
- No GPU required for evaluation judging (Token Factory handles inference)
- Nemotron Super 49B is available as a faster/cheaper judge option via the `judge_model` input

To use Token Factory directly from the Inference page, pick any Nemotron model (shown with ⚡ chips at the top) and click Deploy.

---

## Architecture

```
orchapod/
├── apps/
│   ├── web/                        # Next.js 15 frontend (React Flow canvas)
│   └── api/                        # FastAPI control plane
│       ├── routes/                 # REST + WebSocket endpoints
│       └── executor/               # Asyncio DAG runner
│
├── packages/
│   ├── providers/
│   │   ├── nebius.py               # ← NEW: Nebius AI Cloud GPU provider
│   │   └── vastai.py               # Fallback GPU provider
│   └── workflow-schema/models.py  # Node types + resource specs
│
├── containers/                     # One container per node type
│   ├── lm-eval/run.py              # ← UPDATED: Nemotron Ultra judge via Token Factory
│   └── vllm-serve/                 # OpenAI-compatible endpoint
│
└── apps/api/services/
    └── nebius_token_factory.py     # ← NEW: Token Factory client
```

**Provider priority:** Nebius AI Cloud → Vast.ai fallback (set by `provider_pref` in ResourceSpec).

---

## Tech stack

| Layer | Choice |
|-------|--------|
| GPU compute | **Nebius AI Cloud** (H100 SXM, eu-north1) |
| LLM models | **NVIDIA Nemotron** (Mini 4B · Super 49B · Ultra 253B) |
| Inference API | **Nebius Token Factory** (OpenAI-compatible) |
| Training | Unsloth + TRL (2–5× faster LoRA SFT) |
| Serving | vLLM 0.8 (OpenAI-compatible endpoint) |
| Evaluation | lm-evaluation-harness + Nemotron Ultra judge |
| Backend | FastAPI + Python 3.12 + PostgreSQL |
| Frontend | Next.js 15 + React Flow |
| Storage | Cloudflare R2 (zero-egress model artifacts) |
| Auth | Clerk (alpha) |

---

## License

[MIT](LICENSE) — open source, free to use and self-host.
