#!/usr/bin/env bash
set -euo pipefail
cd "${CLAUDE_PROJECT_DIR:-.}"
ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
{
  echo ""; echo "## CHECKPOINT $ts"
  echo "branch: $(git rev-parse --abbrev-ref HEAD) @ $(git rev-parse --short HEAD)"
  echo "dirty files: $(git status --porcelain | wc -l | tr -d ' ')"
  echo "in-progress tasks:"; grep -n "IN_PROGRESS" hackathon/STATE.md 2>/dev/null | head -n 20 || true
  echo "worktrees:"; git worktree list 2>/dev/null || true
} >> hackathon/LOG.md
# Commit only the record, never half-done code: the pathspec keeps anything else that is staged out of the commit
git add hackathon CHANGELOG.md docs 2>/dev/null || true
git commit -qm "chore(checkpoint): state at $ts" -- hackathon CHANGELOG.md docs 2>/dev/null || true
exit 0
