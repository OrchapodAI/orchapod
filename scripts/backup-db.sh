#!/usr/bin/env bash
# Nightly (cron, infra/cloud-init.yaml): pg_dump the hosted Postgres into the artifact bucket as backups/pg/orchapod-<NN>.dump,
# NN = days since 1970 mod 14, so the bucket keeps the last 14 nights with no lifecycle rule. Restore: docs/HOSTING.md.
set -euo pipefail
project=${COMPOSE_PROJECT_NAME:-orchapod}
container() { docker ps -q --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=$1"; }
key=backups/pg/orchapod-$(printf %02d $(( $(date -u +%s) / 86400 % 14 ))).dump

# The dump goes to a file first, so a failed pg_dump never overwrites a good slot.
dump=$(mktemp)
trap 'rm -f "$dump"' EXIT
docker exec "$(container postgres)" pg_dump -U orchapod -d orchapod -Fc > "$dump"
# The api container has boto3 and the bucket's credentials: upload the way the API itself talks to storage.
docker exec -i "$(container api)" python -c 'import sys; from api.services.storage import _bucket, _get_client; _get_client().upload_fileobj(sys.stdin.buffer, _bucket(), sys.argv[1])' "$key" < "$dump"
echo "backup: $(wc -c < "$dump" | tr -d ' ') bytes to $key"
