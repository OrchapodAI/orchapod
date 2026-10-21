# Hackathon targets (see CLAUDE.md). The compose project is pinned so we never touch another stack on this machine.
COMPOSE = docker compose -p orchapod-hack -f infra/docker-compose.dev.yml
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
# pnpm 11 (this Mac) runs `pnpm install` before every `pnpm test` unless told not to, and leaves an apps/web/pnpm-workspace.yaml that
# broke CI once. CI runs pnpm 9 (plain `pnpm test`); with pnpm 9 locally: make check PNPM=pnpm
PNPM ?= pnpm --config.verify-deps-before-run=false

up:        ; $(COMPOSE) up -d postgres redis minio
down:      ; $(COMPOSE) down
# check = lint + unit tests + web tests. `make check E2E=1` adds the stub e2e of intent #2: it needs Docker and `make up` and builds and
# retags the shared orchapod/<node>:dev images, so only the orchestrator runs it, after merges.
ifeq ($(E2E),1)
E2E_STEP = $(PY) scripts/e2e_demo.py --stub
else
E2E_STEP = echo "SKIP stub e2e: set E2E=1 (orchestrator/integration only)"
endif
check:     ; ruff check apps packages containers && $(PY) -m pytest tests -q && $(PNPM) -C apps/web test && $(E2E_STEP)
e2e:       ; $(PY) scripts/e2e_demo.py --max-cost 3
agent-e2e: ; $(PY) scripts/e2e_agent.py --intent "$(INTENT)" --max-cost 3
demo:      ; $(PY) scripts/seed-golden-run.py
checkpoint:; bash scripts/harness/checkpoint.sh

.PHONY: up down check e2e agent-e2e demo checkpoint
