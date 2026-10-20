#!/usr/bin/env bash
# Spike 4 vast.ai lifecycle, run on the Mac with the venv's vastai CLI and VASTAI_API_KEY (never sent to the host).
#   vast.sh up OFFER_ID DISK_GB   create ONE instance, then start a watchdog shell whose EXIT trap destroys it;
#                                 the watchdog exits at the hard stop (170 min after creation) or on any signal
#   vast.sh key                   throwaway ed25519 key, attached to this instance only (the matching
#                                 account key is passphrase-protected, so unusable non-interactively)
#   vast.sh ssh CMD...            run CMD on the instance with that key
#   vast.sh down                  stop the watchdog (its trap destroys the instance), then list instances
set -euo pipefail
S=${TMPDIR:-/tmp}/orchapod-spike4
mkdir -p "$S"
IMAGE=pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel
case $1 in
up)
  vastai create instance "$2" --image "$IMAGE" --disk "$3" --ssh --direct --cancel-unavail \
    --label orchapod-spike4 --raw > "$S/create.json"
  ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["new_contract"])' "$S/create.json")
  echo "$ID" > "$S/id"
  DEADLINE=$(( $(date +%s) + 170 * 60 ))
  echo "$DEADLINE" > "$S/deadline"
  # Wall-clock loop (not one long sleep) so a Mac sleep/wake still honours the deadline.
  nohup bash -c "trap 'vastai destroy instance $ID -y >> $S/watchdog.log 2>&1' EXIT; trap 'exit 0' INT TERM HUP
    while [ \$(date +%s) -lt $DEADLINE ]; do sleep 15 & wait \$!; done" > /dev/null 2>&1 &
  echo $! > "$S/watchdog.pid"
  echo "instance $ID; watchdog pid $(cat "$S/watchdog.pid"); hard stop $(date -r "$DEADLINE")" ;;
key)
  [ -f "$S/key" ] || ssh-keygen -q -t ed25519 -N "" -C orchapod-spike4 -f "$S/key"
  vastai attach ssh "$(cat "$S/id")" "$(cat "$S/key.pub")" ;;
ssh)
  shift
  URL=$(vastai ssh-url "$(cat "$S/id")" < /dev/null)  # ssh://root@HOST:PORT; keep stdin for ssh
  HP=${URL#ssh://root@}
  ssh -i "$S/key" -o IdentitiesOnly=yes -p "${HP##*:}" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 \
    -o ServerAliveInterval=30 "root@${HP%:*}" "$@" ;;
down)
  kill "$(cat "$S/watchdog.pid")" 2>/dev/null || vastai destroy instance "$(cat "$S/id")" -y
  sleep 10
  vastai show instances --raw | python3 -c \
    'import json,sys; print([(i["id"], i.get("label"), i["actual_status"]) for i in json.load(sys.stdin)])' ;;
esac
