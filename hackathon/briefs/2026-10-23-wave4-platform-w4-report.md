# platform-w4 report — wave 4 (written 2026-10-21)
Status: DONE · branch `hack/platform-w4` (worktree `/Users/hari/src/orchapod-hack/.claude/worktrees/platform-w4`; `git merge-base --is-ancestor e3c289b HEAD` = yes) · cost $0 (no key used, no cloud resource created, nothing bought, no sign-up).
Resumed after the orchestrator restart. The branch had no commits; I had started no Docker resources before the stop (only `docker manifest inspect`, which pulls nothing). Docker Desktop was down at first, so I wrote and committed everything that needs no daemon. When someone else brought Docker back up and the Orchestrator said go, I ran the builds and the smoke.

## Commits (never pushed; trailer `Co-Authored-By: Claude Opus 5.5`)
- `f5d20d2` fix(providers): NebiusProvider.quote reads orchapod.prices; its stale _PRICES table is gone (item 3)
- `16371e3` feat(config): .env.example marks hosted values, adds ORCHAPOD_MAX_COMPARES, comments out VASTAI_API_KEY (item 2)
- `c89d4bd` feat(infra): prod Dockerfiles for the API and the web app
- `b30f6e7` feat(infra): prod compose, Caddyfile and cloud-init for the hosted VM
- `ab1e1d7` feat(scripts): deploy, nightly backup and api watchdog for the hosted VM
- `f120c32` docs: HOSTING.md runbook (bring-up, deploy, rollback, kill switch, restore, daily check, teardown)
- `7f373af` docs(hosting): rehearsal snippet works in zsh; the nebius profile flags, checked in the built image
- 18 files, +609 −26. `git merge-tree --write-tree NebiusHackathon HEAD` (NebiusHackathon at 0abfd46): clean. My 11 tests also pass on that merged tree.

