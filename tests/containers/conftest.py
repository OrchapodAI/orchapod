"""
tests/containers/conftest.py

Shared fixtures for container unit tests.

Both quantize/run.py and vllm-serve/run.py are named run.py.
We load them with importlib using unique module names to avoid collisions.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def load_container(name: str):
    """Load a container's run.py as a module named containers.<name>."""
    module_name = f"containers.{name.replace('-', '_')}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    path = Path(__file__).parent.parent.parent / "containers" / name / "run.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def mock_orchapod_io(monkeypatch):
    """
    Replace orchapod.io with a lightweight mock so container tests
    never touch S3/R2 or read real env vars.
    """
    mock_io = MagicMock()
    mock_io.read_inputs.return_value = {}
    mock_io.local_path.side_effect = lambda name: Path(f"/tmp/orchapod_test/{name}")
    mock_io.download_input.side_effect = lambda uri, dest: Path(dest)
    mock_io.write_output.return_value = None

    mock_log = MagicMock()

    # Patch inside already-loaded container modules and future imports
    monkeypatch.setattr("orchapod.io",  mock_io,  raising=False)
    monkeypatch.setattr("orchapod.log", mock_log, raising=False)

    # Patch inside the containers.<name> module namespace if already loaded
    for mod_name, mod in list(sys.modules.items()):
        if mod_name.startswith("containers."):
            if hasattr(mod, "io"):
                monkeypatch.setattr(mod, "io", mock_io)
            if hasattr(mod, "log"):
                monkeypatch.setattr(mod, "log", mock_log)

    return mock_io
