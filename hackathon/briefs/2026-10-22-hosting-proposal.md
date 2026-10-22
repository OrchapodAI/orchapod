# DECISION proposal: hosting for the Dec 1–15 judging window (platform-w3, wave 3, item 1; fix round 1)
Status: DECIDED by Hari on 2026-10-21 — A-M, fallbacks A-W then B2; domain orchapod.dev (bought at Hostinger). Previously: PROPOSED, waiting for Hari. Nothing was created and nobody signed up for anything; this is desk research. Prices are the vendors' public pages read on 2026-10-20, in USD excluding tax unless marked EUR (sources at the end). Sizing figures are estimates, not measurements.

## Bottom line
- Recommend **A-M: one Nebius `cpu-e2` VM** (eu-north1, `4vcpu-16gb`, 120 GiB disk) running Docker Compose (Caddy, API, web, Postgres, Redis), with artifacts in Nebius Object Storage. About **$97 a month**; about **$173 for the whole window** (Oct 26 to Dec 16, domain included).
- Why a VM and not a PaaS: the API starts every cpu and api node with `docker run` (`packages/providers/local_docker.py`), so the host needs a Docker daemon. That rules out Vercel, Render, Fly and Cloud Run for the API.
- A follows the plan of record (PLAN.md D4: one Nebius CPU VM, HTTPS) with two changes: the web app runs on the same VM instead of Vercel, and artifacts use Nebius Object Storage instead of MinIO. If Nebius has not raised our vCPU quota by Oct 25 noon, fall back to **A-W** (Nebius `cpu-d3` in eu-west1, no quota wait, about $189), then **B2** (DigitalOcean, about $96). Hetzner (about $44) is cheaper, but every plan's page said it is currently unavailable.
- From Hari: the five decisions below and about 80 minutes of his time, mostly in the Nebius console, plus waits. Platform builds everything else in the repo first, with no cloud access.

## Decisions for Hari
| # | Decision | Recommended default | By (why) |
| --- | --- | --- | --- |
| 1 | Option and size | **A-M**, fallbacks A-W then B2. A-L (8 vCPU) only if intent #3 must run live for visitors | Oct 24 (the quota wait starts here) |
| 2 | End date | **Tear down Dec 16.** Keeping it to Jan 11, when winners are announced, adds about $83 | about Dec 10 (before judging ends) |
| 3 | Domain | **Buy `orchapod.dev`** (public registry lookup on 2026-10-20: not registered; about $9–11 the first year, $13 to renew), records `app.` and `api.`. For the record: `orchapod.com` is registered (Jan 2026, owner unknown) and `orchapod.ai`, which the README and email default imply, is not | Oct 24 (DNS and certificates take a day) |
| 4 | Who deploys | **Hari, or the Orchestrator session on his Mac**, with `scripts/deploy-hosted.sh` (rsync + `docker compose up`), so no agent holds a key to the VM | Oct 25 (first deploy) |
| 5 | Hosted caps | **`ORCHAPOD_MAX_DAY_USD=5`, `ORCHAPOD_ANON_SCALE=0.1`** | Oct 26, D6 (the app goes public) |
- Decision 5, in plain terms. At 0.1 an anonymous run is capped at $0.30: movie ($0.03 reduced) and maths ($0.02) fit, but real-estate's reduced plan ($0.83, backend-w3, at the corrected L40S price) does not, so it stays admin-only unless Hari sets the scale to 0.3 or more (cap $0.90). The $5 day cap allows up to $75 over 15 days, which is **more than the whole free Token Factory pool** ($25 promo + $25 Builders, which development also draws on: spikes 1 and 2 are capped at $4, the golden run at $3); the rest would be charged to Hari's card. A $3 cap ($45) stays inside the pool.
- Reply template: `approve A-M, fallbacks A-W then B2; domain: buy orchapod.dev; deploy: Hari; day cap $5, anon scale 0.1; teardown Dec 16`

