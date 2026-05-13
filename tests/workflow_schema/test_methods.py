from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from pydantic import ValidationError

from packages.workflow_schema.methods import (
    TrainingMethod,
    TRAINING_METHOD_REGISTRY,
    list_methods,
    get_method,
)


# ── Registry completeness ──────────────────────────────────────────────────────

MVP_IDS = ["unsloth-lora-sft", "unsloth-distill-sft", "quant-gguf", "quant-awq"]


def test_all_mvp_method_ids_present():
    for mid in MVP_IDS:
        assert mid in TRAINING_METHOD_REGISTRY, f"Missing method: {mid}"


@pytest.mark.parametrize("method_id", MVP_IDS)
def test_each_method_has_nonempty_required_string_fields(method_id):
    m = TRAINING_METHOD_REGISTRY[method_id]
    assert m.container, f"{method_id}: container is empty"
    assert m.framework, f"{method_id}: framework is empty"
    assert m.display_name, f"{method_id}: display_name is empty"
    assert m.description, f"{method_id}: description is empty"


@pytest.mark.parametrize("method_id", ["unsloth-lora-sft", "unsloth-distill-sft"])
def test_unsloth_methods_have_gpu_runtime(method_id):
    assert TRAINING_METHOD_REGISTRY[method_id].runtime == "gpu"


def test_quant_gguf_has_cpu_runtime():
    assert TRAINING_METHOD_REGISTRY["quant-gguf"].runtime == "cpu"


def test_unsloth_lora_sft_default_hyperparams():
    hp = TRAINING_METHOD_REGISTRY["unsloth-lora-sft"].default_hyperparams
    for key in ("lora_r", "lora_alpha", "learning_rate"):
        assert key in hp, f"Missing hyperparam: {key}"


def test_unsloth_lora_sft_has_at_least_5_supported_models():
    models = TRAINING_METHOD_REGISTRY["unsloth-lora-sft"].supported_models
    assert len(models) >= 5


@pytest.mark.parametrize("method_id", ["quant-gguf", "quant-awq"])
def test_quant_methods_support_wildcard(method_id):
    assert TRAINING_METHOD_REGISTRY[method_id].supported_models == ["*"]


# ── Pydantic validation ────────────────────────────────────────────────────────

def test_training_method_rejects_missing_method_id():
    with pytest.raises(ValidationError):
        TrainingMethod(display_name="X", framework="f", container="c")


def test_training_method_rejects_missing_display_name():
    with pytest.raises(ValidationError):
        TrainingMethod(method_id="x", framework="f", container="c")


def test_training_method_rejects_missing_framework():
    with pytest.raises(ValidationError):
        TrainingMethod(method_id="x", display_name="X", container="c")


def test_training_method_rejects_missing_container():
    with pytest.raises(ValidationError):
        TrainingMethod(method_id="x", display_name="X", framework="f")


def test_training_method_accepts_valid_input():
    m = TrainingMethod(
        method_id="test-method",
        display_name="Test Method",
        framework="pytorch",
        container="ghcr.io/test/image:latest",
    )
    assert m.method_id == "test-method"


def test_model_dump_returns_correct_keys():
    m = TrainingMethod(
        method_id="test-method",
        display_name="Test Method",
        framework="pytorch",
        container="ghcr.io/test/image:latest",
    )
    data = m.model_dump()
    expected_keys = {
        "method_id", "display_name", "framework", "container",
        "description", "runtime", "default_hyperparams", "supported_models",
    }
    assert set(data.keys()) == expected_keys


# ── Helper functions ───────────────────────────────────────────────────────────

def test_list_methods_returns_exactly_4():
    assert len(list_methods()) == 4


def test_list_methods_returns_list():
    result = list_methods()
    assert isinstance(result, list)
    assert all(isinstance(m, TrainingMethod) for m in result)


def test_get_method_returns_correct_method():
    m = get_method("unsloth-lora-sft")
    assert m is not None
    assert m.method_id == "unsloth-lora-sft"
    assert m.framework == "unsloth"


def test_get_method_returns_none_for_nonexistent():
    assert get_method("nonexistent") is None


# ── Extensibility ─────────────────────────────────────────────────────────────

def test_fifth_method_can_be_added_and_removed():
    dummy = TrainingMethod(
        method_id="dummy-method",
        display_name="Dummy Method",
        framework="dummy",
        container="ghcr.io/test/dummy:latest",
    )
    assert "dummy-method" not in TRAINING_METHOD_REGISTRY

    TRAINING_METHOD_REGISTRY["dummy-method"] = dummy
    try:
        methods = list_methods()
        assert len(methods) == 5
        assert any(m.method_id == "dummy-method" for m in methods)
    finally:
        del TRAINING_METHOD_REGISTRY["dummy-method"]

    assert "dummy-method" not in TRAINING_METHOD_REGISTRY
    assert len(list_methods()) == 4


# ── API endpoint tests ─────────────────────────────────────────────────────────

from fastapi.testclient import TestClient
from fastapi import FastAPI
from apps.api.routes.models import router

_app = FastAPI()
_app.include_router(router, prefix="/registry")
client = TestClient(_app)


def test_list_methods_endpoint_returns_200():
    response = client.get("/registry/methods")
    assert response.status_code == 200


def test_list_methods_endpoint_has_methods_key():
    response = client.get("/registry/methods")
    data = response.json()
    assert "methods" in data


def test_list_methods_endpoint_returns_4_items():
    response = client.get("/registry/methods")
    data = response.json()
    assert len(data["methods"]) == 4


def test_list_methods_items_have_required_fields():
    response = client.get("/registry/methods")
    data = response.json()
    for item in data["methods"]:
        assert "method_id" in item, f"Missing method_id in {item}"
        assert "framework" in item, f"Missing framework in {item}"
        assert "container" in item, f"Missing container in {item}"


def test_get_method_endpoint_returns_200():
    response = client.get("/registry/methods/unsloth-lora-sft")
    assert response.status_code == 200


def test_get_method_endpoint_returns_correct_method():
    response = client.get("/registry/methods/unsloth-lora-sft")
    data = response.json()
    assert data["method_id"] == "unsloth-lora-sft"


def test_get_method_endpoint_returns_404_for_nonexistent():
    response = client.get("/registry/methods/nonexistent-method")
    assert response.status_code == 404