## Item 1: hosting files (proposal "What platform builds after a yes")
- `infra/docker-compose.prod.yml` (project `orchapod`): Caddy is the only service with `ports` (80, 443). api, web, postgres and redis share the compose network. Every service has `restart: unless-stopped`, a healthcheck and json-file logs at 10 MB × 3.
  - The API gets the contract Config without `VASTAI_API_KEY`, so the hosted app never rents vast.ai GPUs. It refuses to start without `DOMAIN`, `POSTGRES_PASSWORD`, `ORCHAPOD_INTERNAL_SECRET` (R17) or the four storage settings; MinIO's defaults would be wrong in prod.
  - The compose sets `DATABASE_URL`, `REDIS_URL`, `ORCHAPOD_CONTROL_URL=https://api.${DOMAIN}` and `ORCHAPOD_CORS_ORIGINS=https://app.${DOMAIN}` itself (the CORS var was pre-wired for backend-w4, with the Orchestrator's OK).
  - Mounts: `/var/run/docker.sock` (nodes run as sibling containers) and `../nebius:/root/.nebius` (R15).
- `infra/Caddyfile`: `app.{$DOMAIN}` → web:3000, `api.{$DOMAIN}` → api:8000. reverse_proxy carries WebSockets, flushes SSE at once, and replaces a client-sent X-Forwarded-For.
- `infra/cloud-init.yaml`:
  - Packages: docker.io, docker-compose-v2, docker-buildx, rsync, ufw, unattended-upgrades.
  - `/etc/docker/daemon.json` sets `live-restore` (an upgrade restarts dockerd without stopping containers) and 10 MB logs for every container, node containers included.
  - Unattended upgrades on, automatic reboot off; ufw denies all incoming except 22, 80 and 443.
  - Scheduling: `orchapod-watchdog.timer` (minutely) and its service; `/etc/cron.d/orchapod` runs the 03:15 UTC backup and the weekly `docker image prune -f`; `/opt/orchapod/nebius` is created with mode 700.
- `apps/api/Dockerfile` (prod; build context = repo root):
  - Same `PYTHONPATH` and COPYs as Dockerfile.dev; no `--reload`, one worker (R20).
  - The docker CLI comes from `docker:28.5.1-cli`. The nebius CLI 0.12.293 is the binary Nebius's install.sh fetches, pinned. It installs and runs without any login (`nebius version` runs during the build), so the brief's condition is met.
  - uvicorn runs with `--forwarded-allow-ips '*'`: only Caddy can reach the API, and Caddy replaces X-Forwarded-For.
- `apps/web/Dockerfile` (+ `.dockerignore`): pnpm 9.15.9 (CI's major) and `next start`. `NEXT_PUBLIC_API_URL`, `_WS_URL` and `_SITE_URL` are build args; the build stops without them rather than bake in localhost.
  - `_SITE_URL` was added at frontend-w4's request; it is set to `https://app.<domain>`.
  - The `.dockerignore` keeps a local `node_modules`, `.next` or pnpm 11's `pnpm-workspace.yaml` out of the image.
- `scripts/deploy-hosted.sh`: `ORCHAPOD_DEPLOY_HOST=<user>@<vm>`; `rsync --delete` (via `sudo rsync`) to `/opt/orchapod`, then `sudo docker compose … up -d --build --remove-orphans` on the VM, which appends `<UTC time> <commit>[-dirty]` to `/opt/orchapod/deploys.log` for rollback.
- `scripts/backup-db.sh`: `pg_dump -Fc` into a temp file, then uploads it from inside the api container (boto3 and the bucket credentials are already there, via `api.services.storage`) to `backups/pg/orchapod-<NN>.dump`.
  - NN = days since 1970 mod 14: the "14-day prefix" is 14 rotating slots, so retention needs no lifecycle rule and no extra human step.
  - A failed dump never overwrites a slot.
- `scripts/watchdog.sh`: restarts the `orchapod` project's api container when Docker marks it `health=unhealthy`. The compose healthcheck does the counting (3 failed `/health` in a row), and a deliberately stopped api is left alone.
- `infra/docker-compose.smoke.yml`: the local rehearsal (never on the VM). Caddy on 18080/18443 via `!override`, with `local_certs` in an inline config that imports the real Caddyfile; MinIO as the bucket; a 5 s api healthcheck.
- `docs/HOSTING.md` (132 lines): file map, then sections:
  - Bring-up in 10 steps, including the exact VM `.env`, the golden-run seed, the Lane B profile and the D5 checks.
  - Deploy, rollback, kill switch (soft and hard), backup and restore, daily check, teardown checklist (from the proposal), local rehearsal.
  - What the hosted app still needs from backend.
- Tests, `tests/providers/`:
  - `test_env_example.py::test_prod_compose_api_gets_the_config_and_only_caddy_publishes_ports`: api env == contract Config + ORCHAPOD_CORS_ORIGINS, no VASTAI, the internal secret required, web build args, only Caddy with `ports` (80:80, 443:443), no host networking.
  - `test_hosting.py`, three tests against recording fakes of rsync, ssh and docker: the deploy's rsync keeps `.env`, `nebius/` and `deploys.log`; the backup uploads to today's slot and never after a failed dump; the watchdog restarts only an unhealthy api of this project.
  - Each bites. Without `--exclude=/.env`, without the temp file (pg_dump piped straight into the upload), or without the health filter, its test fails: 1 failed each. Files were restored afterwards.

## Item 2: `.env.example`
- Every contract Config variable, with its default, where to get it, and `hosted:` notes; `ORCHAPOD_MAX_COMPARES=4` (backend-w3, now in contracts Config/R22) in the budget block.
- `VASTAI_API_KEY` is commented out, with the warning that a set key lets gpu nodes whose provider_pref names vastai rent vast.ai GPUs. The dev compose still forwards it for spikes; the prod compose never does.
- A "Hosted only" block: `DOMAIN`, `POSTGRES_PASSWORD`, plus a note that `ORCHAPOD_DEPLOY_HOST` comes from the shell. The dev compose's api gained `ORCHAPOD_MAX_COMPARES`.
- Test `test_every_env_name_the_code_reads_is_in_env_example`: a regex scan of `os.environ.get/[]` and `os.getenv` under apps/api and packages (it also catches the multi-line read in database.py).
  - Every name must be in `.env.example`, live or commented, or on an allow-list with reasons.
  - The allow-list: the six names the executor sets per node; `ORCHAPOD_CHECKPOINT_STEPS` (SDK default, not forwarded); `NEBIUS_FOLDER_ID` and `NEBIUS_SUBNET_ID` (legacy nebius.py, until its rewrite).
  - Stale allow-list entries fail too. Negative control: deleting `RESEND_API_KEY` from `.env.example` fails it, naming the variable.

## Item 3: second price table deleted
`packages/providers/nebius.py` imports `orchapod.prices.PRICES`; `_PRICES` (H100 2.49, H200, A100, gpu-l40s) is gone. `quote()` returns `PRICES["nebius_serverless"][platform] × count`; an unpriced platform raises `LookupError("no price for nebius_serverless <platform> in orchapod.prices.PRICES")`. pick_provider and get_cost_estimate already catch exceptions from `quote`, so the fail-closed path stays readable. Tests in `test_prices.py`: H100 ×2 = $9.00 (it was 4.98 before the fix: 2 failed, then 2 passed); H200 fails closed. `vastai.py` `_FALLBACK_PRICES` is vast.ai's market table, not Nebius, so I left it.

## Proof
```
make check (worktree, HEAD 7f373af):  ruff: All checks passed! · pytest: 559 passed · web: pass 22, fail 0 · stub e2e SKIP (E2E=1 only)
gitleaks detect --log-opts e3c289b..HEAD: 7 commits, no leaks found
docker compose -f infra/docker-compose.prod.yml config: without .env → "required variable ORCHAPOD_INTERNAL_SECRET is missing a value";
  with the required vars → valid; only caddy publishes (80, 443); ORCHAPOD_CONTROL_URL https://api.example.com
cloud-init: in a throwaway ubuntu:24.04 → cloud-init 26.2 "Valid schema /ci.yaml"; apt resolves docker.io 29.1.3,
  docker-compose-v2 2.40.3, docker-buildx 0.30.1, rsync, ufw; systemd-analyze verify of the watchdog timer and service: ok
Builds (project orchapod-prodtest-platform-w4): api built in 42 s, web in 44 s (next build: 17 routes)
Smoke (prod + smoke override, STUB=1, DOMAIN=orchapod.test, 18080/18443 only): up --wait → all 6 services healthy in 33 s
  GET https://api.orchapod.test:18443/health → {"status":"ok"} HTTP 200
  GET https://app.orchapod.test:18443/ → 1 redirect to /agent, HTTP 200, <title>Orchapod — LLM Fine-tuning Platform
  http :18080 → 308 to https · certificate issuer "Caddy Local Authority - ECC Intermediate" · WebSocket /ws/runs/<id> → 101
  /agent/templates through Caddy → 200 · web bundle holds https://api.orchapod.test and wss://api.orchapod.test, no localhost:8001
  in the api container: docker CLI 28.5.1 → host daemon 28.1.1; nebius 0.12.293 with no profile; uvicorn … --forwarded-allow-ips *;
  the api logs the client as 192.168.65.1 (the host), not Caddy's 172.26.0.6
  scripts/backup-db.sh → "backup: 13840 bytes to backups/pg/orchapod-13.dump"; HOSTING.md listing shows it; marker table dropped,
  HOSTING.md restore (download + pg_restore --clean) → marker back ("before-backup"), 8 tables
  watchdog: healthy → nothing; SIGSTOP the api → unhealthy after 31 s → watchdog.sh restarted it → healthy 6 s later, /health 200
  kill switch: ORCHAPOD_KILL_SWITCH=1 + up -d api → POST /agent/plan 503 while web /agent 200; back to 0 → 200
Teardown: down -v --rmi local removed the 6 containers, 3 named volumes, the network, and both built images (…-api, …-web).
  Removed the caddy:2.10.2-alpine and ubuntu:24.04 images I pulled; node:22-alpine and docker:28.5.1-cli were only ever in
  BuildKit's cache, never the image store. Removed the empty nebius/ that the bind mount created in my worktree.
  Nothing named prodtest or platform-w4 is left. The image store matches its pre-smoke listing except the orchapod/<node>:dev
  IDs, which another agent rebuilt during my window; I never built or touched them. orchapod-hack's postgres, redis and minio
  kept running. BuildKit's shared build cache still holds my layers: pruning it would also hit other agents' caches.
```

## Findings
- **rsync `--delete` and the VM's secrets.** With macOS's openrsync, the `.gitignore` dir-merge filter does not protect receiver files from deletion, even with `--delete-after`. A rehearsal between two scratch dirs (a VM-side `.env` and `nebius/key.pem`, no explicit excludes) deleted both. The explicit `--exclude=/.env --exclude=/nebius/ --exclude=/deploys.log` keeps them, and test_hosting pins it.
- **zsh does not word-split `$dc`**: my first smoke command failed with "no such file or directory". HOSTING.md snippets now use a shell function (`dc() { … "$@"; }`) or an alias on the VM.
- **create_all never alters a table.** Alembic is unused (LOG ruling), so the hosted DB picks up new tables but never a changed column of an existing table. Rollback is safe for the same reason. A backend change to an existing table needs a manual ALTER, or a fresh DB plus `make demo`, on the VM.
- **Healthcheck vs backend-w4's deep `/health`.** The compose healthcheck and therefore the watchdog follow `/health`. Once backend-w4 makes `/health` deep and adds `/livez`, switch the healthcheck to `/livez`, or a Postgres outage restarts the API every minute. It is a one-line change in the prod compose, noted in HOSTING.md.
- **Client IP.** uvicorn already resolves the visitor IP from Caddy's X-Forwarded-For. If backend-w4's trusted-proxy list parses XFF itself, it should use `request.client.host` as uvicorn sets it; one of the two mechanisms is enough. I added no backend-w4 env vars beyond `ORCHAPOD_CORS_ORIGINS`, per the Orchestrator.

## Deviations from the proposal (revert if unwanted)
- `nebius/` is mounted read-write, not read-only: `nebius profile create` runs inside the container, and the CLI may write its own state. The API already holds docker.sock (root on the host), so `:ro` would protect nothing.
- Backups use 14 rotating slots instead of a 14-day lifecycle rule: one human step fewer, and no reliance on Nebius lifecycle behaviour (unverified).
- The nightly backup and the weekly prune run from `/etc/cron.d`, logging to journald tags `orchapod-backup` and `orchapod-prune`; the watchdog uses the systemd timer the brief asked for.

## Not done or not verified
- Needs the cloud (proposal's list): Let's Encrypt issuance, hairpin NAT from node containers to `api.<domain>`, bucket CORS with `Origin: null`, whether the Nebius console keeps its SSH-key field once user data is set (a `users:` line is in cloud-init's header), deploy-hosted.sh against a real VM (GNU rsync receiving through `sudo rsync`), ufw with Docker, `nmap` from outside.
- The golden-run seed command in HOSTING.md (`dc run --rm -v /opt/orchapod/scripts:/app/scripts:ro api python scripts/seed-golden-run.py`) is untested: the script lives on NebiusHackathon, not on my base. Run it in the post-merge smoke.
- No node ran in the smoke: node containers on the default bridge cannot resolve `orchapod.test` or reach the smoke's MinIO. On the VM they use the public names.

## For the Orchestrator
- Record as DECISION if you agree:
  - (1) The hosted VM never gets `VASTAI_API_KEY`; the prod compose drops it and a test pins it.
  - (2) Backups use 14 rotating slots, not a lifecycle rule.
  - (3) `deploy-hosted.sh` must keep the explicit excludes (the openrsync finding).
- Follow-ups:
  - backend-w4: the `/livez` healthcheck switch (one line in the prod compose; I can do it after the merge) and the XFF note above.
  - qa: CI still builds only `Dockerfile.dev`; building `apps/api/Dockerfile` and `apps/web/Dockerfile` would catch prod-image breakage. Also the D8 rehearsals on the hosted URL.
  - The nebius.py Serverless rewrite (contracts NebiusServerless) is still open. It removes the FOLDER_ID and SUBNET_ID allow-list lines, and the stale-entry check will flag them.

## Fix round 1 (2026-10-21)
Commits: `0d7cf8f` fix(scripts) · `0595a96` fix(infra) · `716d154` docs(hosting). 11 files, +97 −48. All on `hack/platform-w4`; merge-tree against NebiusHackathon 82886f8 is clean.

### Important
1. **Lost export.** HOSTING.md now copies the export off the VM at once: `scp <user>@<vm>:/opt/orchapod/scripts/golden-run.json scripts/`.
   - Bring-up step 7 now has the D8 flow: export, scp, gitleaks, commit. It warns that the next deploy's rsync overwrites the VM's copy.
   - Teardown step 1: export and scp before step 2 deletes the disk.
2. **Node fixes never reaching the VM.** After the deploys.log line, the deploy pulls the `${ORCHAPOD_IMAGE_PREFIX:-ghcr.io/bangadpurva}/<node>:latest` of each `containers/*`. The prefix comes from the VM's `.env`, and every `$` in the ssh string is escaped.
   - One deviation: it pulls only the `:latest` images the VM already has. A gpu node's image (unsloth-train) runs on Nebius and never lands on the VM, so pulling it would cost GBs of disk for nothing. A missing image is pulled fresh at its first `docker run`, so staleness is fixed either way. Drop the `docker image inspect` guard if you want all of them.
   - A failed pull prints `could not pull <img>` and the deploy continues (the stack is already up).
   - HOSTING.md bring-up step 6 and the Deploy section say that `orchapod/<node>:dev` images built on the VM must be rebuilt or removed.

### Minors (all done)
- Hard kill switch:
  - Stops node containers: every container without a compose project (`docker ps --format '{{.ID}} {{.Label "com.docker.compose.project"}}' | awk '$2 == ""' … | xargs -r sudo docker stop -t 30`).
  - Then check the Nebius console for Jobs and Endpoints, because TTL deletion lives in the API.
  - The selector was checked by listing only: on this shared Mac, the stop would also hit other agents' node containers.
- Rehearsal:
  - The function is now `smoke() { docker compose -p "$COMPOSE_PROJECT_NAME" … }`.
  - `COMPOSE_PROJECT_NAME=orchapod-prodtest-$USER` stays exported because backup-db.sh and watchdog.sh read it. Pasted on the VM, they too stay on the prodtest project.
- Restore order:
  - List the slots, then `umask 077`.
  - Download while the API runs (`exec` needs it), then `dc stop api`.
  - `pg_restore --clean --if-exists --single-transaction`, then `dc start api && rm`.
- `infra/cloud-init.yaml`: `ssh_pwauth: false`.
- apps/api/Dockerfile:
  - A comment says why it runs as root (docker.sock is root-equivalent; the profile is in /root/.nebius).
  - The nebius binary is checked with `sha256sum -c` per arch. Nebius publishes no checksums (6 candidate URLs: 404), so I pinned today's: x86_64 `a4176af5…a421d026`, arm64 `aca84ec8…bca82a35`.
- watchdog.sh and backup-db.sh filter `label=com.docker.compose.oneoff=False`.
- deploy-hosted.sh: `-dirty` = `[ -z "$(git status --porcelain)" ]` (untracked files count; rsync ships them).
- Caddyfile:
  - `header Strict-Transport-Security "max-age=31536000"` on both sites.
  - Its header comment and the Deploy section say an edited Caddyfile needs `dc restart caddy`.
- HOSTING.md:
  - Backups share the artifact bucket and its storage key, which every node receives.
  - The weekly check includes `test -f /var/run/reboot-required`.
- Ponytail:
  - The backend status section is deleted; the `/livez` switch is now a comment on the api healthcheck.
  - The VASTAI test is one assert in the main `.env.example` test (559 → 558 tests, same coverage).
- `.env.example`: `# ORCHAPOD_CORS_ORIGINS=` is commented out in the hosted block, with a comment on what it is. My scan accepts a listed but unread name, and commented counts as documented. It is not a live line, because the prod compose derives it from DOMAIN.

### Proof
```
tests/providers/test_env_example.py, test_hosting.py, test_prices.py: 10 passed
negative controls (each restored): pulling without the presence guard → "Left contains one more item: [... 'ghcr.io/acme/unsloth-train:latest']";
  an unescaped ${prefix} in the ssh string → 1 failed; backup without the one-off filter → 1 failed
make check (HEAD 716d154): ruff All checks passed! · pytest 558 passed · web pass 22, fail 0 · stub e2e SKIP
gitleaks detect --log-opts e3c289b..HEAD: no leaks found
compose config (prod+smoke): valid · cloud-init vs its JSON schema: 0 errors, ssh_pwauth False
API image, arm64 (native): "/usr/local/bin/nebius: OK", 0.12.293 · linux/amd64 (emulated, tag orchapod-prodtest-platform-w4-api-amd64:fr1):
  "/usr/local/bin/nebius: OK", uname -m x86_64, docker 28.5.1, nebius 0.12.293; image removed afterwards
Re-smoke (project orchapod-prodtest-platform-w4, 18080/18443, all 6 healthy in 40 s):
  strict-transport-security: max-age=31536000 on app and api
  with a `run` one-off of api: without the filter, 2 api containers match; backup-db.sh → "backup: 13393 bytes to backups/pg/orchapod-13.dump";
  the one-off goes unhealthy in 30 s (it runs sleep); the old watchdog filter would match it (1); watchdog.sh → nothing, one-off untouched
  restore as documented: dump file -rw------- 13844 bytes, api Stopped, pg_restore exit 0, api Started, marker back, api healthy, /health 200
Teardown: down -v --rmi local removed 3 volumes, the network and both built images; caddy:2.10.2-alpine removed again; nothing
  named prodtest or platform-w4 is left. The image store matches its pre-re-smoke listing except orchapod/<node>:dev IDs, which
  another agent rebuilt during the window (I did not touch them).
```
