# DECISION proposal: hosting for the Dec 1–15 judging window (platform-w3, wave 3, item 1)
Status: PROPOSED, waiting for Hari. Nothing was created and nobody signed up for anything; this is desk research. Prices are the vendors' public pages as read on 2026-10-20, in USD excluding tax unless marked EUR (sources at the end). Sizing figures are estimates, not measurements.

## Bottom line
- Recommend **Option A-M: one Nebius CPU VM** (eu-north1, `cpu-e2` `4vcpu-16gb`, 120 GiB disk) running Docker Compose (Caddy, API, web, Postgres, Redis), with artifacts in Nebius Object Storage. About **$97 a month**; about **$175 for the whole window** (Oct 26 to Dec 16, domain included).
- Why a VM and not a PaaS: the API starts every cpu and api node with `docker run` (`packages/providers/local_docker.py`), so the host must have a Docker daemon. That rules out Vercel, Render, Fly and Cloud Run for the API.
- A is not the cheapest. It follows the plan of record (PLAN.md D4: one Nebius CPU VM for API, Postgres and Redis, HTTPS), with two changes: the web app runs on the same VM instead of Vercel, and artifacts use Nebius Object Storage instead of MinIO. It puts the control plane next to the Jobs, Endpoints and bucket it drives and adds no vendor. Proposed fallback **B2 (DigitalOcean 4 vCPU / 8 GiB, $48 a month, about $93 for the window)** if Nebius has not raised our vCPU quota by Oct 25 noon. **B1 (Hetzner) is about $44** but every plan's page said it is currently unavailable.
- From Hari: four answers (Decisions, below; a fifth can wait to D6) and about 75 minutes of his time, mostly in the Nebius console, plus waits. Platform builds everything else in the repo first, with no cloud access.

