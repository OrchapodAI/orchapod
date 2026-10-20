#!/usr/bin/env bash
set -euo pipefail
cd "${CLAUDE_PROJECT_DIR:-.}"
# Most important first; the 9,800-character cap truncates only the LOG tail (the resume protocol reads it in full anyway)
{
echo "=== RESUME PROTOCOL: read STATE, then LOG tail, then continue from Next actions. Manual: hackathon/ORCHESTRATOR.md ==="
[ -f hackathon/WAITING_FOR_HUMAN ] && echo "!!! WAITING_FOR_HUMAN is set: $(cat hackathon/WAITING_FOR_HUMAN)"
echo "--- git ---"; git status -sb 2>/dev/null | head -n 20; git log --oneline -10 2>/dev/null; git worktree list 2>/dev/null
echo "--- hackathon/STATE.md (head) ---"; head -n 120 hackathon/STATE.md 2>/dev/null || echo "(no STATE.md yet — run bootstrap §2)"
echo "--- hackathon/LOG.md (tail) ---"; tail -n 40 hackathon/LOG.md 2>/dev/null || true
} | head -c 9800 || true
exit 0
