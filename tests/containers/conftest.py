"""
tests/containers/conftest.py

Shared fixtures for container unit tests.

Both quantize/run.py and vllm-serve/run.py are named run.py.
We load them with importlib using unique module names to avoid collisions.
"""

from __future__ import annotations

import importlib.util
import itertools
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


@pytest.fixture
def files(mock_orchapod_io) -> dict:
    """{uri: local path} that io.download_input serves; tests chain nodes by adding an output under a URI."""
    served: dict = {}
    mock_orchapod_io.download_input.side_effect = lambda uri, *_: served[uri]
    return served


@pytest.fixture
def run_main(mock_orchapod_io, tmp_path):
    """run_main(module, **inputs) -> ({output name: local path}, metrics): one main() run in a fresh output dir."""
    runs = itertools.count()

    def run(module, **inputs):
        out = tmp_path / f"run{next(runs)}"
        out.mkdir()
        mock_orchapod_io.local_path.side_effect = lambda name: out / name
        mock_orchapod_io.write_output.reset_mock()
        mock_orchapod_io.write_metrics.reset_mock()
        mock_orchapod_io.read_inputs.return_value = inputs
        module.main()
        (metrics,), _ = mock_orchapod_io.write_metrics.call_args
        return {c.args[0]: c.args[1] for c in mock_orchapod_io.write_output.call_args_list}, metrics

    return run