## What has to be hosted, and the constraints that decide it
| Piece | Today | Hosted |
| --- | --- | --- |
| API | FastAPI/uvicorn, `/health`, WebSocket `/ws/runs/{id}`, `create_all` at start | container on the VM behind Caddy; needs the `docker` CLI and `/var/run/docker.sock`, and the `nebius` CLI for IAM tokens when GPU nodes run (R15) |
| Node containers | `docker run` per cpu/api node (images about 0.3 GB each; data-prep 0.75 GB, quantize 3.9 GB; 8–10 GB in all, estimate) | siblings on the VM's Docker; pulled from GHCR (packages must be public) or built on the VM as `orchapod/<type>:dev` |
| Postgres 16, Redis 7 | compose containers | same containers, on the compose network only (no published ports) |
| Object Storage | MinIO | Nebius Object Storage `https://storage.eu-north1.nebius.cloud`; Lane B jobs need it, and it is the simplest public endpoint for presigned downloads |
| Web | Next.js 15.3.2, `NEXT_PUBLIC_API_URL`/`_WS_URL` baked in at build | container on the same VM, `app.<domain>` |

Constraints: (1) a Docker daemon next to the API; (2) a public https `ORCHAPOD_CONTROL_URL`, because Serverless Jobs call `/internal/*` and have no other log path; (3) the API answers a download with a 307 to a 1-hour presigned URL, so the browser sends `Origin: null`, and the bucket must allow GET and HEAD from `*` (contracts R21); (4) always on from G3 (Oct 27) through Dec 15: PLAN.md says the demo must stay testable for seven weeks after submission, and stage-one checks could come any time after Oct 30.
```
Browser --https--> Caddy :443 --> web (app.<domain>) and api (api.<domain>, wss)      [all on the VM]
api --docker.sock--> node containers (cpu/api) --> Token Factory, Tavily, Object Storage
api --> postgres, redis (compose network only);  api --> Nebius Jobs/Endpoints (Lane B)
Jobs/Endpoints --https--> api.<domain>/internal/*  and  Object Storage
```

## Options
Window = Oct 26 to Dec 16, 51 days = 1,224 h = 1.68 months. Each total adds a Nebius bucket (about $1) and the domain (about $11).
| Option | Where | Monthly | Window | Human steps | Main risk |
| --- | --- | --- | --- | --- | --- |
| **A-M** (recommended) | Nebius `cpu-e2` 4 vCPU / 16 GB, 120 GiB, eu-north1 | $97 | **$173** | project and billing, quotas, VM, bucket, DNS | vCPU quota starts at 0 in eu-north1 |
| **A-W** (first fallback) | Nebius `cpu-d3` (AMD) 4 vCPU / 16 GB, 120 GiB, eu-west1 (France) | $106 ($96 compute) | $189 | as A-M, minus the quota wait (the default there is 200 vCPU); one check: Hari's tenant has a usable project in eu-west1 | second region: bucket reads cost $0.015 per GiB (about $1 in the window, included) |
| A-S | Nebius 2 vCPU / 8 GB, 60 GiB | $49 | $93 | same as A-M | cannot run intent #3 (quantize plus llama.cpp eval) live |
| A-L | Nebius 8 vCPU / 32 GB, 200 GiB | $190 | $330 | same as A-M | cost; only for live intent #3 |
| B2 | DigitalOcean 4 vCPU / 8 GiB / 160 GiB | $48 | $96 | card, droplet, DNS, bucket | no Nebius VM story; the bucket still needs the Nebius account |
| B1 | Hetzner CX43 8 vCPU / 16 GB (EUR 16.49 excl. VAT; at an assumed 1.15 USD per EUR) | $19 | $44 | account (may need ID or a prepayment), server, DNS, bucket | every plan's page said it is currently unavailable on 2026-10-20 |
| C | Vercel + Render/Fly API + managed DB | not priced | n/a | | **rejected**: no Docker daemon for node containers; moving cpu/api nodes to Serverless CPU Jobs is new provider code, adds job start-up to every node (a GPU vLLM endpoint takes about 5 minutes to reach Running; CPU start-up is unmeasured, so this is an estimate) against a 25-minute target, and meets the same vCPU quota |
| D | Hari's Mac behind a tunnel | $0 | n/a | | **rejected** for the window (sleep, ISP); fine as a throw-away tunnel for one Lane B test before the VM exists |
A-W keeps the bucket in eu-north1, next to the GPUs. Nebius charges $0.015 per GiB for Standard-storage egress to the internet or another region and nothing inside a region, plus $0.00028 per 1,000 GET requests (docs.nebius.com/object-storage/resources/pricing). So what the eu-west1 VM reads costs that rate; moving the bucket to eu-west1 would make the Lane B jobs pay it for model weights instead.
Also considered and not proposed: web on Vercel Hobby ($0, personal and non-commercial use only per its FAQ) or Pro ($20 a month), which adds an account, CORS and a build-time API URL for a shell that is useless without the API; Nebius Managed PostgreSQL (4 vCPU / 16 GB is about $204 a month for compute alone); free-tier databases (more accounts, cold starts, the same data-loss exposure as a dump).

