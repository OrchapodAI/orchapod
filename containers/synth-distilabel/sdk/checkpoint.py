"""
packages/sdk-py/orchapod/checkpoint.py

Checkpoint helpers for training nodes.
Aggressively saves every N steps to R2 so a pod failure is resumable.

Risk mitigation (from MVP plan):
  "RunPod pod fails mid-training" — HIGH probability
  Mitigation: checkpoint every 100 steps to R2; resume-from-checkpoint flag in unsloth-train
"""

from __future__ import annotations
import os
from pathlib import Path
from . import io, log


CHECKPOINT_EVERY_N_STEPS = int(os.environ.get("ORCHAPOD_CHECKPOINT_STEPS", "100"))


def save_checkpoint(step: int, model_dir: Path) -> str:
    """
    Save a training checkpoint to R2.
    Returns the R2 URI of the checkpoint.
    Called from inside the training loop every N steps.
    """
    log.info(f"Saving checkpoint at step {step}")
    uri = io.write_output(
        name=f"checkpoint_step_{step:06d}",
        local_path=model_dir,
        kind="model",
        metadata={"step": step, "type": "checkpoint"},
    )
    log.info(f"Checkpoint saved: {uri}")
    return uri


def download_checkpoint(checkpoint_uri: str, local_dir: str | Path) -> Path:
    """
    Download a checkpoint directory from R2 to a local path.
    Used at startup when ORCHAPOD_RESUME_CHECKPOINT_URI is set.
    Returns the local path so run.py can pass it to trainer.train().
    """
    log.info(f"Downloading checkpoint from R2: {checkpoint_uri}")
    return io.download_directory(checkpoint_uri, local_dir)


def latest_checkpoint_uri() -> str | None:
    """
    Check if a previous checkpoint exists for this run (for resume-from-checkpoint).
    Returns the R2 URI of the latest checkpoint, or None if starting fresh.

    The control plane injects ORCHAPOD_RESUME_CHECKPOINT_URI if resuming.
    """
    return os.environ.get("ORCHAPOD_RESUME_CHECKPOINT_URI")


def should_checkpoint(step: int) -> bool:
    return step > 0 and step % CHECKPOINT_EVERY_N_STEPS == 0