## Decisions for Hari (defaults in bold)
1. Option and size: **A-M**; A-L (8 vCPU, if intent #3 should run live on the hosted VM); A-S (2 vCPU, intents #1 and #2 only); B2; B1.
2. End date: **tear down Dec 16**; or keep until winners are announced (about Jan 11), which adds about $85 for A-M.
3. Domain: **we own one (tell me which), else buy a `.dev` or `.com` at about $9–13 for the first year**; fallback is a free `<ip>.sslip.io` name (works with Caddy, but may share certificate rate limits with other users of that suffix, unverified, and looks less credible).
4. Who deploys: **Hari, or the Orchestrator session on his Mac, with `scripts/deploy-hosted.sh` (rsync + `docker compose up`), so no agent holds a standing key to the VM**; or give platform a revocable SSH key.
5. Not blocking, decide by D6: hosted `ORCHAPOD_MAX_DAY_USD` (proposed **$5**: at most $75 over 15 days, against $225 at the default $15) and the anonymous scale (the UI is always anonymous, so at 0.1 the run cap is $0.30 and intent #1, estimated $1.72, cannot start; see LOG 2026-10-21T01:14Z).

## What has to be hosted, and the constraints that decide it
| Piece | Today | Hosted |
| --- | --- | --- |
| API | FastAPI/uvicorn, `/health`, WebSocket `/ws/runs/{id}`, `create_all` at start | container on the VM behind Caddy; needs the `docker` CLI and `/var/run/docker.sock`, and the `nebius` CLI for IAM tokens when GPU nodes run (R15) |
| Node containers | `docker run` per cpu/api node (images about 0.3 GB each; data-prep 0.75 GB, quantize 3.9 GB; 8–10 GB in all, estimate) | siblings on the VM's Docker; pulled from GHCR (packages must be public) or built on the VM as `orchapod/<type>:dev` |
| Postgres 16, Redis 7 | compose containers | same containers, on the compose network only (no published ports) |
| Object Storage | MinIO | Nebius Object Storage `https://storage.eu-north1.nebius.cloud`; Lane B jobs need it, and it is the simplest public endpoint for presigned downloads |
| Web | Next.js 15.3.2, `NEXT_PUBLIC_API_URL`/`_WS_URL` baked in at build | container on the same VM, `app.<domain>` |

Constraints: (1) a Docker daemon next to the API; (2) a public https `ORCHAPOD_CONTROL_URL`, because Serverless Jobs call `/internal/*` and have no other log path; (3) the browser fetches eval samples from the bucket and follows presigned download links, so the bucket needs a public endpoint and a CORS rule for the web origin (LOG ruling 2026-10-21T02:06Z); (4) always on from G3 (Oct 27) through Dec 15: PLAN.md says the demo must stay testable for seven weeks after submission, and stage-one checks could come any time after Oct 30.

```
Browser --https--> Caddy :443 (VM) --+--> web  (Next.js)   app.<domain>
                                     +--> api  (FastAPI)   api.<domain>, wss
api --docker.sock--> node containers (cpu/api) --> Token Factory, Tavily, Object Storage
api --> postgres, redis (compose network)        api --> Nebius Jobs/Endpoints (Lane B)
Nebius Jobs/Endpoints --https--> api.<domain>/internal/*   and   Object Storage
```

## Options
Window = Oct 26 to Dec 16, 51 days = 1,224 h = 1.68 months. Each total adds a Nebius bucket (about $1) and the domain (about $11).
| Option | Where | Monthly | Window | Human steps | Main risk |
| --- | --- | --- | --- | --- | --- |
| **A-M** (recommended) | Nebius `cpu-e2` 4 vCPU / 16 GB, 120 GiB | $97 | **$175** | project and billing, vCPU quota, VM, bucket, DNS | quota starts at 0 vCPU in eu-north1 |
| A-S | Nebius 2 vCPU / 8 GB, 60 GiB | $49 | $93 | same | cannot run intent #3 (quantize plus llama.cpp eval) live |
| A-L | Nebius 8 vCPU / 32 GB, 200 GiB | $190 | $330 | same | cost; only for live intent #3 |
| B2 | DigitalOcean 4 vCPU / 8 GiB / 160 GiB | $48 | $93 | card, droplet, DNS, bucket | no Nebius VM story; bucket still needs the Nebius account |
| B1 | Hetzner CX43 8 vCPU / 16 GB (EUR 16.49 excl. VAT; at an assumed 1.15 USD per EUR) | $19 | $44 | account (may need ID or a prepayment), server, DNS, bucket | every plan's page said it is currently unavailable on 2026-10-20 |
| C | Vercel + Render/Fly API + managed DB | not priced | n/a | | **rejected**: no Docker daemon for node containers; moving cpu/api nodes to Serverless CPU Jobs is new provider code, adds job start-up to every node (endpoints take about 5 minutes to reach Running) against a 25-minute target, and meets the same vCPU quota |
| D | Hari's Mac behind a tunnel | $0 | n/a | | **rejected** for the window (sleep, ISP); fine as a throw-away tunnel for one Lane B test before the VM exists |
Optional add-on to any VM option: web on Vercel Hobby ($0; Vercel's FAQ limits Hobby to personal, non-commercial use) or Pro ($20 a month). Not proposed: one more account, CORS and a build-time API URL, for a shell that is useless without the API.
Not proposed either: Nebius Managed PostgreSQL (4 vCPU / 16 GB is about $204 a month for compute alone, more than twice the VM) and free-tier databases (more accounts, cold starts, the same data-loss exposure as a dump).

## Monthly cost, A-M, line by line
| Line | Basis | Per month | Window |
| --- | --- | --- | --- |
| VM compute | 4 vCPU × $0.012 + 16 GiB × $0.0045 = $0.12/h × 730 h | $87.60 | $146.88 |
| Disk (OS, images, Postgres) | 120 GiB network SSD × $0.071 per GiB-month | $8.52 | $14.29 |
| Public IPv4, traffic in/out | listed Free | $0 | $0 |
| Object Storage | $0.0147 per GiB-month (assume 50 GiB), egress $0.015 per GiB | about $0.75 | about $1.20 |
| Domain | first year, once | | about $11 |
| Total | | **about $97** | **about $175** |
A-S: 2 vCPU / 8 GB is $0.06/h = $43.80 a month, window $73.44 + disk $7.14. A-L: 8 vCPU / 32 GB is $0.24/h = $175.20 a month, window $293.76 + disk $23.81. VMs are billed per second; a stopped VM stops compute billing but not disks, and still counts toward quota.
Why 4 vCPU / 16 GB (estimates): the idle stack takes about 1 GB; Lane A nodes are API-bound; quantizing a model of 2B or less needs roughly 6–10 GB for a few minutes, and the llama.cpp eval of 50 GSM8K items on CPU is the slowest CPU step in the product (tens of minutes at 4 vCPU). Go bigger only if that must be live for visitors; otherwise ship intent #3 as the pre-completed golden fixture.

## Not hosting, but it moves in the window (all capped by the existing guard)
| Item | Exposure | Note |
| --- | --- | --- |
| Token Factory | `ORCHAPOD_MAX_DAY_USD` × 15 days: $75 at $5, $225 at $15 | credits are $25 promo + $25 Builders and are shared with development; keep at least $20 unspent for the window (PLAN) or top up |
| Lane B GPU | off by default; one 30-minute L40S wake = $0.78 (1.55 × 0.5) | always on for 15 days = $558; do not, without Hari's yes. An endpoint also bills its 250 GiB disk (about $0.024/h), which PRICES does not include |
| Price drift | Nebius repriced H100 ($3.85 to $4.50) and CPU RAM ($0.0032 to $0.0045 per GiB-h) on Oct 1; L40S unchanged | re-read nebius.com/prices on D7 and the day before the window; the date is in the `prices.py` comment |

## HTTPS and DNS
- Caddy with automatic HTTPS (Let's Encrypt or ZeroSSL): needs ports 80 and 443 open to the internet and an A record per name. WebSockets pass through `reverse_proxy` with no extra directive. Names: `app.<domain>` (web) and `api.<domain>` (API). `ORCHAPOD_CONTROL_URL=https://api.<domain>` for every node, local or GPU.
- Node containers reach that name through the VM's own public IP. Unverified on Nebius (hairpin NAT): test with one `docker run … curl https://api.<domain>/health` on D5. Fallback is three lines in `local_docker.py`: `--add-host <control host>:host-gateway`.
- Bucket CORS: allow GET and HEAD from `https://app.<domain>`. Nebius documents CORS as a `--cors-rules` JSON on `nebius storage bucket create`; an S3 `put-bucket-cors` call is not documented, so create the bucket with the rule and test it with `curl -I -H 'Origin: …'`.

## Uptime and recovery
- External: UptimeRobot free (50 monitors, 5-minute checks, one status page; its pricing page frames the plan as for hobby and non-profit projects; confirm email alerts at signup) or Better Stack free (10 monitors, Slack and email; for personal projects). Three checks: `https://api.<domain>/health`, `https://app.<domain>/agent` (keyword), and the golden run's `/runs/<id>/summary` (keyword `succeeded`, which proves Postgres and the fixture). `/health` is shallow today (returns ok without touching Postgres or Redis); asking backend for a deep check in the D6 hardening.
- On the VM: `restart: unless-stopped`, compose healthchecks, and a one-minute systemd timer that restarts the API after three failed `/health` calls (the PLAN's "uptime monitor with restart"). Logs rotate at 10 MB; weekly `docker image prune`. Unattended upgrades on, automatic reboot off.
- Backups: nightly `pg_dump` to `s3://<bucket>/backups/pg/` with a 14-day lifecycle rule. The golden run is reproducible with `make demo`, so the dump matters mainly for visitors' runs.
- Rebuild target 30 minutes: new VM, cloud-init, `deploy-hosted.sh`, restore, `make demo`. Rehearse it once on D7. One VM is a single point of failure; accepted.
- Daily during Dec 1–15: check the monitors, the Nebius bill, Token Factory credit and the day ledger. Kill switch: `ORCHAPOD_KILL_SWITCH=1` in `/opt/orchapod/.env`, then `docker compose up -d api` (about 10 s; backend to confirm whether it is read per request).

## Security notes
- Firewall allows 22 (Hari's IP if static), 80 and 443 only; only Caddy publishes ports (Docker bypasses UFW for published ports). Postgres, Redis, API and web stay on the compose network. Nebius does not document default security-group behaviour on the pages I read: verify from outside with `nmap`.
- The API container holds `docker.sock`, which is root on the VM. Mitigations: a one-purpose VM, node types come from the registry, anonymous caps, no other secrets on the host.
- Keys on the VM: `NEBIUS_API_KEY` (bounded by credits), `TAVILY_API_KEY`, the Object Storage key, and the service-account profile for Jobs and Endpoints. That profile can create GPU resources up to our quota, so keep the quota at exactly 1 × H100 and 1 × L40S, and use a separate service account for storage than for compute if it costs nothing. Secrets live in `/opt/orchapod/.env` (mode 600), generated by Hari with `openssl rand -hex 32`; I never see them. `ORCHAPOD_INTERNAL_SECRET` is explicit (R17), `ORCHAPOD_ADMIN_TOKEN` blank for the window (no admin runs on the hosted instance; LOG 2026-10-21T01:46Z).
- CORS is `*` with credentials in `apps/api/main.py` ("tighten in production"): backend, D6.

## What needs a human
| # | Who | What | Time | Blocks |
| --- | --- | --- | --- | --- |
| 1 | Hari | Answer the decisions above | 5 min | everything |
| 2 | Hari (Nebius admin) | AI Cloud project and payment method (already on the Human actions list). Administration → Limits → Quotas → "Total vCPUs across non-GPU VMs" in eu-north1: **default is 0** (200 in most other regions), so request 8. Approval time is not documented. Keep GPU quotas at 1 + 1 | 10 min + wait | VM |
| 3 | Hari | Create the VM from my cloud-init (in the console; the `nebius` CLI is not installed yet, and I can supply the commands if you install it): Ubuntu 24.04 CPU image, his SSH public key, public IPv4, security group as above | 15 min | deploy |
| 4 | Hari | Bucket with the CORS rule, a service account and a static access key (commands supplied) | 15 min | artifacts, downloads |
| 5 | Hari or Purva | Domain: confirm or buy; two A records to the VM's IP | 10 min + TTL | HTTPS |
| 6 | Hari | Four random secrets into `.env` on the VM | 5 min | start |
| 7 | Purva | GHCR packages public (already open), or the VM builds the images itself and nothing is needed | 5 min | image pulls |
| 8 | Hari | UptimeRobot (or Better Stack) account, three monitors, alert email | 10 min | monitoring |
Optional: apply for a Nebius compute grant (dev.nebius.com/builders lists a separate application; terms and timing unknown). The Builders Program gives no AI Cloud credit, so the VM is out of pocket.

## What platform builds after a yes (repo only, no cloud access; about 5 h plus 1 h of bring-up with Hari)
`infra/docker-compose.prod.yml`, `infra/Caddyfile`, `infra/cloud-init.yaml`; `apps/api/Dockerfile` (no `--reload`; docker and nebius CLIs) and `apps/web/Dockerfile`; `scripts/deploy-hosted.sh`, `backup-db.sh`, `watchdog.sh`; `docs/HOSTING.md` (deploy, rollback, kill switch, restore, daily check); a test that the prod compose carries exactly the contract Config and publishes only Caddy's ports (same style as `tests/providers/test_env_example.py`). Needed from others: backend (CORS allow-list, deep health, per-IP rate limits), qa (rehearsals against the hosted URL on D8), devrel (demo URL in README and Devpost).

## Timeline
| Date | Step |
| --- | --- |
| Oct 22–24 (D2–D4) | Hari decides; if A, file the vCPU quota request the same day; platform builds the files |
| Oct 25 (D5) noon | quota granted? If not, switch to B2 (droplet in minutes) |
| Oct 25–26 | VM, bucket, DNS, first deploy, `make demo`, monitors on |
| Oct 27 (D7, G3) | feature freeze; hosted demo live; rebuild rehearsal |
| Oct 28–29 | three rehearsals on the hosted app; submit |
| Nov 1 to Nov 30 | leave running; weekly check. A stop-start in November would save about $80 of compute but risks failing an early screening; not proposed |
| Dec 1–15 | judging; daily check |
| Dec 16 | tear down (or Jan 12, Decision 2) |

## Risks
| Risk | Mitigation |
| --- | --- |
| vCPU quota 0 in eu-north1, approval time unknown | request now; B2 trigger Oct 25 noon |
| Single VM dies | 30-minute rebuild path, nightly dump, `make demo` |
| `docker.sock` is root | see Security notes |
| Certificate issuance fails (DNS lag, port 80) | test with Let's Encrypt staging on D5 |
| Disk fills (images, model downloads) | 120 GiB, prune timer, alert at 80% |
| Visitors burn Token Factory credit | day cap $5, anonymous scale, kill switch, credit reserve |
| Service-account key leaks | GPU quota capped at 1 + 1; rotate after Dec 15 |
| Hetzner stays unavailable | not the primary; B2 is the fallback |

## Sources (read 2026-10-20)
- nebius.com/prices: HGX H100 $4.50; L40S Intel from $1.55 (8–40 vCPU, 32–160 GB); L40S AMD from $1.82; CPU instances from $0.06 (Ice Lake 2 vCPU / 8 GB) and $0.13 (Genoa 4 vCPU / 16 GB) per hour; Object Storage Standard $0.0147 per GiB-month, egress $0.0150 per GiB; public IP, traffic: Free.
- docs.nebius.com/compute/resources/pricing: CPU $0.012 (Ice Lake) and $0.015 (Genoa) per vCPU-hour, RAM $0.0045 per GiB-hour from Oct 1 2026; L40S Intel GPU $1.35 + $0.012 per vCPU-hour + $0.0032 per GiB-hour (so `1gpu-8vcpu-32gb` is $1.5484/h), L40S AMD GPU $1.35 + $0.01 + $0.0032 (`1gpu-16vcpu-96gb` is $1.8172/h); network SSD $0.071 per GiB per 730 h; per-second billing.
- docs.nebius.com/serverless/pricing-quotas: Serverless AI uses Compute pricing and quotas. docs.nebius.com/compute/virtual-machines/types: platform ids (`gpu-l40s-a` Intel Ice Lake, `gpu-l40s-d` AMD Genoa, `cpu-e2` eu-north1 only, `cpu-d3` all regions). docs.nebius.com/compute/resources/quotas-limits: non-GPU vCPU default 0 in eu-north1 and us-central1. docs.nebius.com/overview/quotas: quota change path. docs.nebius.com/postgresql/resources/pricing: $0.034 per vCPU-hour, $0.009 per GB-hour. docs.nebius.com/cli/reference/storage/bucket/create: `--cors-rules`. docs.nebius.com/object-storage/interfaces/aws-cli: endpoint, service account and static key.
- dev.nebius.com/builders: Token Factory $25, Tavily $25, no AI Cloud credit. hetzner.com/cloud (cost-optimized and regular-performance pages): CX33 EUR 8.99, CX43 EUR 16.49, every plan marked unavailable; docs.hetzner.com fraud-prevention FAQ (ID or prepayment for some first orders). digitalocean.com/pricing/droplets: $48 and $96. vercel.com/pricing: Hobby and Pro. uptimerobot.com/pricing, betterstack.com/pricing. caddyserver.com/docs/automatic-https. Porkbun listings for `.dev`, `.com`, `.xyz`.
- Not verified: Nebius default security-group behaviour, hairpin NAT, the exact CPU boot-image name, UptimeRobot email alerts on the free plan, Hetzner stock, sslip.io certificate limits, EUR to USD.