## Monthly cost, A-M, line by line
| Line | Basis | Per month | Window |
| --- | --- | --- | --- |
| VM compute | 4 vCPU × $0.012 + 16 GiB × $0.0045 = $0.12/h × 730 h | $87.60 | $146.88 |
| Disk (OS, images, Postgres) | 120 GiB network SSD × $0.071 per GiB-month | $8.52 | $14.29 |
| Public IPv4, traffic in/out | listed Free | $0 | $0 |
| Object Storage | $0.0147 per GiB-month (assume 50 GiB), egress $0.015 per GiB | about $0.75 | about $1.20 |
| Domain | first year, once | | about $11 |
| Total | | **about $97** | **about $173** |
A-W: 4 vCPU × $0.015 + 16 GiB × $0.0045 = $0.132/h = $96.36 a month; window $161.57 + the same disk, bucket and domain + about $1 of cross-region reads = $189. A-S: $0.06/h = $43.80 a month, window $73.44 + disk $7.14. A-L: $0.24/h = $175.20 a month, window $293.76 + disk $23.81. B2: DigitalOcean bills Droplets per second, capped at 672 hours a month: $10.29 (Oct 26–31) + $48 (Nov) + $25.71 (Dec 1–15) = $84, plus bucket and domain. Nebius bills VMs per second; a stopped VM stops compute billing but not disks, and still counts toward quota.
Why 4 vCPU / 16 GB (estimates): the idle stack takes about 1 GB; Lane A nodes are API-bound; quantizing a model of 2B or less needs roughly 6–10 GB for a few minutes, and the llama.cpp eval of 50 GSM8K items on CPU is the slowest CPU step in the product (tens of minutes at 4 vCPU). Go bigger only if that must be live for visitors; otherwise ship intent #3 as the pre-completed golden fixture.

## Not hosting, but it moves in the window (all capped by the existing guard)
| Item | Exposure | Note |
| --- | --- | --- |
| Token Factory | `ORCHAPOD_MAX_DAY_USD` × 15 days: $75 at $5, $225 at $15 | free pool is $50 and shared with development (Decision 5); keep at least $20 unspent for the window (PLAN) or top up |
| Lane B GPU | off by default; one 30-minute L40S wake = $0.78 (1.55 × 0.5) | always on for 15 days = $558; do not, without Hari's yes. An endpoint also bills its 250 GiB disk (about $0.024/h), which PRICES does not include |
| Price drift | Nebius repriced H100 ($3.85 to $4.50) and CPU RAM ($0.0032 to $0.0045 per GiB-h) on Oct 1; L40S unchanged | re-read nebius.com/prices on D7 and the day before the window; the date is in the `prices.py` comment |

