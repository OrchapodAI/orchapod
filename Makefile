# Hackathon targets (see CLAUDE.md). The compose project is pinned so we never touch another stack on this machine.
COMPOSE = docker compose -p orchapod-hack -f infra/docker-compose.dev.yml
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
# pnpm 11 (this Mac) runs `pnpm install` before every `pnpm test` unless told not to, and leaves an apps/web/pnpm-workspace.yaml that
# broke CI once. CI runs pnpm 9 (plain `pnpm test`); with pnpm 9 locally: make check PNPM=pnpm
PNPM ?= pnpm --config.verify-deps-before-run=false

up:        ; $(COMPOSE) up -d postgres redis minio
down:      ; $(COMPOSE) down
# check = lint + unit tests + web tests. `make check E2E=1` adds the stub e2es: intent #2 through the workflow API, then the three
# canonical intents and the golden path (template 4) through the Agent; a plan that names a missing piece fails them, nothing SKIPs.
# They need Docker and `make up` and build and retag the shared orchapod/<node>:dev images, so only the orchestrator runs them, after merges.
ifeq ($(E2E),1)
E2E_STEP = $(PY) scripts/e2e_demo.py --stub && $(PY) scripts/e2e_agent.py --stub
else
E2E_STEP = echo "SKIP stub e2e: set E2E=1 (orchestrator/integration only)"
endif
check:     ; ruff check apps packages containers && $(PY) -m pytest tests -q && $(PNPM) -C apps/web test && $(E2E_STEP)
# The Playwright smoke of the web app, STUB and $0 (Docker, `make up`, node and pnpm): scripts/e2e_ui.py starts the API, a second API at the public scale and `next dev`, and
# builds and retags the same shared orchapod/<node>:dev images, so it is orchestrator-only too, like `make check E2E=1`.
# UI_ARGS goes to scripts/e2e_ui.py: make ui-smoke UI_ARGS="-g golden" runs the tests whose title matches.
# pnpm 11 exits 1 on apps/web (ERR_PNPM_IGNORED_BUILDS: sharp, harmless): hence the "-" before its install.
ui-deps:
	-pnpm -C apps/web install --frozen-lockfile
	pnpm -C tests/ui install --frozen-lockfile
	pnpm -C tests/ui exec playwright install chromium  # a fresh clone has no browser; a cached one makes this a no-op
ui-smoke: ui-deps ; $(PY) scripts/e2e_ui.py $(UI_ARGS)
# make e2e API=https://api.<domain> [MAX_COST=3]: the LIVE golden run (template 4, Lane B: an H100 Job, an L40S endpoint, the Ultra judge) on the
# HOSTED API, as its admin (ORCHAPOD_ADMIN_TOKEN in the shell). It rents GPUs and spends up to MAX_COST (3 at most; MAX_COST is set below),
# so it is the orchestrator's, on G2 day, after the prerequisites in hackathon/briefs/2026-10-22-qa-w9-report.md. It starts no local stack.
e2e:       ; $(PY) scripts/e2e_demo.py --max-cost "$(MAX_COST)" --api "$(API)"
# make agent-e2e INTENT=2 MAX_COST=0.5: ONE intent through the Agent for real, capped at MAX_COST (default and most: 3). It spends,
# so it is the orchestrator's: .env loaded (set -a; . ./.env; set +a), `make up`, and it retags the shared orchapod/<node>:dev images.
MAX_COST ?= 3
agent-e2e: ; $(PY) scripts/e2e_agent.py --intent "$(INTENT)" --max-cost "$(MAX_COST)"
demo:      ; $(PY) scripts/seed-golden-run.py
checkpoint:; bash scripts/harness/checkpoint.sh

.PHONY: up down check ui-deps ui-smoke e2e agent-e2e demo checkpoint
