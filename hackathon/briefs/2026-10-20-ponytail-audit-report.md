# Ponytail audit — NebiusHackathon @ c866d7f (2026-10-20). Read-only: nothing applied, nothing committed.
Scope apps/ packages/ containers/ scripts/ tests/ infra/ (~14.2K code lines). Sizes = lines removed incl. tests; "0 callers" = grep-verified. Weighted by PLAN.md + docs/contracts.md.
† = contradicts a PLAN "Keep" row or the CLAUDE.md stack line: orchestrator decides, do not auto-apply. "->" = replacement. {owner} per ORCHESTRATOR §3; land each cut on that owner's branch.

## A. Ranked cuts (largest first)
1. delete† -2,200  Vast.ai-only one-click deploy + endpoint TTL/extend/email stack (every generated YAML pins provider_pref vastai): web app/inference, app/endpoints, EndpointCountdown, run-page endpoint tab;
   routes/inference.py, /internal/ttl + _terminate_after_ttl, services/email.py, containers/vllm-serve (Cloudflare tunnel), their tests; +371 TryItChat if the compare playground replaces it. -> tf-deploy / serverless-endpoint nodes. {frontend,backend,ml,qa}
2. delete -1,280  Provider layer: providers/vastai.py, providers/nebius.py, services/provider_selector.py, Quote/quote()/get_cost_estimate, /runs/{id}/cost-estimate + canvas quote modal†, tests/providers/test_vastai.py.
   -> a 3-line {cpu: LocalDockerProvider, gpu: serverless provider} lookup on NODE_REGISTRY runtime in the executor. {platform,backend,frontend,qa}
