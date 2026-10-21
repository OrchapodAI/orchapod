"""
packages/sdk-py/orchapod/io.py

Node I/O SDK — used INSIDE every container.
Handles reading inputs from env vars and uploading outputs to object storage (R2/S3).

Every node's run.py imports from here:
    from orchapod import io, log

The contract (docs/NODE_CONTRACT.md, docs/contracts.md "Node SDK"):
  - Inputs arrive via ORCHAPOD_NODE_INPUTS (JSON-encoded dict)
  - Outputs are written locally then uploaded by this SDK
  - Artifact URIs follow: r2://${ORCHAPOD_R2_BUCKET}/runs/{run_id}/{node_id}/{name}
  - Nodes never read from each other directly — only via r2:// URIs
  - cost_json is written at SIGTERM, when main ends (before its threads are joined) and at exit
"""

from __future__ import annotations
import atexit
import json
import os
import re
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Literal

import boto3  # R2 is S3-compatible

from orchapod import cost, log


ArtifactKind = Literal["dataset", "model", "metrics", "log", "endpoint"]

_NAME = re.compile(r"[a-z][a-z0-9_]*")  # refs split on dots, so names have none


@dataclass
class Inputs:
    """Parsed node inputs. Access values like inputs["model"] or inputs.get("lora_r", 16)."""
    _data: dict

    def __getitem__(self, key: str):
        return self._data[key]

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def keys(self):
        return self._data.keys()


def read_inputs() -> Inputs:
    """
    Read node inputs from the ORCHAPOD_NODE_INPUTS environment variable.
    Called at the top of every node's run.py; it also arms the exit hooks (cost_json, SIGTERM).
    """
    raw = os.environ.get("ORCHAPOD_NODE_INPUTS")
    if not raw:
        raise RuntimeError("ORCHAPOD_NODE_INPUTS not set — are you running inside a pod?")
    _arm()
    return Inputs(_data=json.loads(raw))


def local_path(artifact_name: str) -> Path:
    """
    Return a local path where the node should write an output artifact.
    The SDK uploads from this path when write_output() is called.
    """
    outputs_dir = Path(os.environ.get("ORCHAPOD_NODE_OUTPUTS_DIR") or "/tmp/orchapod_outputs")
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return outputs_dir / artifact_name


def write_output(
    name: str,
    local_path: Path | str,
    kind: ArtifactKind,
    metadata: dict | None = None,
) -> str:
    """
    Upload a local file or directory and register it with the control plane.
    Returns the URI: r2://${ORCHAPOD_R2_BUCKET}/runs/{run_id}/{node_id}/{name}

    The control plane records it in NodeRun.outputs, so `${{ nodes.<id>.outputs.<name> }}` resolves to it.
    The name `logs` is reserved: the SDK writes it at exit.
    """
    if not _NAME.fullmatch(name):
        raise ValueError(f"output name {name!r} must match ^[a-z][a-z0-9_]*$")
    if name == "logs":
        raise ValueError("output name 'logs' is reserved: the SDK writes the node's log lines under it at exit")
    return _write(name, local_path, kind, metadata)


def _write(name: str, local_path: Path | str, kind: ArtifactKind, metadata: dict | None = None) -> str:
    r2_key = f"runs/{os.environ['ORCHAPOD_RUN_ID']}/{os.environ['ORCHAPOD_NODE_ID']}/{name}"
    r2_uri = f"r2://{_bucket()}/{r2_key}"

    _upload_to_r2(local_path=Path(local_path), r2_key=r2_key)
    _notify_control_plane(name=name, uri=r2_uri, kind=kind, metadata=metadata or {})

    return r2_uri


def write_metrics(metrics: dict) -> str:
    """
    Write metrics_json (kind metrics), with `stub` filled in from STUB. The dict also travels
    as metadata when it is <= 16 KB, so the API reads it from the DB; otherwise {"truncated": true}.
    """
    metrics = {"stub": os.environ.get("STUB") == "1", **metrics}
    path = local_path("metrics_json")
    path.write_text(json.dumps(metrics))
    small = path.stat().st_size <= 16 * 1024
    return write_output("metrics_json", path, "metrics", metrics if small else {"truncated": True})


def download_input(uri: str, local_dir: Path | str | None = None) -> Path:
    """
    Download a single artifact to a local path.
    Used when a node receives a model or dataset URI as input.
    """
    local_dir = Path(local_dir or tempfile.mkdtemp())
    local_dir.mkdir(parents=True, exist_ok=True)
    artifact_name = uri.split("/")[-1]
    dest = local_dir / artifact_name
    _download_from_r2(r2_key=_key(uri), dest=dest)
    return dest


def download_directory(uri_prefix: str, local_dir: Path | str) -> Path:
    """
    Download all objects under a key prefix into a local directory.
    Used for directory artifacts (adapters, checkpoints).
    """
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    _download_dir_from_r2(r2_prefix=_key(uri_prefix).rstrip("/"), local_dir=local_dir)
    return local_dir


# ---------------------------------------------------------------------------
# Exit hooks: armed by read_inputs() in the node's main process only, so pytest and
# spawned worker processes (which never call it) do not write cost_json.
# ---------------------------------------------------------------------------

