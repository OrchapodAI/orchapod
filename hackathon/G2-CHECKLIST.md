# G2 checklist — the live golden run (Lane B, template 4)

From qa-w9's report (hackathon/briefs/2026-10-22-qa-w9-report.md), reviewed twice. One command runs it once everything below is true:
`caffeinate -i make e2e API=https://api.<domain> MAX_COST=3` with `ORCHAPOD_ADMIN_TOKEN` in the shell (the orchestrator runs it).
Day cap: Hari raised ORCHAPOD_MAX_DAY_USD to **10 for G2 day** (2026-10-24), so two attempts fit ($2.92 worst case each, plus at most $1 of visitors at scale 0.1). Set it back to 5 after the golden run (`dc up -d api`, between runs).

Sources: `docs/HOSTING.md` (bring-up steps are cited as "HOSTING n"), `.env.example`, `infra/docker-compose.prod.yml`,
`hackathon/briefs/2026-10-22-hosting-proposal.md`, contracts R14/R15/R25. A box is something that must be true before `make e2e` runs.
"New" marks what the golden run needs beyond the anonymous demo.

### A. Nebius console (Hari)
- [ ] AI Cloud project and billing; the project id (`project-...`) is `NEBIUS_PROJECT_ID`. (Registers the nebius provider; GPU nodes need it.)
- [ ] **Quotas in eu-north1** (Administration, Limits, Quotas): GPU H100 at least **1** (`gpu-h100-sxm`, preset `1gpu-16vcpu-200gb`) and
  GPU L40S at least **1** (`gpu-l40s-a`, preset `1gpu-8vcpu-32gb`) are what G2 asks; non-GPU vCPUs at least 8 for the VM (starts at 0).
  The defaults are 32 + 32: lower them to 1 + 1 before any key exists (a leaked key could rent 32 H100s, about $144/h). Re-read the page
  after each request. The Job and the endpoint run one after the other, so 1 + 1 is enough; a **leftover endpoint holds the only L40S**.
- [ ] Object Storage bucket in eu-north1 with the CORS rule `[{"allowed_origins":["*"],"allowed_methods":["GET","HEAD"],"max_age_seconds":3600}]`
  (R21), plus a service account with storage access and its static key. (HOSTING 3)
- [ ] **New:** a compute service account that may create and delete Serverless Jobs and Endpoints in the project; its private key file goes to
  `/opt/orchapod/nebius/` on the VM, then `dc exec api nebius profile create --parent-id ... --service-account-id ... --public-key-id ...
  --private-key-file-path /root/.nebius/<file>` (R15; HOSTING 8). `NEBIUS_IAM_TOKEN` stays blank.
- [ ] VM (`cpu-e2`, 4 vCPU / 16 GB, 120 GiB), DNS A records `app.<domain>` and `api.<domain>`, HTTPS from Caddy. (HOSTING 1, 2)

