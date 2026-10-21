# Production API image for infra/docker-compose.prod.yml (docs/HOSTING.md); Dockerfile.dev is the --reload variant.
# Build from the repo root: docker build -f apps/api/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# The docker CLI only: cpu and api nodes run as sibling containers through the host's /var/run/docker.sock.
COPY --from=docker:28.5.1-cli /usr/local/bin/docker /usr/local/bin/docker

# The nebius CLI (R15: IAM tokens for Serverless Jobs and Endpoints). Installing needs no login; the service-account
# profile is mounted at /root/.nebius at run time. Same binary as Nebius's install.sh fetches, pinned.
RUN arch=$(uname -m | sed s/aarch64/arm64/) \
    && curl -fsSL "https://artifacts.nebius.cloud/cli/release/0.12.293/linux/${arch}/nebius" -o /usr/local/bin/nebius \
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
# One worker: budget reservations and rate limits live in this process (R20). Only Caddy reaches this port, and it
# replaces X-Forwarded-For, so trusting it gives the real client IP and https URLs.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips", "*"]
