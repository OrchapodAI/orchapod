"""
Shared fixtures for container tests.

Container run.py files live at containers/<name>/run.py and all import
`from orchapod import io, log`. Loading them via importlib lets us give each
a unique module name so both can coexist in the same pytest session.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_CONTAINERS = Path(__file__).parents[2] / "containers"


def _load_container(name: str):
    """Load containers/<name>/run.py as a uniquely-named module."""
    module_name = f"container_{name.replace('-', '_')}_run"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(
        module_name, _CONTAINERS / name / "run.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def quantize_mod():
    return _load_container("quantize")


@pytest.fixture(scope="session")
def vllm_serve_mod():
    return _load_container("vllm-serve")


@pytest.fixture(autouse=True)
def mock_orchapod_io(monkeypatch):
    """
    Replace orchapod.io with a MagicMock for every container test so nothing
    tries to read env vars or talk to R2.
    """
    mock_io = MagicMock()
    mock_io.local_path.side_effect = lambda name: Path(f"/tmp/{name}")
    monkeypatch.setattr("orchapod.io", mock_io)
    return mock_io
