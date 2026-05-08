"""
apps/api/models/db.py

SQLModel database models (PostgreSQL 16).
Tables: Workflow, Run, NodeRun, Artifact
"""

from __future__ import annotations
import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from sqlmodel import SQLModel, Field, Column, JSON


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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


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
    created_at:   datetime = Field(default_factory=datetime.utcnow)

    # Run state machine:
    # pending → provisioning_gpu → running → (succeeded | failed | cancelled)
    # A failed node fails the entire run (MVP). V1 adds retry policies.


class NodeRun(SQLModel, table=True):
    """One node execution within a run."""
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
    metadata:    dict = Field(default={}, sa_column=Column(JSON))
    created_at:  datetime = Field(default_factory=datetime.utcnow)
