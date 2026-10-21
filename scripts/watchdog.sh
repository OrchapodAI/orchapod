#!/bin/sh
# Restart the hosted api once Docker marks it unhealthy, i.e. after 3 failed /health in a row (its healthcheck in
# infra/docker-compose.prod.yml). orchapod-watchdog.timer runs this every minute (infra/cloud-init.yaml); the restarts
# show in `journalctl -u orchapod-watchdog`. A stopped api is left alone: someone stopped it on purpose.
set -eu
for c in $(docker ps -q --filter "label=com.docker.compose.project=${COMPOSE_PROJECT_NAME:-orchapod}" \
    --filter label=com.docker.compose.service=api --filter label=com.docker.compose.oneoff=False --filter health=unhealthy); do
  echo "api container $c is unhealthy: restarting it"
  docker restart "$c"
done
