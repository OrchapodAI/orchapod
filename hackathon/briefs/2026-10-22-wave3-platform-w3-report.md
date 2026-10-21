# platform-w3 report — wave 3 (2026-10-22)
Status: DONE · branch `hack/platform-w3` (worktree `/Users/hari/src/orchapod-hack/.claude/worktrees/platform-w3`; `git merge-base --is-ancestor b6c26ff HEAD` = yes; HEAD was ef00bb7 before my commits) · cost $0 (no key used, no cloud resource created, no sign-up; web research only).

## Commits (never pushed; trailer `Co-Authored-By: Claude Sonnet 5.5`)
- `2d9f799` fix(prices): gpu-l40s-a is the Intel L40S at $1.55/h, not the AMD $1.82 — `packages/sdk-py/orchapod/prices.py`, new `tests/providers/test_prices.py`
- `3187692` test(providers): drop the sys.modules workaround for the unsloth fakes — `tests/providers/conftest.py`
- `2fc29d5` test(providers): unique tag for the LocalDocker throwaway image — `tests/providers/test_local_docker.py` (beyond the brief; reason below)
- Not committed on the branch (the Orchestrator commits briefs): `hackathon/briefs/2026-10-22-hosting-proposal.md`, this report.

## Item 1: hosting DECISION proposal (`hackathon/briefs/2026-10-22-hosting-proposal.md`, 137 lines after fix round 1)
- Recommends **A-M: one Nebius `cpu-e2` 4 vCPU / 16 GB VM in eu-north1** (Caddy, API, web, Postgres, Redis in Docker Compose; artifacts in Nebius Object Storage): about **$97 a month, about $173 for Oct 26 to Dec 16** with the domain. Fallbacks if the vCPU quota is not granted by Oct 25 noon: **A-W** (Nebius `cpu-d3` 4 vCPU / 16 GB in eu-west1, default quota 200 vCPU, about $189), then **B2** (DigitalOcean 4 vCPU / 8 GiB, $48 a month, about $96). Hetzner (about $44) is listed but every plan's page said it is currently unavailable. PaaS and a laptop tunnel are rejected with reasons.
- The constraint that decides it: the API starts every cpu/api node with `docker run` (`packages/providers/local_docker.py`), so the host needs a Docker daemon.
- Finding that matters for the schedule: Nebius's default quota for non-GPU vCPUs in `eu-north1` is **0** (200 in most other regions; docs.nebius.com/compute/resources/quotas-limits, row "Total vCPUs across non-GPU VMs"). Any CPU VM there needs a quota request; approval time is not documented.
- Five decisions for Hari, each with a recommended default and a by-date (Oct 24 option and domain, Oct 25 who deploys, Oct 26 caps, about Dec 10 end date) and a one-line reply template. The human checklist is about 80 minutes of Hari's time plus waits, including lowering the GPU quotas (default in eu-north1 is 32 H100 + 32 L40S; a leaked key could run 32 H100s, about $144/h). Platform builds the compose, Caddyfile, cloud-init, Dockerfiles, deploy, backup and watchdog scripts and a runbook after a yes (about 5 h, repo only).
- Not verified, listed in the proposal: Nebius default security-group behaviour, hairpin NAT from node containers to the VM's own public name (fallback: a three-line `--add-host` change), bucket CORS (R21: GET and HEAD from `*`; routes are `--cors-rules` at creation, `bucket update --patch`, or S3 `put-bucket-cors`, listed for the `storage.editor` role), UptimeRobot email alerts on the free plan, Hetzner stock, sslip.io certificate limits, EUR to USD (assumed 1.15). Sizing figures are estimates, not measurements.

## Item 2a: L40S price correction
- **Evidence (read 2026-10-20).** nebius.com/prices: "L40S with Intel CPU" from $1.55 (8–40 vCPU, 32–160 GB), "L40S with AMD CPU" from $1.82 (16–192 vCPU, 96–1152 GB), HGX H100 $4.50. docs.nebius.com/compute/resources/pricing gives the parts: L40S Intel GPU $1.35 + $0.012 per vCPU-h + $0.0032 per GiB-h, so the `1gpu-8vcpu-32gb` preset we use is 1.35 + 0.096 + 0.1024 = **$1.5484/h**; AMD is 1.35 + 0.16 + 0.3072 = $1.8172/h for `1gpu-16vcpu-96gb`. docs.nebius.com/compute/virtual-machines/types maps `gpu-l40s-a` to Intel Ice Lake and `gpu-l40s-d` to AMD Genoa; docs.nebius.com/serverless/pricing-quotas says Jobs and Endpoints bill at Compute rates. So the $1.82 we used belongs to `gpu-l40s-d`; "from" on the price page is the smallest preset, which is the one we run.
- **Change.** `prices.py`: `"gpu-l40s-a": 1.55` with a source comment (the pages, the read date, which platform id is which, and the -d note). H100 stays 4.50, which matches the post-Oct 1 price. `gpu-l40s-d` is not added (no node targets it); the comment says to add 1.82 if one does.
- **Test** `tests/providers/test_prices.py` (pins both GPU rates; new file, so no merge conflict with ml/backend edits to `prices.py` or `test_sdk.py`):
```
with the fix:          1 passed in 0.07s
old value put back:    E  assert (4.5, 1.82) == (4.5, 1.55)   -> 1 failed
```
- **Other files that quote it (for the Orchestrator; I did not edit them):**
  - `docs/contracts.md:72` (Prices section), `:221` (vllm-serve `keep_alive_min`: "L40S costs $1.82/h"), `:290` (R5), `:299` (R14).
  - `docs/agent_knowledge.md:28`.
  - `README.md:173` (table row) and `:175`. devrel-w3 already put a TODO(D8) on `:175`.
  - Suggested wording: "gpu-l40s-a 1.55 (Intel; the AMD gpu-l40s-d is 1.82; nebius.com/prices read 2026-10-20)".
  - Derived figure: R14 and README:175 say Lane B "about $2.8"; at $1.55 it is 25 min × $4.50/h + 30 min × $1.55/h = $1.875 + $0.775 = **$2.65**, still under the $3 cap.
  - Not edited on purpose: `hackathon/LOG.md:96` (append-only journal), the 2026-10-20 contract proposals under `hackathon/briefs/` (historical).
