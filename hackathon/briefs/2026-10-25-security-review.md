# Security review — Orchapod (NebiusHackathon, HEAD 1000c82)

Read-only static review for the Oct 27 open-sourcing. Threat actor: anonymous internet users of
`api.orchapod.dev` / `app.orchapod.dev` who can also read every line of the repo. Scope and rules per the
review brief. No network calls were made; the local uvicorn source was read to confirm one behaviour.

Counts: 0 critical, 1 high, 1 medium, 5 low.

Most of the money- and secret-exfiltration surface is sound: the ModelRef key↔URL pairing is enforced in
four independent places, GPU spend is admin-only behind `gpu_guard`, and no code-execution path was found in
the node containers an anonymous user can launch. The findings below are the gaps.

---

## H1 (high) — X-Forwarded-For spoofing defeats every per-IP rate limit

**Where:** `apps/api/services/ratelimit.py:29-38` (`address()` → `request.client.host`);
`apps/api/Dockerfile:40` (`uvicorn … --forwarded-allow-ips "*"`); `infra/Caddyfile:13-19` (no XFF override;
the comment at `:3-5` claims Caddy "replaces any X-Forwarded-For a client sends").

**Attack (inputs → effect):** a client sends `X-Forwarded-For: 1.2.3.4` (any value). Caddy's `reverse_proxy`
default *appends* the real peer rather than replacing, so uvicorn receives `1.2.3.4, <real-ip>`. uvicorn
0.32.1 with `forwarded_allow_ips="*"` returns the **leftmost** entry as the client host
(`_TrustedHosts.get_trusted_client_host` → `x_forwarded_for_hosts[0]`, confirmed in
`.venv/.../uvicorn/middleware/proxy_headers.py`). So `request.client.host` is fully attacker-chosen. Rotating
the header per request yields unlimited fresh token buckets, bypassing the `plan`/`run`/`compare`/`write`
limits entirely.

**Why existing controls don't stop it:** the rate limiter is the *only* per-caller throttle. The day cap and
kill switch bound dollars but not row creation, and `compare`'s `_slots` semaphore bounds only concurrency.
With the bypass an attacker (a) drains the shared anonymous day pot (`ORCHAPOD_MAX_DAY_USD × ORCHAPOD_ANON_SCALE`
= $1.50) in minutes via `/agent/plan` + `/compare`, denying all other anonymous visitors for the rest of the
UTC day; and (b) creates **unbounded** workflows / runs / models (the `write` bucket is the only guard on those
and they cost $0, so no budget stops them) — DB growth on the single VM and the golden run pushed out of the
500-row listings that `/runs` and `/workflows` cap at (the exact harm `ratelimit.py:22-23` names).

**Smallest fix:** make Caddy overwrite the header, as its own comment already promises — in `infra/Caddyfile`
the `api.{$DOMAIN}` block:

```
reverse_proxy api:8000 {
    header_up X-Forwarded-For {remote_host}
}
```

Then uvicorn's leftmost entry is the Caddy-set real client IP. (Equivalent: drop `--forwarded-allow-ips "*"`
and set it to Caddy's address only.)

---

## M1 (medium, unconfirmed) — data-prep runs `load_dataset` on an attacker repo with an unpinned `datasets` and no `trust_remote_code=False`

**Where:** `containers/data-prep/run.py:66` (`load_dataset(repo, name=hf_config, split=hf_split)`);
`containers/data-prep/Dockerfile:3` (`pip install … datasets …`, unpinned).

**Attack (inputs → effect):** data-prep is `cpu`, so an anonymous caller may run it. A node input
`dataset: "<attacker-org>/<repo>"` (any value with a `/` and no leading `/`) is passed straight to
`load_dataset`. On `datasets` < 2.20, `load_dataset` executes the repo's loader `.py` script in-process (it
defaulted to trusting remote code). That container holds the full secret env — `NEBIUS_API_KEY`,
`TAVILY_API_KEY`, `HF_TOKEN`, `ORCHAPOD_ENDPOINT_TOKEN`, the R2 access/secret keys and
`ORCHAPOD_INTERNAL_SECRET` — so a loader script is remote code execution with every platform secret.

**Why existing controls don't stop it:** nothing validates the dataset id, and the code never passes
`trust_remote_code=False`. Whether it is live today depends on the version the image build resolves: `datasets`
3.x removed remote dataset scripts, so a fresh build is likely safe — hence **unconfirmed** — but the pin is
absent, so a rebuild or a transitive downgrade silently reopens it.

**Smallest fix:** pin `datasets` to a current 3.x line in the Dockerfile and pass `trust_remote_code=False`
explicitly at the call; optionally reject dataset ids that aren't a plain `<org>/<name>`.

---

## L1 (low) — `/internal/*` is internet-facing on the hosted deploy, guarded only by one shared bearer

`apps/api/routes/internal.py` + `infra/docker-compose.prod.yml:53` (`ORCHAPOD_CONTROL_URL: https://api.${DOMAIN}`).
Nodes post webhooks to the public `api.orchapod.dev/internal/*`, so artifact/cost/ttl/log registration is
reachable from the internet, protected solely by `X-Orchapod-Secret`. The secret sits in every node
container's env (see L2); a single leak lets an attacker forge cost_json / artifacts and register or supersede
endpoint TTLs. By design (R17, because GPU Jobs live on Nebius), but the surface is wide — scope `/internal`
to the compose network / a mesh where the deployment allows, or add a second factor.

## L2 (low) — full platform secret set forwarded into every cpu/api node container

