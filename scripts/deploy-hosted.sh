#!/usr/bin/env bash
# Deploy this checkout to the hosted VM (docs/HOSTING.md "Deploy"): rsync it to /opt/orchapod without .git and whatever
# .gitignore names (.env, node_modules, .venv, worktrees), rebuild and restart the stack there, and append
# "<UTC time> <commit>" to /opt/orchapod/deploys.log (rollback reads it).
# Usage: ORCHAPOD_DEPLOY_HOST=<user>@<vm> scripts/deploy-hosted.sh
set -euo pipefail
host=${ORCHAPOD_DEPLOY_HOST:?set ORCHAPOD_DEPLOY_HOST=<user>@<vm>}
cd "$(dirname "$0")/.."
rev=$(git rev-parse --short HEAD)$(git diff --quiet HEAD || echo -dirty)

# The explicit excludes keep the VM's own files from --delete: the .gitignore filter alone does not (openrsync, tested).
rsync -az --delete --rsync-path="sudo rsync" \
  --exclude=.git --exclude=/.env --exclude=/nebius/ --exclude=/deploys.log --filter=':- .gitignore' \
  ./ "$host:/opt/orchapod/"
ssh "$host" "cd /opt/orchapod && sudo docker compose --env-file .env -f infra/docker-compose.prod.yml up -d --build --remove-orphans \
  && echo \"\$(date -u +%FT%TZ) $rev\" | sudo tee -a deploys.log"