_armed = False
_cost_lock = threading.Lock()
_registered: tuple[dict, dict] | None = None  # (the cost record, its summary as last registered as cost_json)


def _arm() -> None:
    global _armed
    if _armed:
        return
    _armed = True
    # CPython joins worker threads (pool calls still in flight) before atexit, and a SIGKILL 30 s after SIGTERM would
    # lose cost_json with them: so it also goes out when main ends, from threading's hook that runs before the joins.
    # Hooks run newest first, so the pool's own join hook is registered (imported) before this one.
    import concurrent.futures.thread  # noqa: F401
    threading._register_atexit(_flush_cost)
    atexit.register(_at_exit)                   # after every thread: the spend of calls that were in flight, then logs
    signal.signal(signal.SIGTERM, _sigterm)     # cancel/timeout: docker stop sends SIGTERM, kills after 30 s
    sys.excepthook = _excepthook


def _sigterm(signum, frame):
    threading.Thread(target=_flush_cost, daemon=True).start()  # the spend so far, beside the node's cleanup
    raise SystemExit(143)  # unwinds the node's `finally` blocks, which cancel remote jobs


def _excepthook(exc_type, exc, tb) -> None:
    log.error(f"{exc_type.__name__}: {exc}")  # the executor shows the last ERROR line
    sys.__excepthook__(exc_type, exc, tb)


def _flush_cost() -> None:
    """Register what the node spent since its last cost_json: the file holds the whole summary, the metadata
    {"usd": the increase}, which the control plane adds to the run. No new spend, no new cost_json. A fresh cost record
    (cost._items replaced: one process running several nodes, as tests/drills does) starts from nothing."""
    global _registered
    with _cost_lock:
        summary = cost.summary()
        last = _registered[1] if _registered and _registered[0] is cost._items else None
        if summary == last:
            return
        path = local_path("cost_json")
        path.write_text(json.dumps(summary))
        try:
            write_output("cost_json", path, "metrics", {"usd": round(summary["usd"] - (last or {"usd": 0})["usd"], 6)})
            _registered = (cost._items, summary)
        except Exception as e:
            log.error(f"cost_json not registered: {e}")


def _at_exit() -> None:
    """cost_json first (money), then `logs`: the last lines the node logged (log.lines), as JSONL {ts, level, message}."""
    _flush_cost()
    path = local_path("logs")
    path.write_text("".join(json.dumps(line) + "\n" for line in list(log.lines)))  # a copy: another thread may still log
    try:
        _write("logs", path, "log")
    except Exception as e:
        log.warn(f"logs not registered: {e}")  # not ERROR: the node's last ERROR line is its error


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bucket() -> str:
    return os.environ.get("ORCHAPOD_R2_BUCKET") or "orchapod-artifacts"


def _key(uri: str) -> str:
    """r2://<bucket>/<key> → <key>."""
    return uri.split("/", 3)[3] if uri.startswith("r2://") else uri


def _get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("ORCHAPOD_R2_ENDPOINT") or "http://localhost:9000",
        aws_access_key_id=os.environ.get("ORCHAPOD_R2_ACCESS_KEY") or "orchapod",
        aws_secret_access_key=os.environ.get("ORCHAPOD_R2_SECRET_KEY") or "orchapod_dev",
        region_name=os.environ.get("ORCHAPOD_R2_REGION") or "auto",
    )


def _upload_to_r2(local_path: Path, r2_key: str) -> None:
    client = _get_r2_client()
    if local_path.is_dir():
        for f in local_path.rglob("*"):
            if f.is_file():
                rel = f.relative_to(local_path)
                _upload_file(client, f, f"{r2_key}/{rel}")
    else:
        _upload_file(client, local_path, r2_key)


def _upload_file(client, path: Path, key: str) -> None:
    # upload_file's thread pool is refused at interpreter exit, where cost_json is written; a file
    # below the 8 MiB multipart threshold goes up as one plain PUT instead.
    if path.stat().st_size < 8 * 1024 * 1024:
        with path.open("rb") as f:
            client.put_object(Bucket=_bucket(), Key=key, Body=f)
    else:
        client.upload_file(str(path), _bucket(), key)


def _download_from_r2(r2_key: str, dest: Path) -> None:
    _get_r2_client().download_file(_bucket(), r2_key, str(dest))


def _download_dir_from_r2(r2_prefix: str, local_dir: Path) -> None:
    client = _get_r2_client()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=_bucket(), Prefix=r2_prefix + "/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(r2_prefix):].lstrip("/")
            if not rel:
                continue
            dest = local_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(_bucket(), key, str(dest))


def _notify_control_plane(name: str, uri: str, kind: str, metadata: dict) -> None:
    """Register the output; retries 3 times (after 1, 2 and 4 s), then raises."""
    payload = {"artifact": {"name": name, "uri": uri, "kind": kind, "metadata": metadata}}
    for delay in (1, 2, 4):
        try:
            return log.post("/internal/artifact", payload, timeout=10)
        except Exception:
            time.sleep(delay)
    log.post("/internal/artifact", payload, timeout=10)