`apps/api/executor/run_workflow.py:52-54` (`FORWARD`) + `_build_env` give every node the same env, including
`ORCHAPOD_INTERNAL_SECRET`, both R2 keys and `ORCHAPOD_ENDPOINT_TOKEN`. On the hosted VM these are
visitor-launchable sibling containers (docker.sock mounted, `docker-compose.prod.yml:69`). No node-level RCE
exists today, so the blast radius is latent, but any future exec bug or malicious dependency in one image =
total secret compromise. Forward per-node least privilege (e.g. hf-download/quantize need no
`ORCHAPOD_ENDPOINT_TOKEN`; only web-research needs `TAVILY_API_KEY`).

## L3 (low) — `/inference/deploy` hardcodes `provider_pref: [vastai]`

`apps/api/routes/inference.py:200-202,219-220,231-233,248-250`, against the contract's default (`nebius`;
vast.ai is spikes-only). Harmless while `VASTAI_API_KEY` is unset and GPU nodes are admin-only, but it would
silently route a deploy's vllm-serve/quantize-serve to vast.ai the moment that key is ever set. Use the
default `provider_pref` (nebius) or omit the block.

## L4 (low, by-design) — no tenant isolation on artifacts

`apps/api/routes/artifacts.py:48-94`: `GET /artifacts` lists every run's artifacts and
`GET /artifacts/{id}/download` 307s to a 1-hour presigned URL for any artifact UUID, both unauthenticated.
Any visitor can enumerate and download every dataset / model / eval across all users. Intended for the no-auth
public demo (D6, R21, bucket GET-from-`*`); flagged so it stays a conscious choice, not an oversight.

## L5 (low, defense-in-depth) — TokenFactory last-hop pair check covers only `NEBIUS_API_KEY`

`packages/providers/tokenfactory.py:96-97` refuses the Token Factory key to a non-TF `base_url`, but there is
no equivalent guard for `ORCHAPOD_ENDPOINT_TOKEN`: if a ref with `api_key_env="ORCHAPOD_ENDPOINT_TOKEN"` and an
attacker `base_url` ever reached `.chat()`, the client would send the endpoint token there. Today the
application-layer checks (`compare._registered`, judge-eval's artifact-provenance check, the plan validator)
all block that, so it is not reachable — but the client should fail closed too: refuse any non-empty key whose
value equals `ORCHAPOD_ENDPOINT_TOKEN` going off the registered endpoint host.

---

## Checked and found sound

- ModelRef key↔URL pairing enforced in planner (`_model_ref_problems`/`_input_problems`), `/compare` (`_key`),
  judge-eval (`model_ref`) and the TF client — anonymous callers can't redirect our keys to a chosen URL.
- GPU spend is admin-only: `gpu_guard` on plan/run/retry/deploy, the executor's `scale<1` refusal, and
  `/agent/plan` `admin_only`; `budget.gpu_nodes` counts `rents_gpu` (vllm-serve) as GPU.
- Budget guard: run/day caps × anon scale, kill switch (fail-safe on typo), in-process grants reserve
  in-flight spend so concurrent runs can't exceed the day cap; control-plane spend ledgered.
- cost_json reconcile caps an attempt at 2× run cap, refuses non-finite usd, counts a seq once;
  `/internal/artifact` refuses `kind: endpoint` (only `/internal/ttl` records endpoints).
- Redaction: `redact()` on all meta out, `redact_text()` on stored/broadcast logs (cut to 2000 chars first),
  `without_secrets()` drops secret-looking node inputs on store; `_env` keys keep only env-name values.
- `fence()` neutralises tag-closing in untrusted text (Unicode-tag de-disguise + NFKC, to a fixpoint); used in
  judge-eval and the data-prep quality filter with explicit "untrusted" markers.
- `/internal/*` requires `X-Orchapod-Secret` via constant-time compare; random per-process default when unset;
  hosted sets it explicitly; endpoint_id validated against `^[a-z0-9][a-z0-9-]{0,62}$` before any REST path use.
- Cancel token returned once, only its SHA-256 stored, anonymous cancel needs it (constant-time) — no
  cross-run cancel; workflows with runs are read-only to anonymous callers.
- Workflow YAML: aliases refused and 256 KB cap (billion-laughs guard); DAG validates node types, `needs`, and
  Kahn cycle check; refs resolve only at top level.
- Nebius IAM token only to vllm-serve (`rents_gpu`); dropped from GPU Job env; never logged; `TOKEN` regex
  keeps it out of headers/errors; `Pod.error` scrubs URLs/Bearer/host:port/IP.
- `files.content` redirect follow: https-only, ≤3 hops, httpx drops Authorization cross-origin, redirect
  target's error body never logged.
- Web app has no `dangerouslySetInnerHTML`; EvalView linkifies `source_url` only when `^https?://`, ReportBody
  only `/artifacts/{uuid}/download` paths — all other model/API text is React text nodes (no XSS sink found).
- CORS: hosted uses an explicit origin allowlist with no credentials; the dev-only regex goes through
  Starlette `fullmatch` (anchored) and still sends no credentials.
- CI: no cloud secrets in any job, no `pull_request_target`, fork PRs lack `packages: write`, prod images built
  not pushed.
- `.env`, `/nebius/`, `*.db`, `/deploys.log` are gitignored and `.env` is not tracked at HEAD (full git-history
  secret scan is the gitleaks job's domain — unconfirmed here).
- No `shell=True` / `os.system` / `eval` / `exec` / unsafe-yaml / pickle-of-untrusted in reachable code;
  `local_docker._image_exists` uses `shlex.quote` on an enum-validated node type.
- Startup sweep only terminates LocalDocker containers labelled with this API's own `ORCHAPOD_CONTROL_URL`.