## HTTPS, DNS and the bucket
- Caddy with automatic HTTPS (Let's Encrypt or ZeroSSL): ports 80 and 443 open to the internet and an A record per name. WebSockets pass through `reverse_proxy` with no extra directive. Names `app.<domain>` and `api.<domain>`; `ORCHAPOD_CONTROL_URL=https://api.<domain>` for every node, local or GPU.
- Node containers reach that name through the VM's own public IP. Unverified on Nebius (hairpin NAT): test with one `docker run … curl https://api.<domain>/health` on D5. Fallback is three lines in `local_docker.py`: `--add-host <control host>:host-gateway`.
- Bucket CORS (R21): `[{"allowed_origins":["*"],"allowed_methods":["GET","HEAD"],"max_age_seconds":3600}]`. Objects are reachable only through 1-hour presigned URLs, so `*` exposes nothing else. How it gets onto the bucket: at creation, `nebius storage bucket create … --cors-rules '<json>'`; afterwards `nebius storage bucket update --id <bucket> --patch --cors-rules '<json>'` (the reference lists both flags, but not whether an update without `--patch` clears other settings), or S3 `put-bucket-cors`, which Nebius lists as an action for the `storage.editor` role (no GetBucketCORS is listed).
- CORS test, D5: `curl -s -o /dev/null -D - -H 'Origin: null' '<presigned GET url>'` must show `Access-Control-Allow-Origin: *`. Use GET: `curl -I` sends HEAD, which a GET-presigned URL normally rejects (the method is part of the signature).

## Uptime and recovery
- External: UptimeRobot free (50 monitors, 5-minute checks, one status page; its pricing page frames the plan as for hobby and non-profit projects; confirm email alerts at signup) or Better Stack free (10 monitors, Slack and email; for personal projects). Three checks: `https://api.<domain>/health`, `https://app.<domain>/agent` (keyword), and the golden run's `/runs/<id>/summary` (keyword `succeeded`, which proves Postgres and the fixture). `/health` is shallow today (it never touches Postgres or Redis); asking backend for a deep check in the D6 hardening.
- On the VM: `restart: unless-stopped`, compose healthchecks, and a one-minute systemd timer that restarts the API after three failed `/health` calls (the PLAN's "uptime monitor with restart"). Logs rotate at 10 MB; weekly `docker image prune`. Unattended upgrades on, automatic reboot off.
- Backups: nightly `pg_dump` to `s3://<bucket>/backups/pg/` with a 14-day lifecycle rule; the golden run comes back with `make demo`. Rebuild target 30 minutes (new VM, cloud-init, `deploy-hosted.sh`, restore, `make demo`), rehearsed once on D7. One VM is a single point of failure; accepted.
- Daily during Dec 1–15: the monitors, the Nebius bill, Token Factory credit and the day ledger. Kill switch: `ORCHAPOD_KILL_SWITCH=1` in `/opt/orchapod/.env`, then `docker compose up -d api` (about 10 s; backend to confirm whether it is read per request).

## Credentials and security
| Credential | Holder | Lives in |
| --- | --- | --- |
| `NEBIUS_API_KEY` (Token Factory), `TAVILY_API_KEY`, `HF_TOKEN` | Hari | his local `.env`; `/opt/orchapod/.env` on the VM (mode 600) |
| Postgres password, `ORCHAPOD_INTERNAL_SECRET` (R17), `ORCHAPOD_ENDPOINT_TOKEN`, `ORCHAPOD_ADMIN_TOKEN` | Hari generates them (`openssl rand -hex 32`) | the VM `.env` only; he uses the admin token from curl, never in the browser and not during Dec 1–15 |
| Object Storage static key (storage service account) | Hari | the VM `.env` as `ORCHAPOD_R2_ACCESS_KEY`/`_SECRET_KEY` |
| Compute service-account key and CLI profile (Jobs, Endpoints; R15) | Hari | `/opt/orchapod/nebius/` (mode 600), mounted read-only into the API container |
| SSH private key; Nebius, registrar and monitor logins | Hari (Purva as second admin if wanted) | his Mac and password manager; the VM holds only the public key |
| (agents) | hold none of these, per Decision 4 | n/a |
- **GPU blast radius.** The compute key can start GPUs up to the project's GPU quota. The default in eu-north1 is 32 H100 and 32 L40S (docs.nebius.com/compute/resources/quotas-limits), so a leaked key could run 32 H100s at about $144 an hour (32 × $4.50) until someone notices. Human step 3 lowers both to 1; do it before any key is created.
- Firewall allows 22 (Hari's IP if static), 80 and 443; only Caddy publishes ports (Docker bypasses UFW for published ports). Nebius does not document default security-group behaviour on the pages I read: verify from outside with `nmap`. The API container holds `docker.sock`, which is root on the VM: a one-purpose VM, node types come from the registry, anonymous caps, no other secrets on the host. CORS is `*` with credentials in `apps/api/main.py`: backend, D6.
- Data residency: everything sits in eu-north1 (Finland), except A-W's VM in eu-west1 (France); visitor text (intents, prompts, queries) goes to Token Factory and Tavily.

## What needs a human
| # | Who | What | Time | Blocks |
| --- | --- | --- | --- | --- |
| 1 | Hari | Answer the decisions above | 5 min | everything |
| 2 | Hari (Nebius admin) | AI Cloud project and payment method (already on the Human actions list). Administration → Limits → Quotas: raise "Total vCPUs across non-GPU VMs" in eu-north1 from **0** to 8; check the tenant has a usable eu-west1 project (A-W) | 10 min + wait | VM |
| 3 | Hari (Nebius admin) | Same page: read "Total NVIDIA H100 GPUs …" and "Total NVIDIA L40S GPUs …" (**32 each** by default) and lower each to 1; admins can request decreases (docs.nebius.com/overview/quotas), tracked in the support center, so re-read the page. Skipped, a leaked key could run 32 H100s, about $144/h | 5 min | any key |
| 4 | Hari | Create the VM from my cloud-init, in the console (the `nebius` CLI is not installed yet; I can supply the commands if you install it): Ubuntu 24.04 CPU image, his SSH public key, public IPv4, security group as above | 15 min | deploy |
| 5 | Hari | Bucket with the CORS rule above, a service account and a static access key (commands supplied) | 15 min | artifacts, downloads |
| 6 | Hari or Purva | Buy the domain; two A records to the VM's IP | 10 min + TTL | HTTPS |
| 7 | Hari | Four random secrets into `.env` on the VM | 5 min | start |
| 8 | Purva | GHCR packages public (already open), or the VM builds the images itself and nothing is needed | 5 min | image pulls |
| 9 | Hari | UptimeRobot (or Better Stack) account, three monitors, alert email | 10 min | monitoring |
Optional: apply for a Nebius compute grant (dev.nebius.com/builders lists a separate application; terms and timing unknown). The Builders Program gives no AI Cloud credit, so the VM is out of pocket.

## What platform builds after a yes (repo only, no cloud access; about 5 h plus 1 h of bring-up with Hari)
`infra/docker-compose.prod.yml`, `infra/Caddyfile`, `infra/cloud-init.yaml`; `apps/api/Dockerfile` (no `--reload`; docker and nebius CLIs) and `apps/web/Dockerfile`; `scripts/deploy-hosted.sh`, `backup-db.sh`, `watchdog.sh`; `docs/HOSTING.md` (deploy, rollback, kill switch, restore, daily check, teardown); a test that the prod compose carries exactly the contract Config and publishes only Caddy's ports. Needed from others: backend (CORS allow-list, deep health, per-IP rate limits), qa (rehearsals on the hosted URL, D8), devrel (demo URL in README and Devpost).

## Timeline and teardown
| Date | Step |
| --- | --- |
| Oct 22–24 (D2–D4) | Hari answers 1 and 3 by Oct 24; the same day, quota steps 2 and 3; platform builds the files |
| Oct 25 (D5) noon | vCPU quota granted? If not, A-W (if the eu-west1 project exists), else B2 |
| Oct 25–27 | VM, bucket, DNS, first deploy, `make demo`, monitors; Oct 27 (D7, G3) freeze, rebuild rehearsal |
| Oct 28–29 | three rehearsals on the hosted app; submit |
| Nov 1 to Dec 15 | leave running; weekly check, daily from Dec 1. Stopping in November would save about $80 of compute but risks failing an early screening; not proposed |
| Dec 16 | teardown (or Jan 11, Decision 2) |
Teardown, owner Hari, Dec 16 (commands in `docs/HOSTING.md`): export the golden run and anything worth keeping; delete the VM; then its disk (check the Disks list for leftovers), the public IP, the bucket (empty it first), both service accounts with their keys and the key files on the VM; remove the DNS records; delete the monitors; rotate `NEBIUS_API_KEY` and `TAVILY_API_KEY`; next day, confirm the Nebius bill shows no running line items.

## Risks
| Risk | Mitigation |
| --- | --- |
| vCPU quota 0 in eu-north1, approval time unknown | request now; at Oct 25 noon A-W, then B2 |
| GPU quota 32 + 32 by default; a leaked key is expensive | step 3 before any key exists; rotate after Dec 15 |
| Single VM dies | 30-minute rebuild path, nightly dump, `make demo` |
| Unverified: certificate issuance, hairpin NAT, bucket CORS | test all three on D5 (staging certificate, container `curl`, `Origin: null` `curl`) |
| Visitors burn credit; disk fills | day cap, anonymous scale, kill switch, credit reserve; 120 GiB, prune timer, alert at 80% |

## Sources (read 2026-10-20)
- nebius.com/prices: HGX H100 $4.50; L40S Intel from $1.55, AMD from $1.82; CPU instances from $0.06 and $0.13 per hour; Object Storage Standard $0.0147 per GiB-month, egress $0.0150 per GiB; public IP and traffic Free. docs.nebius.com/compute/resources/pricing: CPU $0.012 (Ice Lake) and $0.015 (Genoa) per vCPU-hour, RAM $0.0045 per GiB-hour from Oct 1 2026; network SSD $0.071 per GiB per 730 h; per-second billing. docs.nebius.com: serverless/pricing-quotas, compute/virtual-machines/types (`cpu-e2` eu-north1 only, `cpu-d3` all regions), compute/resources/quotas-limits (non-GPU vCPU 0 in eu-north1, 200 in eu-west1; 32 H100 and 32 L40S in eu-north1), overview/quotas and overview/regions, object-storage/resources/pricing, object-storage/supported-actions, cli/reference/storage/bucket/create and /update, postgresql/resources/pricing.
- dev.nebius.com/builders (no AI Cloud credit). hetzner.com/cloud (CX33 EUR 8.99, CX43 EUR 16.49, every plan marked unavailable) and its fraud-prevention FAQ. digitalocean.com/pricing/droplets and docs.digitalocean.com/products/droplets/details/pricing ($48, per-second billing, 672-hour cap). vercel.com/pricing, uptimerobot.com/pricing, betterstack.com/pricing, caddyserver.com/docs/automatic-https, Porkbun listings for `.dev` and `.com`, public RDAP lookups of orchapod.dev, .app, .com and .ai.
- Not verified: Nebius default security-group behaviour, hairpin NAT, the CPU boot-image name, whether a manual quota decrease applies at once, S3 `put-bucket-cors` in practice, UptimeRobot email alerts on the free plan, Hetzner stock, EUR to USD.
