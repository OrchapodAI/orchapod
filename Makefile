# Hackathon targets (see CLAUDE.md). The compose project is pinned so we never touch another stack on this machine.
COMPOSE = docker compose -p orchapod-hack -f infra/docker-compose.dev.yml
PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

up:        ; $(COMPOSE) up -d postgres redis minio
down:      ; $(COMPOSE) down
check:     ; ruff check apps packages containers && $(PY) -m pytest tests -q && if [ -f scripts/e2e_demo.py ]; then STUB=1 $(PY) scripts/e2e_demo.py --stub; else echo "SKIP stub e2e: scripts/e2e_demo.py not written yet (qa)"; fi
e2e:       ; $(PY) scripts/e2e_demo.py --max-cost 3
agent-e2e: ; $(PY) scripts/e2e_agent.py --intent "$(INTENT)" --max-cost 3
demo:      ; $(PY) scripts/seed-golden-run.py
checkpoint:; bash scripts/harness/checkpoint.sh

.PHONY: up down check e2e agent-e2e demo checkpoint