- **Related finds.**
  - `packages/providers/nebius.py:51-57` still carries a legacy `_PRICES` (H100 2.49, H200 3.10, A100 1.89, gpu-l40s 0.99), and `NebiusProvider.quote` returns it to `provider_selector`, so the UI's `price_per_hour` for H100 is $2.49 against the real $4.50. It disappears with the Serverless rewrite (contracts: `quote` reads PRICES); until then a five-line change to read PRICES would fix the display. Not done: out of this item's scope.
  - PLAN.md:41 names `gpu-l40s-d` for Jobs while the contracts default to `gpu-l40s-a`. Which one our quota covers is visible in the console (Administration → Limits → Quotas).
  - A running Endpoint also bills its 250 GiB disk (about $0.024/h, 1.6% of the L40S rate); PRICES has no disk term.

## Item 2b: tests/providers/conftest.py workaround removed
Removed the `_fakes` pop, the `import orchapod.prices` and the `sys.modules.update` (and the now-unused `import sys`). ml-w2's fix (`717650b`) scopes the fakes to test_unsloth_train.py.
```
A  pytest tests/containers/test_unsloth_train.py tests/providers   146 passed   (the order that used to fail)
B  pytest tests/containers tests/providers                          269 passed
C  pytest tests/providers tests/containers/test_unsloth_train.py    146 passed
D  pytest tests                                                     395 passed, 2 skipped (396 with test_prices)
negative control (pre-fix test_unsloth_train.py from 717650b^ restored temporarily, same order, no workaround):
   ModuleNotFoundError: No module named 'orchapod.prices'; 'orchapod' is not a package
   ERROR tests/providers/test_tavily.py, ERROR tests/providers/test_tokenfactory.py -> 2 errors during collection
```
The control file was restored with `git checkout`; the tree was clean afterwards.

## Beyond the brief (revert if unwanted): LocalDocker test flake, `2fc29d5`
- **Symptom.** My first `make check` failed on `test_a_container_that_fails_at_once_keeps_its_exit_code_until_terminate` (it passed alone and on re-runs). Cause: the test built the shared tag `orchapod-test/exit1:latest` and removed it in `finally`, and about eight agents run `make check` against one docker daemon.
- **Reproduction.** Eight runs started 2.5 s apart: 1 failed with `docker run failed (exit=125): Unable to find image 'orchapod-test/exit1:latest' locally`.
- **Fix.** A uuid tag per run. Eight staggered runs afterwards: 8 of 8 passed, no `orchapod-test/exit1` image left. The test still bites: with `--rm` put back into `provision` it fails with `ProvisionError: docker wait failed: … No such container` (file restored).
- Convention worth keeping: any test that builds an image on the shared daemon needs a unique tag.

## Proof
```
make check (worktree root, shared venv, HEAD 2fc29d5):
  ruff check apps packages containers      All checks passed!
  python3 -m pytest tests -q               396 passed, 2 skipped, 55 warnings   (base: 395 passed, 2 skipped)
  pnpm … -C apps/web test                  pass 12, fail 0
  stub e2e                                 SKIP (opt-in: E2E=1)
gitleaks detect --log-opts ef00bb7..HEAD   3 commits scanned, no leaks found
git merge-tree --write-tree NebiusHackathon hack/platform-w3   (main at f4a00fe)   clean tree, no conflicts; main changed none of my four files
```
`ruff check tests/providers` shows one older F841 (`tests/providers/test_vastai.py:181`, an unused variable); `make check` does not lint `tests/`, so I left it.

## What is not done or not verified
- No live Nebius check: the L40S rate comes from the public price page and docs, not the console's price calculator for our project. The console shows the final rate.
- Hosting: nothing was built or created, as the brief says; the unverified list above stands. `make check E2E=1` was not run (orchestrator only). `apps/api/config.py` stays deferred (item 3).

## For the Orchestrator
- Record as DECISION: `gpu-l40s-a` = $1.55/h (Intel, `1gpu-8vcpu-32gb`); $1.82 is `gpu-l40s-d`, unpriced until a node targets it. Then edit contracts (4 lines), agent_knowledge:28 and README:173/:175 as listed; R14's figure becomes about $2.65.
- OPEN DECISION for Hari: hosting, five decisions in the proposal. Time-critical: file the non-GPU vCPU quota request (eu-north1, request 8) the day he says yes, because the default is 0, and lower the GPU quotas to 1 before any service-account key exists.
- Ask the other roles for the hosting prerequisites in the proposal: backend (CORS allow-list, deep `/health`, per-IP rate limits, whether the kill switch is read per request), qa (D8 rehearsals on the hosted URL), devrel (demo URL).