3. delete† -800  Static Registry page + catalogs: routes/models.py (BASE_MODELS, PUBLIC_DATASETS, /node-types with 0 callers), workflow_schema/methods.py + test_methods.py (names containers that don't exist), app/registry. -> node forms carry their own defaults. {backend,frontend,qa}
4. yagni† -550  Second model registry (Model table, routes/model_registry.py, _auto_register_model, app/models, test_models.py). -> the Artifacts page already filters kind=model. {backend,frontend,qa}
5. yagni† -370  Alembic (ini, env, one migration, mako) beside create_all() in the lifespan; only README calls it. -> create_all; add Alembic when a live DB must be migrated. [apps/api/alembic*] {backend}
6. delete -310  containers/synth-distilabel/sdk/ is a byte-identical copy of packages/sdk-py/orchapod. -> repo-root-context "COPY packages/sdk-py/orchapod /app/orchapod", as unsloth-train/Dockerfile already does. {data-eng}
7. delete -325  Node types with no container: hf-import, file-upload, s3-import, auto-label-cleanlab (schemas, registry rows, web tables) and distill-sft (no PLAN row: container, schema, web). -> nothing; PLAN only hides the first four. {backend,frontend,ml}
8. delete† -310  containers/lm-eval once judge-eval lands (PLAN: optional): GPU-heavy, never run, Claude fallback, a vLLM server on :8002 that the in-process "--model vllm" harness doesn't use. {ml}
9. delete -235  0 callers: services/storage.py, components/WorkflowCard.tsx, /internal/node-complete, NodeDef/WorkflowInput/WorkflowSchema (workflow_schema/models.py:236-279), database.SessionLocal + get_db. {backend,frontend}
10. delete -235  Three hand-rolled Token Factory clients: services/nebius_token_factory.py (0 callers), synth TeacherCall._nebius, lm-eval _judge_via_nebius; all on legacy api.studio.nebius.ai (CLAUDE.md: api.tokenfactory.nebius.com).
    -> platform's P0 D1 "TF client" is the only one (openai SDK + base_url: retries, usage counts; SDK only, endpoint stays Nebius), shipped to node images with the SDK; one URL constant. {platform,data-eng,ml}
11. delete -210  Mock/dead UI: 3 "Coming soon" pages, Sidebar fake workspace/budget/user/counts, 9 inert filter/toggle buttons, RunVolumeChart, CSV export, 23 unused CSS classes (PLAN calls dead buttons a judging risk). {frontend}
12. delete -200  scripts/seed-demo-workflow.py (posts to /api/workflows, which doesn't exist; Qwen + RunPod/Vast demo), build-and-push-containers.sh (CI matrix is a second, disagreeing image list), compose api+web services (make up starts only postgres/redis/minio; :8000 is taken). {qa,platform}
13. delete -190  Checkpoint-resume chain: executor _find_resume_checkpoint (run_workflow.py:248-267) reads a fresh NodeRun's empty outputs, so it never fires; SDK checkpoint.py, io.download_directory, unsloth resume + _CheckpointCallback, tautological interval test. -> --max-steps + final upload; re-run the node. {backend,ml}
14. shrink -120  Executor/routes: 19 debug log.warning lines (run_workflow.py x13, runs.py _launch_run x6), unused _launch_run params, 4 add/flush/commit helpers -> one _save(), Kahn loop (dag.py:26-48) -> graphlib.TopologicalSorter,
    field-by-field DTO mappers (runs.py:268-309, workflows._to_out, artifacts.py:65-80) -> ConfigDict(from_attributes=True). {backend}
15. shrink -90  Web: 3 parallel node-type tables (NodePalette, OrchaNode, canvas nodeColor/defaultInputs) -> one; timeAgo x3 -> Intl.RelativeTimeFormat; fmtBytes x2; clsx -> template strings; next.config.ts env block (Next inlines NEXT_PUBLIC_*). {frontend}
16. shrink -50  SDK/provider: io.Inputs wrapper -> plain dict; 2-3 copies of urllib POST (log.py, io.py, vllm-serve) -> one _post(); local_docker._image_exists os.popen("...; echo $?") -> subprocess.run([...]).returncode == 0. {backend,platform}
17. yagni -45  Redis pub/sub (events.py) for a single-process API -> per-run asyncio.Queue ("# ponytail: add Redis back for >1 uvicorn worker"). Judgment call: PLAN hosts Redis on the VM. {backend,platform}
18. delete -13 deps  apps/api/requirements.txt: python-multipart, python-jose, pydantic-settings, python-dotenv, vastai (0 imports), + anthropic, alembic, boto3, redis (die with B, 5, 9, 17); requirements-dev.txt: runpod; hf-download image: httpx; synth image: anthropic; web: clsx.
Not flagged (lean on the golden path): run_workflow.py core, local_docker.py, synth STUB_TEACHER mode, data-prep, hf-download, quantize, SDK io/log.

## B. Non-Nebius model / GPU provider code: must leave the demo path
- Anthropic: agent/workflow_builder.py (168) + POST /workflows/from-prompt (workflows.py:139-169) + web fromPrompt and prompt tab (-> the planned Nemotron /agent/plan); synth _anthropic (run.py:139-150); lm-eval _judge_via_anthropic + use_claude (126-143,152-191);
  anthropic in api/requirements.txt:27 and the synth + lm-eval images; ANTHROPIC_API_KEY forwarded to every node (run_workflow.py:243), compose:84, .env.example:44-47; teacher_kind "anthropic" (workflow_schema/models.py:138).
- OpenAI (the provider): synth _openai, teacher_kind "openai", pricing + key branches (run.py:41-45,126-137,250-258); OPENAI_API_KEY forwarded (run_workflow.py:242). Keep only the openai SDK aimed at Token Factory; the lm-eval image installs openai and never imports it.
- RunPod: no provider module ever existed (dead try/except ImportError, provider_selector.py:24-27,51-52); default provider_pref ["runpod","vastai"] (provider_selector.py:74, canvas/[id]/page.tsx:119, seed script);
  _HOURLY_COST_USD (inference.py:187-193); RUNPOD_POD_ID URL sniffing (vllm-serve/run.py:133-136 + 2 tests); runpod in requirements-dev.txt:12.
- Vast.ai: providers/vastai.py (348; also a second provider registry + pick_provider imported by main.py:21,30 and internal.py:289); "provider_pref: vastai" in generated YAML (inference.py x4) and web /inference; workflow_schema/models.py:63-66;
  vllm-serve/run.py:137-141; compose:81-82; .env.example:38-41; vastai in api/requirements.txt:30; tests/providers/test_vastai.py. Keep the vastai CLI (requirements-dev.txt:11) while spike 4 runs: it uses the CLI, not this module.
- Legacy Nebius Compute API: providers/nebius.py (261; compute.api.eu-north1 /instances, guessed serial-port logs, wait() waits for a VM stop that never comes per PLAN), wired at provider_selector.py:19-22,47-48; NEBIUS_IAM_TOKEN/FOLDER_ID/SUBNET_ID in compose:75-77, .env.example:16-22.
  -> the planned nebius_serverless.py (Jobs + Endpoints); do not keep both.
- Other vendors on the node path: Cloudflare Tunnel (vllm-serve/run.py:22-25,54-123, Dockerfile:4-8, token forwarded at run_workflow.py:245-246), Resend (services/email.py), Clerk keys (.env.example:80-81, no code), Cleanlab node (no container).

## C. Routed to a normal review (correctness/security, not complexity)
- Loss chart is always empty: nothing calls /internal/progress (SDK log.progress posts to /internal/log) while the run page filters type "progress"; wire one or delete both.
- 7 of 8 Dockerfiles use "COPY ../../packages..." and context-relative "COPY run.py", which cannot build from the repo-root context that CI, build-and-push-containers.sh and local_docker's hint use (only unsloth-train is right).
- Webhooks are open when ORCHAPOD_INTERNAL_SECRET is unset (internal.py:46-51) and the SDK never sends X-Orchapod-Secret, so setting it 403s every node; PLAN D2 makes the control URL public.
- model_registry.py uses get_db (never commits): POST /models doesn't persist outside the test override. Canvas buildYamlFromGraph drops "resources:". inference.py writes the user's hf_token into stored YAML (lines 335-336,354,386).

net: -7,400 lines, -13 deps possible (of ~14.2K lines in scope; -3,100 if the † items stay); replacements add ~100 lines.
