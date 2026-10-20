#!/usr/bin/env bash
set -euo pipefail
cd "${CLAUDE_PROJECT_DIR:-.}"
echo "=== RESUME PROTOCOL: read STATE, then LOG tail, then continue from Next actions. Manual: hackathon/ORCHESTRATOR.md ==="
echo "--- hackathon/STATE.md (head) ---"; head -n 120 hackathon/STATE.md 2>/dev/null || echo "(no STATE.md yet — run bootstrap §2)"
echo "--- hackathon/LOG.md (tail) ---"; tail -n 40 hackathon/LOG.md 2>/dev/null || true
echo "--- git ---"; git status -sb 2>/dev/null | head -n 20; git log --oneline -10 2>/dev/null; git worktree list 2>/dev/null
[ -f hackathon/WAITING_FOR_HUMAN ] && echo "!!! WAITING_FOR_HUMAN is set: $(cat hackathon/WAITING_FOR_HUMAN)"
exit 0
