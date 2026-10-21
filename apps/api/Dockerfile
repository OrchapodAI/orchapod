# Production API image for infra/docker-compose.prod.yml (docs/HOSTING.md); Dockerfile.dev is the --reload variant.
# Build from the repo root: docker build -f apps/api/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# The docker CLI only: cpu and api nodes run as sibling containers through the host's /var/run/docker.sock.
COPY --from=docker:28.5.1-cli /usr/local/bin/docker /usr/local/bin/docker

# The nebius CLI (R15: IAM tokens for Serverless Jobs and Endpoints). Installing needs no login; the service-account
# profile is mounted at /root/.nebius at run time. Same binary as Nebius's install.sh fetches, pinned by version and by
# the sha256 of each arch's binary (Nebius publishes none; taken 2026-10-21).
RUN arch=$(uname -m | sed s/aarch64/arm64/) \
    && case "$arch" in \
         x86_64) sum=a4176af5d90c7efd8dbcd938d087dd43b749e6cb131746332870c79aa421d026 ;; \
         arm64) sum=aca84ec8caf4661152b74f4cc10a87cb6a0591c5fd4fd0de8b52e0b1bca82a35 ;; \
       esac \
    && curl -fsSL "https://artifacts.nebius.cloud/cli/release/0.12.293/linux/${arch}/nebius" -o /usr/local/bin/nebius \
    && echo "${sum}  /usr/local/bin/nebius" | sha256sum -c - \
    && chmod +x /usr/local/bin/nebius && nebius version

COPY apps/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/api /app/api
COPY packages /app/packages
# the planner reads it on every request (apps/api/agent/planner.py)
COPY docs/agent_knowledge.md /app/docs/agent_knowledge.md

# api.* and packages.* from /app; orchapod (the SDK's price table, which the provider clients import) from packages/sdk-py
ENV PYTHONPATH=/app:/app/packages/sdk-py

EXPOSE 8000
# Runs as root on purpose: /var/run/docker.sock is root-equivalent on the host anyway, and the nebius CLI reads its
# profile from /root/.nebius. One worker: budget reservations and rate limits live in this process (R20).
# Only Caddy reaches this port, and it replaces X-Forwarded-For, so trusting it gives the real client IP and https URLs.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips", "*"]
