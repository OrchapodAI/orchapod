#!/usr/bin/env bash
# Deploy this checkout to the hosted VM (docs/HOSTING.md "Deploy"): rsync it to /opt/orchapod without .git and whatever
# .gitignore names (.env, node_modules, .venv, worktrees), rebuild and restart the stack there, append
# "<UTC time> <commit>" to /opt/orchapod/deploys.log (rollback reads it), and refresh the node images.
# Usage: ORCHAPOD_DEPLOY_HOST=<user>@<vm> scripts/deploy-hosted.sh
set -euo pipefail
host=${ORCHAPOD_DEPLOY_HOST:?set ORCHAPOD_DEPLOY_HOST=<user>@<vm>}
cd "$(dirname "$0")/.."
rev=$(git rev-parse --short HEAD)$([ -z "$(git status --porcelain)" ] || echo -dirty)

# The explicit excludes keep the VM's own files from --delete: the .gitignore filter alone does not (openrsync, tested).
rsync -az --delete --rsync-path="sudo rsync" \
  --exclude=.git --exclude=/.env --exclude=/nebius/ --exclude=/deploys.log --filter=':- .gitignore' \
  ./ "$host:/opt/orchapod/"
# docker run pulls a node image only when it is missing, so the deploy pulls each :latest the VM already has. A gpu node's
# image runs on Nebius and never lands here; a missing one is pulled fresh at its first run.
ssh "$host" "cd /opt/orchapod && sudo docker compose --env-file .env -f infra/docker-compose.prod.yml up -d --build --remove-orphans \
  && echo \"\$(date -u +%FT%TZ) $rev\" | sudo tee -a deploys.log \
  && prefix=\$(sudo sed -n 's/^ORCHAPOD_IMAGE_PREFIX=//p' .env) && for d in containers/*/; do \
     img=\${prefix:-ghcr.io/bangadpurva}/\$(basename \$d):latest; \
     if sudo docker image inspect \$img >/dev/null 2>&1; then sudo docker pull -q \$img || echo \"could not pull \$img\"; fi; done"
