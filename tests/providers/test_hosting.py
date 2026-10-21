"""The hosting scripts (docs/HOSTING.md) against recording fakes of rsync, ssh, sudo and docker: nothing remote, no daemon."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# One fake for every command: it logs its argv, one arg per line after a "--- <name>" line, then acts per FAKE_* env.
FAKE = """#!/bin/sh
{ echo "--- $(basename "$0")"; printf '%s\\n' "$@"; } >> "$FAKE_LOG"
case "$(basename "$0") $1" in
  "docker ps") case "$*" in *health=unhealthy*) echo "$FAKE_UNHEALTHY" ;; *service=postgres*) echo pg1 ;; *) echo api1 ;; esac ;;
  "docker exec") case "$*" in *pg_dump*) [ -z "$FAKE_PG_FAIL" ] && printf DUMP || exit 1 ;;
                              *upload_fileobj*) cat > "$FAKE_LOG.uploaded" ;; esac ;;
  "docker image") [ "$3" = "$FAKE_PRESENT" ] ;;
esac
"""
ONEOFF = "label=com.docker.compose.oneoff=False"  # never a one-off `dc run api`


def run(tmp_path, argv, **env):
    for name in ("docker", "rsync", "ssh"):
        (tmp_path / name).write_text(FAKE)
        (tmp_path / name).chmod(0o755)
    log = tmp_path / "log"
    env = {"PATH": f"{tmp_path}:{os.environ['PATH']}", "FAKE_LOG": str(log), "FAKE_UNHEALTHY": "", "FAKE_PG_FAIL": "",
           "FAKE_PRESENT": "", "HOME": os.environ.get("HOME", "/tmp")} | env
    done = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    calls = [c.splitlines() for c in log.read_text().split("--- ")[1:]] if log.exists() else []
    return done, calls, log


def test_deploy_never_ships_or_deletes_the_vms_secrets_and_refreshes_node_images(tmp_path):
    done, calls, _ = run(tmp_path, ["scripts/deploy-hosted.sh"])
    assert done.returncode != 0 and calls == []  # no ORCHAPOD_DEPLOY_HOST: nothing runs

    done, calls, log = run(tmp_path, ["scripts/deploy-hosted.sh"], ORCHAPOD_DEPLOY_HOST="hari@vm")
    assert done.returncode == 0, done.stderr
    (rsync, *rsync_args), (ssh, host, command) = calls
    # without these excludes, rsync --delete removes the VM's .env and nebius/ (the .gitignore filter alone does not keep them)
    assert {"--delete", "--exclude=/.env", "--exclude=/nebius/", "--exclude=/deploys.log", "--filter=:- .gitignore"} <= set(rsync_args)
    assert (rsync, rsync_args[-1], ssh, host) == ("rsync", "hari@vm:/opt/orchapod/", "ssh", "hari@vm")

    # The VM's half, run here in a fake /opt/orchapod: sudo passes through; the VM has data-prep's image, not unsloth-train's.
    vm = tmp_path / "vm"
    for node in ("data-prep", "unsloth-train"):
        (vm / "containers" / node).mkdir(parents=True)
    (vm / ".env").write_text("DOMAIN=x\nORCHAPOD_IMAGE_PREFIX=ghcr.io/acme\n")
    (tmp_path / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (tmp_path / "sudo").chmod(0o755)
    log.unlink()
    done, calls, _ = run(tmp_path, ["bash", "-c", command.replace("cd /opt/orchapod", f"cd {vm}")],
                         FAKE_PRESENT="ghcr.io/acme/data-prep:latest")
    assert done.returncode == 0, done.stderr
    assert calls[0][:2] == ["docker", "compose"] and "up" in calls[0] and "--build" in calls[0]
    assert [c for c in calls if c[1] == "pull"] == [["docker", "pull", "-q", "ghcr.io/acme/data-prep:latest"]]
    assert (vm / "deploys.log").read_text().split()[1].startswith(subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip())


def test_backup_uploads_the_dump_to_todays_slot_and_never_a_failed_one(tmp_path):
    done, calls, log = run(tmp_path, ["scripts/backup-db.sh"])
    assert done.returncode == 0, done.stderr
    slot = f"backups/pg/orchapod-{int(time.time()) // 86400 % 14:02d}.dump"
    assert [c for c in calls if "pg_dump" in c] and [c for c in calls if c[-1] == slot]
    assert all(ONEOFF in c for c in calls if c[1] == "ps")
    assert Path(f"{log}.uploaded").read_text() == "DUMP"

    Path(f"{log}.uploaded").unlink()
    done, calls, log = run(tmp_path, ["scripts/backup-db.sh"], FAKE_PG_FAIL="1")
    assert done.returncode != 0 and not Path(f"{log}.uploaded").exists()


def test_watchdog_restarts_only_an_unhealthy_api_of_this_project(tmp_path):
    done, calls, _ = run(tmp_path, ["scripts/watchdog.sh"])
    assert done.returncode == 0 and [c[1] for c in calls] == ["ps"]  # healthy: nothing restarted

    done, calls, _ = run(tmp_path, ["scripts/watchdog.sh"], FAKE_UNHEALTHY="c0ffee")
    ps, restart = calls[-2:]
    assert {"label=com.docker.compose.project=orchapod", "label=com.docker.compose.service=api", ONEOFF,
            "health=unhealthy"} <= set(ps)
    assert restart == ["docker", "restart", "c0ffee"]
