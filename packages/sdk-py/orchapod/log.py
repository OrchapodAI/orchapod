"""
packages/sdk-py/orchapod/log.py

Structured logging for node containers.
Streams log lines to the control plane via webhook → SSE → frontend run viewer.
"""

from __future__ import annotations
import json
import os
import urllib.request
from datetime import datetime, timezone


_control_url = os.environ.get("ORCHAPOD_CONTROL_URL")
_run_id      = os.environ.get("ORCHAPOD_RUN_ID", "local")
_node_id     = os.environ.get("ORCHAPOD_NODE_ID", "local")


def _emit(level: str, message: str) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    line = f"[{ts}] [{level}] {message}"
    print(line, flush=True)

    if _control_url:
        try:
            payload = json.dumps({
                "run_id": _run_id,
                "node_id": _node_id,
                "ts": ts,
                "level": level,
                "message": message,
            }).encode()
            req = urllib.request.Request(
                f"{_control_url}/internal/log",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass  # Never let logging crash the training run


def info(message: str)  -> None: _emit("INFO", message)
def warn(message: str)  -> None: _emit("WARN", message)
def error(message: str) -> None: _emit("ERROR", message)


def progress(step: int, total: int, loss: float | None = None, extra: dict | None = None) -> None:
    """Emit a structured training progress event (parsed by run viewer for charts)."""
    msg = f"step={step}/{total}"
    if loss is not None:
        msg += f" loss={loss:.4f}"
    if extra:
        msg += " " + " ".join(f"{k}={v}" for k, v in extra.items())
    _emit("PROGRESS", msg)
