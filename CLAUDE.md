# Orchapod.ai — hackathon build (Nebius × NVIDIA)

You are part of a multi-agent build led by the Orchestrator. Operating manual: hackathon/ORCHESTRATOR.md. Backlog: hackathon/PLAN.md. Board: hackathon/STATE.md. Journal: hackathon/LOG.md.

## Resume protocol (do this first after any start, resume, or compaction)
1. Read hackathon/STATE.md, then the last 60 lines of hackathon/LOG.md.
2. Run: git status -sb && git log --oneline -15 && git worktree list
3. Continue from "Next actions" in STATE.md. Do not re-plan finished work.

## Non-negotiables
- Every workflow calls Nemotron on Nebius Token Factory (base URL https://api.tokenfactory.nebius.com/v1). No Anthropic/OpenAI/other model providers in the demo path.
- Nothing is "done" without a test, a doc line, and a LOG entry with evidence (run id, cost).
- Spend caps: $3 per run, $15 per day, Serverless Job timeout 1h. Ask a human before exceeding.
- Secrets only in .env; never commit them. Edit only the paths your role owns (see ORCHESTRATOR.md §3).
- Conventional commits; commit small and often on your branch; the Orchestrator merges into and pushes NebiusHackathon, the only shared branch (never force-push).

## Machine notes (Hari's Mac)
- Checkout ~/src/orchapod-hack (outside iCloud). Shared venv .venv: Python 3.12, third-party deps only (no editable installs, so worktrees import their own code).
- Host ports 8000 (complychip2) and 8001 (complychip-ED) and the complychip* compose projects belong to other projects: never stop, recreate or `down` them. Our compose project is `orchapod-hack`; on this Mac the orchapod API runs on 8002 (set in .env); the documented default elsewhere is 8001.
- pnpm here is v11 (CI uses 9): run web commands with `pnpm --config.verify-deps-before-run=false …`.

## Commands
make up        # postgres + redis + minio (docker compose project orchapod-hack)
make check     # lint + unit + stub-mode e2e (fast, no spend)
make e2e       # real golden path, budget-capped — QA agent only
make agent-e2e INTENT="..."   # one canonical intent through the Orchapod Agent
make demo      # seed the golden run fixture for the hosted app
make checkpoint

## Stack
FastAPI + SQLModel + Alembic + Postgres (apps/api), Next.js 15 + React Flow (apps/web), one Docker container per node (containers/*), node SDK (packages/sdk-py), providers (packages/providers). Nodes read ORCHAPOD_NODE_INPUTS, write artifacts via the SDK, log via /internal/log. See docs/NODE_CONTRACT.md and docs/contracts.md.

## Skills to use
superpowers (brainstorming → writing-plans → executing-plans → TDD → systematic-debugging → verification-before-completion), ponytail (/ponytail full; /ponytail-review before merge). Install missing skills when needed and log them in STATE.md → Tooling.