### B. `/opt/orchapod/.env` on the VM (mode 600); nothing here is ever committed
| Name | Where it comes from | What the golden run uses it for |
| --- | --- | --- |
| `DOMAIN` | the domain Hari bought (orchapod.dev) | `ORCHAPOD_CONTROL_URL=https://api.<domain>`: the Job reports there (NebiusProvider refuses http) |
| `POSTGRES_PASSWORD` | `openssl rand -hex 32` | the database |
| `ORCHAPOD_INTERNAL_SECRET` | `openssl rand -hex 32` (R17) | every node's calls to `/internal/*` |
| **`ORCHAPOD_ADMIN_TOKEN`** | `openssl rand -hex 32` | **the script's token.** Blank = nobody is the admin: the run is anonymous and a GPU node is a 403. |
| **`ORCHAPOD_ENDPOINT_TOKEN`** | `openssl rand -hex 32` | the L40S endpoint's bearer. **New:** blank makes vllm-serve fail before it calls Nebius. |
| `NEBIUS_API_KEY` | tokenfactory.nebius.com, API keys | Super (synth teacher, the report) and Ultra (the judge) |
| `TAVILY_API_KEY` | app.tavily.com, API keys | web-research over the docs seed URLs |
| `HF_TOKEN` | huggingface.co/settings/tokens (read) | not needed by Nemotron Nano (open weights, R25); keep it for the Llama templates |
| `ORCHAPOD_R2_ENDPOINT` = `https://storage.eu-north1.nebius.cloud`, `ORCHAPOD_R2_REGION` = `eu-north1` | HOSTING 4 | artifacts; the Job and the endpoint mount the bucket, and the clients refuse a non-https endpoint |
| `ORCHAPOD_R2_ACCESS_KEY`, `ORCHAPOD_R2_SECRET_KEY`, `ORCHAPOD_R2_BUCKET` | the storage service account and bucket above | same |
| `NEBIUS_PROJECT_ID` | the project id above | **New:** gpu nodes |
| `ORCHAPOD_MAX_DAY_USD` = `10` on G2 day, then `5`; `ORCHAPOD_ANON_SCALE` = `0.1` | Hari, 2026-10-24 (G2 day) and decision 5 | the day cap this run lives under |
- Leave at their defaults: `ORCHAPOD_MAX_RUN_USD` 3 (the compose default; the template is estimated at $2.6627), `ORCHAPOD_KILL_SWITCH` 0,
  `ORCHAPOD_NODE_TIMEOUT_S` 5400. **`STUB` must be blank:** a stubbed API runs the plan at $0 with a `stub-*` endpoint, and the script
  fails it for both. `VASTAI_API_KEY` is never on the VM.

### C. Images
- [ ] GHCR packages public (Purva), above all **`ghcr.io/bangadpurva/unsloth-train:latest`** (about 20 GB, CUDA): Nebius Jobs pull it anonymously.
  CI builds and pushes it on NebiusHackathon (after clearing runner disk): check the last CI run for the commit being deployed is green.
- [ ] The cpu and api nodes on the VM run from GHCR, or from `orchapod/<node>:dev` built on the VM (HOSTING 6). A stale `:dev` image shadows
  `:latest` for good: rebuild or remove them after every deploy.
- Nothing to do for `vllm/vllm-openai:v0.18.0-cu130`: Nebius pulls it from Docker Hub when the endpoint starts.

