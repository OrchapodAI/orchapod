# Hosting runbook

The hosted demo is one VM running Docker Compose: Caddy (HTTPS, and the only published ports, 80 and 443), the API, the web
app, Postgres and Redis. Artifacts live in Nebius Object Storage. The design, the costs and Hari's open decisions are in
`hackathon/briefs/2026-10-22-hosting-proposal.md`. Nothing here depends on which option he picks (A-M, A-W or B2).
`<domain>` is `DOMAIN` in the VM's `.env`. On the VM, `dc` below is
`alias dc='sudo docker compose --env-file /opt/orchapod/.env -f /opt/orchapod/infra/docker-compose.prod.yml'`.

| File | Role |
| --- | --- |
| `infra/docker-compose.prod.yml` | the stack: `restart: unless-stopped`, healthchecks, logs rotated at 10 MB |
| `infra/Caddyfile` | `app.<domain>` → web, `api.<domain>` → API; WebSockets and SSE pass through |
| `infra/cloud-init.yaml` | the VM's user data: Docker, unattended upgrades, firewall 22/80/443, watchdog timer, backup and prune cron |
| `apps/api/Dockerfile`, `apps/web/Dockerfile` | the prod images; every deploy builds them on the VM |
| `scripts/deploy-hosted.sh` | copies this checkout to the VM, rebuilds, restarts |
| `scripts/backup-db.sh` | nightly `pg_dump` into the bucket, 14 rotating slots |
| `scripts/watchdog.sh` | restarts the API after 3 failed `/health` in a row |
| `infra/docker-compose.smoke.yml` | a local rehearsal of the stack; never on the VM |

## Bring-up (once, after Hari's yes)
Do the proposal's "What needs a human" steps 2–3 first (vCPU quota; GPU quotas down to 1 before any key exists).
1. **VM**: Ubuntu 24.04, 4 vCPU / 16 GB, 120 GiB disk, public IPv4, your SSH key, inbound 22, 80 and 443 only. Paste
   `infra/cloud-init.yaml` as its user data. When `ssh <vm> cloud-init status --wait` says `done`, Docker and the timers are set up.
2. **DNS**: A records `app.<domain>` and `api.<domain>` → the VM's IP.
3. **Bucket** in eu-north1 with the CORS rule `[{"allowed_origins":["*"],"allowed_methods":["GET","HEAD"],"max_age_seconds":3600}]`
   (R21), plus a service account with storage access and its static key (proposal step 5).
4. **`/opt/orchapod/.env`**, mode 600 (`sudo install -m 600 /dev/null /opt/orchapod/.env`, then edit it with sudo):
   ```
   DOMAIN=<domain>
   POSTGRES_PASSWORD=<openssl rand -hex 32>
   ORCHAPOD_INTERNAL_SECRET=<openssl rand -hex 32>
   ORCHAPOD_ADMIN_TOKEN=<openssl rand -hex 32>
   ORCHAPOD_ENDPOINT_TOKEN=<openssl rand -hex 32>
   NEBIUS_API_KEY=<Token Factory key>
   TAVILY_API_KEY=<Tavily key>
   HF_TOKEN=<read token>
   ORCHAPOD_R2_ENDPOINT=https://storage.eu-north1.nebius.cloud
   ORCHAPOD_R2_REGION=eu-north1
   ORCHAPOD_R2_ACCESS_KEY=<static key id>
   ORCHAPOD_R2_SECRET_KEY=<static key secret>
   ORCHAPOD_R2_BUCKET=<bucket>
   ORCHAPOD_MAX_DAY_USD=5
   ORCHAPOD_ANON_SCALE=0.1
   NEBIUS_PROJECT_ID=<project id>
   ```
   The last three lines follow Hari's decision 5 and Lane B. Everything else keeps its `.env.example` default. The compose
   file sets `DATABASE_URL`, `REDIS_URL`, `ORCHAPOD_CONTROL_URL` (`https://api.<domain>`) and `ORCHAPOD_CORS_ORIGINS`
   itself, and it never passes `VASTAI_API_KEY`. It refuses to start without `DOMAIN`, `POSTGRES_PASSWORD`,
   `ORCHAPOD_INTERNAL_SECRET` or the four storage settings. Postgres takes its password only when its volume is first created.
