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
| Synthetic training data teacher | **Nemotron Super 120B** via **Nebius Token Factory** |
| Base model to fine-tune | **Nemotron Mini 4B** from HuggingFace |
| LLM-as-judge (lm-eval) | **Nemotron Ultra 253B** via **Nebius Token Factory** |
| Data quality scoring | Cleanlab TLM (CPU, runs locally) |
| CPU nodes (import, prep, synth) | LocalDockerProvider — no GPU API key needed |
| One-command local stack | docker-compose.dev.yml (Postgres + Redis + MinIO + API + Web) |

**The full demo pipeline:**
```
HF Import (databricks/dolly-15k from HuggingFace)
  → Synth Data (Nemotron Super 120B as teacher — generates 1K synthetic rows via Token Factory)
    → Data Prep (format, dedup, split)
      → HF Download (Nemotron Mini 4B model)
        → Unsloth Train (LoRA SFT on Nebius H100)
          → LM-Eval (benchmarks + Nemotron Ultra judge via Token Factory)
          → vLLM Serve (OpenAI endpoint on Nebius)
```

**Nemotron is used at every intelligence layer:**
- **Nemotron Super 120B** → synthetic training data generation (teacher)
- **Nemotron Mini 4B** → the model being fine-tuned (student)
- **Nemotron Ultra 253B** → evaluation judge (Token Factory, no GPU needed)

---

## Quick start (hackathon demo)

### Prerequisites
- macOS or Linux
- [Colima](https://github.com/abiosoft/colima) or Docker Desktop (for container runtime)
- Python 3.12+
- Node.js 20+ and pnpm
- Homebrew (macOS) for Redis and MinIO

### 1. Get your credentials

| Service | Where to get it |
|---------|----------------|
| **Nebius Token Factory key** | [studio.nebius.ai](https://studio.nebius.ai) → API Keys |
| **Nebius IAM token** | `nebius iam get-access-token` (after `nebius profile create`) |
| **Nebius Folder/Project ID** | `nebius iam project list` — shows the project ID |

### 2. Clone and configure

```bash
git clone https://github.com/bangadpurva/orchapod
cd orchapod
git checkout NebiusHackathon

cp .env.example .env
```

Edit `.env` — minimum required:

```bash
# Nebius Token Factory — Nemotron inference (OpenAI-compatible)
NEBIUS_API_KEY=your_key_from_studio.nebius.ai

# Nebius AI Cloud — GPU compute for training/serving
NEBIUS_IAM_TOKEN=your_iam_token
NEBIUS_FOLDER_ID=your_project_id   # e.g. aiproject-e00xxxxx

# Postgres
DATABASE_URL=postgresql+asyncpg://postgres:orchapod@localhost:5432/orchapod

# MinIO (local R2 stand-in)
ORCHAPOD_R2_ENDPOINT=http://host.docker.internal:9000
ORCHAPOD_R2_ACCESS_KEY=orchapod
ORCHAPOD_R2_SECRET_KEY=orchapod_dev
ORCHAPOD_R2_BUCKET=orchapod-artifacts

# Control plane URL (used by containers to report artifacts)
ORCHAPOD_CONTROL_URL=http://host.docker.internal:8000
```

### 3. Start Docker runtime (macOS — use Colima, no Docker Desktop needed)

```bash
brew install colima docker docker-compose
colima start --cpu 4 --memory 8

# Point Docker at Colima socket
export DOCKER_HOST="unix://${HOME}/.colima/default/docker.sock"
# Make permanent:
echo 'export DOCKER_HOST="unix://${HOME}/.colima/default/docker.sock"' >> ~/.zshrc
```

### 4. Start infrastructure

```bash
# Postgres
docker run -d --name orchapod-pg \
  -e POSTGRES_PASSWORD=orchapod -e POSTGRES_DB=orchapod \
  -p 5432:5432 postgres:16

# Redis (Homebrew — avoids Docker Hub auth)
brew install redis && brew services start redis

# MinIO (Homebrew — avoids Docker Hub auth)
brew install minio
MINIO_ROOT_USER=orchapod MINIO_ROOT_PASSWORD=orchapod_dev \
  /opt/homebrew/opt/minio/bin/minio server --address=:9000 /tmp/minio-data &

# Create the artifacts bucket (run once)
python3 -c "
import boto3
from botocore.client import Config
s3 = boto3.client('s3', endpoint_url='http://localhost:9000',
    aws_access_key_id='orchapod', aws_secret_access_key='orchapod_dev',
    config=Config(signature_version='s3v4'), region_name='us-east-1')
s3.create_bucket(Bucket='orchapod-artifacts')
print('Bucket ready')
"
```

### 5. Start API and frontend

```bash
# Install Python deps
pip3 install -r apps/api/requirements.txt

# Run DB migrations
PYTHONPATH=apps DATABASE_URL=postgresql+asyncpg://postgres:orchapod@localhost:5432/orchapod \
  python3 -m alembic -c apps/api/alembic.ini upgrade head

# Start API (from repo root)
set -a && source .env && set +a
DATABASE_URL=postgresql+asyncpg://postgres:orchapod@localhost:5432/orchapod \
DOCKER_HOST="unix://${HOME}/.colima/default/docker.sock" \
PYTHONPATH=apps uvicorn api.main:app --port 8000
# → http://localhost:8000  (Swagger: http://localhost:8000/docs)

# Start frontend (separate terminal)
cd apps/web && pnpm install && pnpm dev
# → http://localhost:3000
```

### 6. Build the synth-distilabel container

CPU nodes run locally via Docker. Build the container once:

```bash
docker build -t ghcr.io/orchapod/synth-distilabel:latest \
  containers/synth-distilabel/
```

### 7. Run the demo workflow

Open `http://localhost:3000/workflows`, click **+ New Workflow**, then drag these nodes onto the canvas:

1. **HF Import** — `dataset_id: databricks/databricks-dolly-15k`
2. **Synth Data** — `teacher_kind: nebius`, `teacher_model: nvidia/nemotron-3-super-120b-a12b`, `n_samples: 1000`  *(uses Nemotron Super as teacher via Token Factory)*
3. **Data Prep** — `dataset` = output of step 2, `format: chatml`
4. **HF Download** — `model_id: nvidia/Nemotron-Mini-4B-Instruct`
5. **Train** — base model from step 4, train data from step 3
6. **LM-Eval** — judge model: `nvidia/Nemotron-3-Ultra-550b-a55b`
7. **vLLM Serve** — model from step 5

Click **▶ Run** → approve the Nebius cost estimate → watch live logs → open the "Try it" chat tab.

---

## What Nebius Token Factory enables

The `lm-eval` node now uses **Nemotron Ultra 253B** as the evaluation judge instead of a closed-source model. This means:

- The entire pipeline — training, evaluation, and serving — runs on **NVIDIA open-source models**
- The judge call is a single HTTP request to `https://api.studio.nebius.ai/v1/chat/completions`
- No GPU required for evaluation judging (Token Factory handles inference)
- Nemotron Super 120B is available as a faster/cheaper judge option via the `judge_model` input

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
