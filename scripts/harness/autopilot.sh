#!/usr/bin/env bash
# Enable by creating hackathon/AUTOPILOT; disable by deleting it or creating hackathon/STOP.
# Exit 2 = keep working (message on stderr is shown to Claude). Exit 0 = allow the stop.
cd "${CLAUDE_PROJECT_DIR:-.}"
[ -f hackathon/AUTOPILOT ] || exit 0
[ -f hackathon/STOP ] && exit 0
[ -f hackathon/WAITING_FOR_HUMAN ] && exit 0
max=${AUTOPILOT_MAX_ITER:-40}
n=$(cat hackathon/.autopilot_count 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > hackathon/.autopilot_count
[ "$n" -gt "$max" ] && { echo "autopilot: iteration cap $max reached; stopping for human review" >&2; exit 0; }
remaining=$(grep -c "\- \[ \] P0" hackathon/STATE.md 2>/dev/null || echo 0)
if [ "$remaining" -gt 0 ]; then
  echo "autopilot ($n/$max): $remaining P0 tasks remain in hackathon/STATE.md. Run the resume protocol, then continue with the next unblocked task. Create hackathon/WAITING_FOR_HUMAN with a reason if you need a person." >&2
  exit 2
fi
exit 0
