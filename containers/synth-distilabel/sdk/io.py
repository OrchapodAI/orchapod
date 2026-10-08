"""
packages/sdk-py/orchapod/io.py

Node I/O SDK — used INSIDE every container.
Handles reading inputs from env vars and uploading outputs to Cloudflare R2.

Every node's run.py imports from here:
    from orchapod import io, log

The contract (from NODE_CONTRACT.md):
  - Inputs arrive via ORCHAPOD_NODE_INPUTS (JSON-encoded dict)
  - Outputs are written locally then uploaded to R2 by this SDK
  - Artifact URIs follow: runs/{run_id}/{node_id}/{artifact_name}
  - Nodes never read from each other directly — only via R2 URIs
"""

from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import Literal

import boto3  # R2 is S3-compatible


ArtifactKind = Literal["dataset", "model", "metrics", "log", "endpoint"]


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
    Called at the top of every node's run.py.
    """
    raw = os.environ.get("ORCHAPOD_NODE_INPUTS")
    if not raw:
        raise RuntimeError("ORCHAPOD_NODE_INPUTS not set — are you running inside a pod?")
    return Inputs(_data=json.loads(raw))


def local_path(artifact_name: str) -> Path:
    """
    Return a local path where the node should write an output artifact.
    The SDK uploads from this path to R2 when write_output() is called.
    """
    outputs_dir = Path(os.environ.get("ORCHAPOD_NODE_OUTPUTS_DIR", "/tmp/orchapod_outputs"))
    outputs_dir.mkdir(parents=True, exist_ok=True)
    return outputs_dir / artifact_name


def write_output(
    name: str,
    local_path: Path | str,
    kind: ArtifactKind,
    metadata: dict | None = None,
) -> str:
    """
    Upload a local file or directory to R2 and register it with the control plane.
    Returns the R2 URI: r2://orchapod-artifacts/runs/{run_id}/{node_id}/{name}

    The control plane picks up this output via the webhook and updates NodeRun.outputs.
    """
    run_id   = os.environ["ORCHAPOD_RUN_ID"]
    node_id  = os.environ["ORCHAPOD_NODE_ID"]
    r2_key   = f"runs/{run_id}/{node_id}/{name}"
    r2_uri   = f"r2://orchapod-artifacts/{r2_key}"

    _upload_to_r2(local_path=Path(local_path), r2_key=r2_key)
    _notify_control_plane(name=name, uri=r2_uri, kind=kind, metadata=metadata or {})

    return r2_uri


def download_input(uri: str, local_dir: Path | str | None = None) -> Path:
    """
    Download a single artifact from R2 to a local path.
    Used when a node receives a model or dataset URI as input.
    """
    local_dir = Path(local_dir or tempfile.mkdtemp())
    local_dir.mkdir(parents=True, exist_ok=True)
    artifact_name = uri.split("/")[-1]
    dest = local_dir / artifact_name
    r2_key = uri.replace("r2://orchapod-artifacts/", "")
    _download_from_r2(r2_key=r2_key, dest=dest)
    return dest


def download_directory(uri_prefix: str, local_dir: Path | str) -> Path:
    """
    Download all R2 objects under a key prefix into a local directory.
    Used for checkpoint resume — the checkpoint is a directory, not a single file.
    """
    local_dir = Path(local_dir)
    local_dir.mkdir(parents=True, exist_ok=True)
    r2_prefix = uri_prefix.replace("r2://orchapod-artifacts/", "").rstrip("/")
    _download_dir_from_r2(r2_prefix=r2_prefix, local_dir=local_dir)
    return local_dir


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["ORCHAPOD_R2_ENDPOINT"],
        aws_access_key_id=os.environ["ORCHAPOD_R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["ORCHAPOD_R2_SECRET_KEY"],
        region_name="auto",
    )


def _upload_to_r2(local_path: Path, r2_key: str) -> None:
    client = _get_r2_client()
    bucket = os.environ.get("ORCHAPOD_R2_BUCKET", "orchapod-artifacts")
    if local_path.is_dir():
        for f in local_path.rglob("*"):
            if f.is_file():
                rel = f.relative_to(local_path)
                client.upload_file(str(f), bucket, f"{r2_key}/{rel}")
    else:
        client.upload_file(str(local_path), bucket, r2_key)


def _download_from_r2(r2_key: str, dest: Path) -> None:
    client = _get_r2_client()
    bucket = os.environ.get("ORCHAPOD_R2_BUCKET", "orchapod-artifacts")
    client.download_file(bucket, r2_key, str(dest))


def _download_dir_from_r2(r2_prefix: str, local_dir: Path) -> None:
    client = _get_r2_client()
    bucket = os.environ.get("ORCHAPOD_R2_BUCKET", "orchapod-artifacts")
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=r2_prefix + "/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            rel = key[len(r2_prefix):].lstrip("/")
            if not rel:
                continue
            dest = local_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(bucket, key, str(dest))


def _notify_control_plane(name: str, uri: str, kind: str, metadata: dict) -> None:
    import urllib.request
    control_url = os.environ.get("ORCHAPOD_CONTROL_URL")
    if not control_url:
        return
    run_id  = os.environ["ORCHAPOD_RUN_ID"]
    node_id = os.environ["ORCHAPOD_NODE_ID"]
    payload = json.dumps({
        "run_id": run_id,
        "node_id": node_id,
        "artifact": {"name": name, "uri": uri, "kind": kind, "metadata": metadata},
    }).encode()
    req = urllib.request.Request(
        f"{control_url}/internal/artifact",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)
