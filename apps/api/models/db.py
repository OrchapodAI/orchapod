"""
apps/api/models/db.py

SQLModel database models (PostgreSQL 16).
Tables: Workflow, Run, NodeRun, Artifact
"""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional
from sqlmodel import SQLModel, Field, Column, JSON, UniqueConstraint


def utcnow() -> datetime:
    """Naive UTC, as the columns store it (datetime.utcnow() is deprecated)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RunStatus(str, Enum):
    PENDING           = "pending"
    PROVISIONING_GPU  = "provisioning_gpu"
    RUNNING           = "running"
    SUCCEEDED         = "succeeded"
    FAILED            = "failed"
    CANCELLED         = "cancelled"


class NodeStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCEEDED = "succeeded"
    FAILED    = "failed"


class ArtifactKind(str, Enum):
    DATASET  = "dataset"
    MODEL    = "model"
    METRICS  = "metrics"
    LOG      = "log"
    ENDPOINT = "endpoint"


class ModelFormat(str, Enum):
    HF   = "hf"     # full HuggingFace safetensors/pytorch format
    AWQ  = "awq"    # AutoAWQ quantized
    GGUF = "gguf"   # llama.cpp GGUF


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class Workflow(SQLModel, table=True):
    """A saved YAML graph (versioned). YAML is source of truth."""
    id:         uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id:    uuid.UUID
    name:       str
    yaml:       str                          # source of truth — YAML string
    graph_json: dict = Field(sa_column=Column(JSON))  # compiled DAG for canvas render
    version:    int   = Field(default=1)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Run(SQLModel, table=True):
    """One execution of a workflow."""
    id:           uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    workflow_id:  Optional[uuid.UUID] = Field(default=None, foreign_key="workflow.id")
    user_id:      uuid.UUID
    status:       RunStatus = Field(default=RunStatus.PENDING)
    inputs:       dict = Field(default={}, sa_column=Column(JSON))  # user params at runtime
    cost_usd:     Optional[Decimal] = None
    started_at:   Optional[datetime] = None
    finished_at:  Optional[datetime] = None
    gpu_provider: Optional[str] = None      # which provider was picked
    gpu_pod_id:   Optional[str] = None
    created_at:   datetime = Field(default_factory=utcnow)

    # Run state machine:
    # pending → provisioning_gpu → running → (succeeded | failed | cancelled)
    # A failed node fails the entire run (MVP). V1 adds retry policies.


class NodeRun(SQLModel, table=True):
    """One node execution within a run; retry reuses the row."""
    __table_args__ = (UniqueConstraint("run_id", "node_id"),)  # refs and /internal/artifact assume one row
    id:          uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    run_id:      uuid.UUID = Field(foreign_key="run.id")
    node_id:     str                        # from YAML, e.g. "fine_tune_1"
    node_type:   str                        # "unsloth-train", "quantize", etc.
    status:      NodeStatus = Field(default=NodeStatus.PENDING)
    started_at:  Optional[datetime] = None
    finished_at: Optional[datetime] = None
    inputs:      dict = Field(default={}, sa_column=Column(JSON))   # resolved URIs
    outputs:     dict = Field(default={}, sa_column=Column(JSON))   # artifact URIs
    logs_uri:    Optional[str] = None       # R2 path to full log file
    error:       Optional[str] = None
    gpu_pod_id:  Optional[str] = None
    gpu_provider: Optional[str] = None

    # per-node state: pending → running → (succeeded | failed)


class Artifact(SQLModel, table=True):
    """Any output produced by a node — stored in R2, metadata here."""
    id:          uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    node_run_id: uuid.UUID = Field(foreign_key="noderun.id")
    name:        str                        # "lora_weights", "gguf_q4_k_m", etc.
    kind:        ArtifactKind
    uri:         str                        # r2://orchapod-artifacts/runs/...
    size_bytes:  Optional[int] = None
    meta:        dict = Field(default={}, sa_column=Column(JSON))
    created_at:  datetime = Field(default_factory=utcnow)


class Spend(SQLModel, table=True):
    """Control-plane spend (planner, reporter, /compare): the per-UTC-day ledger the day cap counts (R6)."""
    id:         Optional[int] = Field(default=None, primary_key=True)
    source:     str                          # planner | reporter | compare
    usd:        Decimal
    created_at: datetime = Field(default_factory=utcnow)


class Model(SQLModel, table=True):
    """
    Canonical model record — the searchable, shareable unit of a trained/quantized model.
    Auto-populated when a node uploads a model artifact via /internal/artifact.
    Weights live in R2; this table stores metadata + lineage.
    """
    id:              uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id:         uuid.UUID
    name:            str                         # e.g. "qwen3-4b-dolly-q4"
    description:     Optional[str] = None
    base_model:      str                         # HF model ID it derives from
    format:          ModelFormat
    uri:             str                         # R2 URI to weights
    size_bytes:      Optional[int] = None
    tags:            list = Field(default=[], sa_column=Column(JSON))

    # Lineage — denormalised for query speed
    artifact_id:     Optional[uuid.UUID] = Field(default=None, foreign_key="artifact.id")
    node_run_id:     Optional[uuid.UUID] = Field(default=None, foreign_key="noderun.id")
    run_id:          Optional[uuid.UUID] = Field(default=None, foreign_key="run.id")

    created_at:      datetime = Field(default_factory=utcnow)