5. **First deploy**, from your Mac: `ORCHAPOD_DEPLOY_HOST=<user>@<vm-ip> scripts/deploy-hosted.sh` (the first build takes minutes).
6. **Node images**: the API pulls `ghcr.io/bangadpurva/<node>:latest`, so those packages must be public. If they are not,
   build them on the VM: `cd /opt/orchapod && for d in containers/*/; do sudo docker build -t orchapod/$(basename $d):dev -f ${d}Dockerfile .; done`.
7. **Golden run** (what `make demo` does locally):
   `dc run --rm -v /opt/orchapod/scripts:/app/scripts:ro api python scripts/seed-golden-run.py`.
8. **Lane B only** (R15): the API image has the `nebius` CLI (0.12.293) and mounts `/opt/orchapod/nebius` at `/root/.nebius`.
   Copy the compute service account's private key there, then run `dc exec api nebius profile create` with `--parent-id`,
   `--service-account-id`, `--public-key-id` and `--private-key-file-path /root/.nebius/<file>` (`--help` explains each).
9. **Checks** (proposal "HTTPS, DNS and the bucket"):
   - `curl -fsS https://api.<domain>/health`, and `https://app.<domain>/` renders.
   - Hairpin NAT: `sudo docker run --rm curlimages/curl -fsS https://api.<domain>/health` passes. If it fails, nodes cannot
     log: add `--add-host <api host>:host-gateway` to `docker run` in `packages/providers/local_docker.py`.
   - Bucket CORS: `curl -s -o /dev/null -D - -H 'Origin: null' '<a presigned GET url>'` shows `Access-Control-Allow-Origin: *`.
   - From outside, `nmap -Pn <vm-ip>` shows only 22, 80 and 443.
10. **Monitors** (UptimeRobot or Better Stack): `https://api.<domain>/health`; `https://app.<domain>/agent` (keyword Orchapod);
    the golden run's `https://api.<domain>/runs/<id>/summary` (keyword `succeeded`).

## Deploy
From your Mac, at the commit to ship: `ORCHAPOD_DEPLOY_HOST=<user>@<vm> scripts/deploy-hosted.sh`. It copies the checkout
(minus `.git` and everything `.gitignore` names) and never touches the VM's `.env`, `nebius/` or `deploys.log`. Then it
rebuilds the images, restarts what changed, and appends `<UTC time> <commit>` to `/opt/orchapod/deploys.log`; `-dirty`
means uncommitted changes went out. A run in flight when the API restarts fails with "control plane restarted" (retry it),
so deploy between runs.

## Rollback
`ssh <vm> tail -3 /opt/orchapod/deploys.log`, then `git checkout <previous commit>`, deploy, and `git checkout -`. Code
rolls back; data does not. The API only ever adds tables (`create_all`), so old code runs on a newer database; data comes
back only by a restore.

## Kill switch
- Soft (the site stays up; plan, run, start and retry answer 503): set `ORCHAPOD_KILL_SWITCH=1` in `/opt/orchapod/.env`,
  then `dc up -d api` (about 10 s; recreating the API also fails the runs in flight). Undo: set it to 0 and rerun the same command.
- Hard (no API): `dc stop api`; undo with `dc start api`. The watchdog leaves a stopped API alone.