### D. The deployed code and the checks on the VM (HOSTING 5, 9)
- [ ] The VM runs a commit that includes template 4, the unsloth-train and vllm-serve nodes, and NebiusProvider (`ssh <vm> tail -3 /opt/orchapod/deploys.log`).
- [ ] `curl -fsS https://api.<domain>/health` is `{"status": "ok"}` (it checks the database, Redis and the bucket); `dc ps` shows every service healthy.
- [ ] Hairpin NAT: `sudo docker run --rm curlimages/curl -fsS https://api.<domain>/health` passes (the VM's own nodes log through that name).
- [ ] Bucket CORS: `curl -s -o /dev/null -D - -H 'Origin: null' '<a presigned GET url>'` shows `Access-Control-Allow-Origin: *`.
- [ ] Suggested, not in HOSTING: the api container can mint a Nebius token: `dc exec api sh -c 'nebius iam get-access-token >/dev/null && echo ok'`.
- [ ] Console: the Jobs and Endpoints lists are empty.

### E. The operator's machine (where `make e2e` runs)
- [ ] The repo at the deployed commit, `.venv` as in the README. No Docker, no `make up`, none of the `.env` keys are used.
- [ ] `read -s ORCHAPOD_ADMIN_TOKEN; export ORCHAPOD_ADMIN_TOKEN` with the VM's value (not in `.env`, not on a command line, so not in shell history).
- [ ] **A free preflight:** `make e2e API=https://api.<domain> MAX_COST=1`. It must exit 2 with "the golden path's full estimate $2.6627 is over
  --max-cost $1" after one read. That proves DNS, TLS, the template served and its shape, and it starts nothing. **It does not prove the
  token** (the token is only sent by the POST that starts the run). The first proof is that POST: a wrong or missing admin token gets a 403
  ("check ORCHAPOD_ADMIN_TOKEN"), which starts nothing and costs nothing. Without any token the script refuses with
  `ORCHAPOD_ADMIN_TOKEN is unset`.
- [ ] A way to cancel from a second terminal or a phone:
  `curl -X POST -H "X-Orchapod-Admin: $ORCHAPOD_ADMIN_TOKEN" https://api.<domain>/runs/<run id>/cancel`.

### F. Budget arithmetic (the part most likely to bite)
- `POST /agent/run` answers **402** unless `min(run cap 3, day cap 5 - today's spend)` is at least the plan's estimate, $2.6627. So the UTC day
  must have **at most $2.33 spent** before the run starts. Spend includes the anonymous visitors' planner, reporter and /compare calls.
- The run's worst case is $2.92 (R14) plus the report (about $0.004), so a normal first attempt ($2.4 to $2.9) leaves $2.1 to $2.6 of the $5,
  under the $2.66 a second attempt needs: it will be refused with 402. **Plan one attempt per UTC day** (the day resets at 00:00 UTC), unless Hari raises
  `ORCHAPOD_MAX_DAY_USD` in `/opt/orchapod/.env` and runs `dc up -d api` (that fails runs in flight, so do it between runs). A run that
  fails early is cheap and does not use the day up.
- No endpoint shows today's spend. On the VM (not run by me): `dc exec postgres psql -U orchapod -d orchapod -c "select coalesce((select sum(cost_usd)
  from run where created_at >= date_trunc('day', now() at time zone 'utc')),0) + coalesce((select sum(usd) from spend where created_at >=
  date_trunc('day', now() at time zone 'utc')),0) as spent_today"`.
- Attempt it before the app goes public (G3, Oct 26), so visitors do not eat the day.

### G. The run
- [ ] `caffeinate -i make e2e API=https://api.<domain>` (MAX_COST defaults to 3; `caffeinate -i` keeps the Mac awake, since a sleeping Mac
  stops polling). Expect 25 to 50 minutes and, in a healthy worst case, 75 to 87; the script waits up to two hours. Keep the terminal open.
  The run id is on the line that starts `e2e: started run`; the run page is `https://app.<domain>/runs/<run id>`.
- [ ] No deploy and no API restart while it runs (a restart fails the run in flight: "control plane restarted"), nor in the 15 minutes after
  (the API deletes the endpoint at its TTL; a restart re-arms the timer from the database, but do not rely on it).
- The first run pays for a cold pull of the 20 GB training image inside the first GPU node's wall time; it counts against G1's 25 minutes.

### H. If it goes wrong
- Ctrl-C cancels the run: `cancelling run <id> (up to 90 s)`, then `cancelled run <id>` (it tries twice). A line that starts
  `run <id> may still be running; cancel it as the admin: curl ...` means it is not cancelled: run that curl (with `ORCHAPOD_ADMIN_TOKEN`
  exported). It is also what an API that is down for good ends with, at the two-hour limit.
- Soft stop: `ORCHAPOD_KILL_SWITCH=1` in the VM `.env`, then `dc up -d api` (fails the runs in flight and terminates their pods).
  Hard stop and the leftovers sweep: HOSTING "Kill switch".
- Then the console: delete any Job or Endpoint still running (the API deletes endpoints at their TTL only while it runs). A lost
  `POST /agent/run` reply says "the run may have started": find the plan name in the runs list and cancel it.

### I. After a PASS or a FAIL
- [ ] Record in `hackathon/LOG.md` and STATE "Golden path status": the PASS/FAIL line, the run id, the cost, the per-node times, the 25-minute
  verdict and the endpoint's `expires_at`.
- [ ] A day or two later, the Nebius bill lists no running Job or Endpoint line items.
- [ ] Once a good run exists: export it as the hosted fixture (HOSTING 7, D8: `seed-golden-run.py --export <run_id>`, `scp`, gitleaks, commit).
