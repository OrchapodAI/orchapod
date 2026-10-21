"""
packages/sdk-py/orchapod/log.py

Structured logging for node containers: stdout plus the control plane's /internal webhooks.
"""

from __future__ import annotations
import json
import os
import urllib.request
from collections import deque
from datetime import datetime, timezone


def post(path: str, payload: dict, timeout: float = 3) -> None:
    """POST payload (+ run_id, node_id) to the control plane with X-Orchapod-Secret.
    Raises on failure; a no-op without ORCHAPOD_CONTROL_URL (local runs)."""
    control_url = os.environ.get("ORCHAPOD_CONTROL_URL")
    if not control_url:
        return
    body = {"run_id": os.environ.get("ORCHAPOD_RUN_ID", "local"),
            "node_id": os.environ.get("ORCHAPOD_NODE_ID", "local"), **payload}
    req = urllib.request.Request(
        f"{control_url}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "X-Orchapod-Secret": os.environ.get("ORCHAPOD_INTERNAL_SECRET", "")},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout):
        pass


# The last lines this node logged; io writes them as the `logs` artifact at exit, so a finished run keeps its logs.
# Bounded: an hour of progress lines stays a small file.
lines: deque[dict] = deque(maxlen=5000)


def _emit(level: str, message: str, path: str = "/internal/log", payload: dict | None = None) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    print(f"[{ts}] [{level}] {message}", flush=True)
    lines.append({"ts": ts, "level": level, "message": message})
    try:
        post(path, payload or {"ts": ts, "level": level, "message": message})
    except Exception:
        pass  # Never let logging crash the training run


def info(message: str)  -> None: _emit("INFO", message)
def warn(message: str)  -> None: _emit("WARN", message)
def error(message: str) -> None: _emit("ERROR", message)


def progress(step: int, total: int, loss: float | None = None, extra: dict | None = None) -> None:
    """POST /internal/progress → a `progress` event (live loss chart, remote phase). Never raises."""
    msg = f"step={step}/{total}"
    if loss is not None:
        msg += f" loss={loss:.4f}"
    if extra:
        msg += " " + " ".join(f"{k}={v}" for k, v in extra.items())
    _emit("PROGRESS", msg, "/internal/progress", {"step": step, "total": total, "loss": loss, "extra": extra or {}})
