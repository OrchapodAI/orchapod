# Changelog

Dated, user-facing changes made during the Nebius × NVIDIA hackathon submission period (Aug 26 – Oct 30, 2026). Orchapod's first commit is May 4, 2026 (367c605); this file becomes the Devpost "what changed" write-up.

## 2026-10-20
- Repo hygiene: removed a committed SQLite database, compiled Python files and a stray worktree copy; one workflow-schema package instead of two.
- Hackathon build harness: operating manual, plan, state board and journal under `hackathon/`; project hooks and seven agent roles under `.claude/`; `make up / check / e2e / agent-e2e / demo / checkpoint`.
- Quality gate: `make check` is green — ruff pinned to a minimal rule set with 30 lint fixes; CI runs lint and the 153 unit tests on every push.
- Interface contracts v1 (`docs/contracts.md`): node SDK, provider clients, config, data and ML nodes, run state machine, budget guard, events and the Orchapod Agent API; plus the agent's knowledge base (`docs/agent_knowledge.md`).

## 2026-10-02 – 2026-10-08 (Purva)
- Nebius × NVIDIA integration: Nebius Token Factory service and a Nebius provider.
- Synthetic-data pipeline with Nemotron 3 Super as the teacher model (merged from the data-engine branch).
- Token Factory model IDs verified against the live catalog.
- End-to-end executor fixes: database commits, NEBIUS_API_KEY forwarding, container SDK.
- Quick-start docs with Colima/Homebrew setup.