## Backup and restore
Cron runs `scripts/backup-db.sh` at 03:15 UTC: `pg_dump -Fc` → `s3://<bucket>/backups/pg/orchapod-<NN>.dump`, NN = day
number mod 14, so the bucket keeps the last 14 nights with no lifecycle rule. Its log: `journalctl -t orchapod-backup`.
To back up by hand: `sudo /opt/orchapod/scripts/backup-db.sh`. Restore (it replaces the tables the dump holds):
```
dc exec api python -c 'from api.services.storage import _bucket, _get_client; [print(o["LastModified"], o["Key"], o["Size"]) for o in _get_client().list_objects_v2(Bucket=_bucket(), Prefix="backups/pg/").get("Contents", [])]'
dc exec -T api python -c 'import sys; from api.services.storage import _bucket, _get_client; _get_client().download_fileobj(_bucket(), sys.argv[1], sys.stdout.buffer)' backups/pg/orchapod-<NN>.dump > /tmp/restore.dump
dc exec -T postgres pg_restore -U orchapod -d orchapod --clean --if-exists < /tmp/restore.dump && dc restart api && rm /tmp/restore.dump
```
Rebuild from nothing (target 30 minutes): a new VM from cloud-init, the same `.env`, deploy, restore, golden run.

## Daily check (weekly until Dec 1, daily Dec 1–15)
- The monitors are green; `dc ps` shows every service healthy; `df -h /` is under 80%.
- `journalctl -u orchapod-watchdog --since -1d | grep restarting` (should be empty); `journalctl -t orchapod-backup --since -1d`
  shows last night's `backup: … bytes`.
- The Nebius bill lists only the VM, its disk, its IP and the bucket: no leftover endpoint or job. Check the Token Factory
  credit and today's spend against `ORCHAPOD_MAX_DAY_USD`.

## Teardown (Dec 16, or Jan 11 under decision 2; owner Hari)
1. Export what is worth keeping, for example the golden run: `dc run --rm -v /opt/orchapod/scripts:/app/scripts api python scripts/seed-golden-run.py --export <run_id>`.
2. Delete the VM, then its disk (check the Disks list for leftovers) and its public IP.
3. Empty the bucket, then delete it.
4. Delete both service accounts and their keys (the copies on the VM go with its disk).
5. Remove the DNS records and delete the monitors.
6. Rotate `NEBIUS_API_KEY` and `TAVILY_API_KEY`.
7. The next day, check that the Nebius bill shows no running line items.

## Rehearse locally
The prod stack on a laptop: Caddy on 18080/18443 with its internal CA, MinIO as the bucket, STUB on. Use your own project name.
```
export COMPOSE_PROJECT_NAME=orchapod-prodtest-$USER DOMAIN=orchapod.test POSTGRES_PASSWORD=smoke ORCHAPOD_INTERNAL_SECRET=smoke \
  ORCHAPOD_R2_ENDPOINT=http://minio:9000 ORCHAPOD_R2_REGION=auto ORCHAPOD_R2_ACCESS_KEY=orchapod ORCHAPOD_R2_SECRET_KEY=orchapod_dev STUB=1
dc() { docker compose -f infra/docker-compose.prod.yml -f infra/docker-compose.smoke.yml "$@"; }   # bash and zsh
dc up -d --build --wait
curl -kfsS --resolve api.orchapod.test:18443:127.0.0.1 https://api.orchapod.test:18443/health
curl -kfsSL --resolve app.orchapod.test:18443:127.0.0.1 https://app.orchapod.test:18443/ | grep -o '<title>[^<]*'
scripts/backup-db.sh                                       # a dump lands in MinIO
docker kill -s STOP "$(dc ps -q api)"; sleep 40; scripts/watchdog.sh   # unhealthy → restarted
dc down -v --rmi local; rmdir nebius                       # Docker created nebius/ for the bind mount
```

## What the hosted app still needs from backend (D6 hardening, backend-w4)
- CORS: the compose file already passes `ORCHAPOD_CORS_ORIGINS=https://app.<domain>`. Until backend reads it,
  `apps/api/main.py` allows `*` with credentials.
- Health: `/health` is shallow today, and both the compose healthcheck and the watchdog follow it. Once backend splits it
  into a deep `/health` and a shallow `/livez`, point the API healthcheck at `/livez`. Otherwise a Postgres outage restarts the API every minute.
- Per-IP rate limits see the visitor's address: uvicorn trusts Caddy's `X-Forwarded-For` (`--forwarded-allow-ips '*'`), and
  only Caddy can reach the API.
- The kill switch works whether or not it is read per request, because the procedure recreates the API.
