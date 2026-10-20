# Changelog

Dated, user-facing changes made during the Nebius × NVIDIA hackathon submission period (Aug 26 – Oct 30, 2026). Orchapod's first commit is May 7, 2026; this file becomes the Devpost "what changed" write-up.

## 2026-10-20
- Repo hygiene: removed a committed SQLite database, compiled Python files and a stray worktree copy; one workflow-schema package instead of two.
- Hackathon build harness: operating manual, plan, state board and journal under `hackathon/`; project hooks and seven agent roles under `.claude/`; `make up / check / e2e / agent-e2e / demo / checkpoint`.
- Started the interface contracts (`docs/contracts.md`) and the Orchapod Agent knowledge base (`docs/agent_knowledge.md`).

## 2026-10-02 – 2026-10-08 (Purva)
- Nebius × NVIDIA integration: Nebius Token Factory service and a Nebius provider.
- Synthetic-data pipeline with Nemotron 3 Super as the teacher model (merged from the data-engine branch).
- Token Factory model IDs verified against the live catalog.
- End-to-end executor fixes: database commits, NEBIUS_API_KEY forwarding, container SDK.
- Quick-start docs with Colima/Homebrew setup.
