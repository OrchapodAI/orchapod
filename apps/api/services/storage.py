"""
apps/api/services/storage.py

Control-plane side R2/MinIO helpers.
Used by the API to generate presigned upload/download URLs for the frontend
and to list artifacts for a run.

Note: The actual file I/O inside containers is handled by packages/sdk-py/orchapod/io.py.
This module is for the API to interact with R2 on behalf of the user.
"""

from __future__ import annotations

import os

import boto3
from botocore.config import Config


def _get_client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("ORCHAPOD_R2_ENDPOINT") or "http://localhost:9000",
        aws_access_key_id=os.environ.get("ORCHAPOD_R2_ACCESS_KEY") or "orchapod",
        aws_secret_access_key=os.environ.get("ORCHAPOD_R2_SECRET_KEY") or "orchapod_dev",
        region_name=os.environ.get("ORCHAPOD_R2_REGION") or "auto",
        config=Config(signature_version="s3v4"),
    )


def _bucket() -> str:
    return os.environ.get("ORCHAPOD_R2_BUCKET") or "orchapod-artifacts"


def presigned_upload_url(key: str, content_type: str = "application/octet-stream", expires: int = 3600) -> str:
    """Generate a presigned PUT URL so the frontend can upload a dataset directly to R2."""
    client = _get_client()
    return client.generate_presigned_url(
        "put_object",
        Params={"Bucket": _bucket(), "Key": key, "ContentType": content_type},
        ExpiresIn=expires,
        HttpMethod="PUT",
    )


def presigned_download_url(key: str, expires: int = 3600) -> str:
    """Generate a presigned GET URL so the frontend can download an artifact."""
    client = _get_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": key},
        ExpiresIn=expires,
    )


def r2_uri_to_key(uri: str) -> str:
    """Convert r2://orchapod-artifacts/runs/... → runs/..."""
    return uri.replace(f"r2://{_bucket()}/", "")


def key_to_r2_uri(key: str) -> str:
    return f"r2://{_bucket()}/{key}"


def artifact_key(run_id: str, node_id: str, name: str) -> str:
    return f"runs/{run_id}/{node_id}/{name}"


def dataset_upload_key(user_id: str, filename: str) -> str:
    """Key for user-uploaded datasets (before they're attached to a run)."""
    return f"uploads/{user_id}/{filename}"


def ensure_bucket_exists() -> None:
    """Create the R2 bucket if it doesn't exist (MinIO dev only)."""
    client = _get_client()
    bucket = _bucket()
    try:
        client.head_bucket(Bucket=bucket)
    except client.exceptions.NoSuchBucket:
        client.create_bucket(Bucket=bucket)
    except Exception:
        # head_bucket raises ClientError for 404 on real S3 — catch generically
        try:
            client.create_bucket(Bucket=bucket)
        except Exception:
            pass
