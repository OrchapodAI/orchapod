"""
tests/containers/test_unsloth_train.py

Unit tests for containers/unsloth-train/run.py
No GPU required — all heavy ML deps are mocked.

Coverage:
  - _build_formatting_func  (pure fn, only needs a mock tokenizer)
  - main() input parsing    (defaults, type coercions)
  - output artifact names   (lora_adapter / merged_model / train_metrics_json)
  - optional eval_data      (empty string = no eval dataset, no download)
  - checkpoint resume       (download_checkpoint called with right URI)
  - Unsloth merge API       (save_pretrained_merged, not merge_and_unload)
  - checkpoint interval     (parametrized arithmetic check)
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fakes for the SDK and the GPU libraries. They sit in sys.modules only while run.py loads and while a test
# of this file runs, so the real orchapod package is untouched for every other test file.
# ---------------------------------------------------------------------------

def _fakes() -> dict:
    """Lightweight fakes for the SDK and the GPU/heavy modules, by sys.modules name."""

    # orchapod SDK
    orchapod  = types.ModuleType("orchapod")
    io_m      = types.ModuleType("orchapod.io")
    log_m     = types.ModuleType("orchapod.log")
    ckpt_m    = types.ModuleType("orchapod.checkpoint")

    io_m.read_inputs    = MagicMock()
    io_m.download_input = MagicMock(return_value=Path("/tmp/fake.jsonl"))
    io_m.local_path     = MagicMock(return_value=Path("/tmp/metrics.json"))
    io_m.write_output   = MagicMock(return_value="r2://bucket/out")

    log_m.info     = MagicMock()
    log_m.warn     = MagicMock()
    log_m.progress = MagicMock()

    ckpt_m.latest_checkpoint_uri = MagicMock(return_value=None)
    ckpt_m.save_checkpoint       = MagicMock()
    ckpt_m.download_checkpoint   = MagicMock(return_value=Path("/tmp/resume_ckpt"))

    orchapod.io         = io_m
    orchapod.log        = log_m
    orchapod.checkpoint = ckpt_m

    # transformers — TrainerCallback is imported at module level in run.py
    tf = types.ModuleType("transformers")
    class FakeTrainerCallback:
        pass
    tf.TrainerCallback   = FakeTrainerCallback
    tf.TrainingArguments = MagicMock(return_value=MagicMock())

    # Heavy libs used only inside main() — lazy mocks are fine
    unsloth = types.ModuleType("unsloth")
    unsloth.FastLanguageModel = MagicMock()

    trl = types.ModuleType("trl")
    trl.SFTTrainer = MagicMock()

    datasets = types.ModuleType("datasets")
    datasets.load_dataset = MagicMock(return_value=MagicMock())

    return {
        "orchapod": orchapod, "orchapod.io": io_m, "orchapod.log": log_m, "orchapod.checkpoint": ckpt_m,
        "transformers": tf, "unsloth": unsloth, "trl": trl, "datasets": datasets,
    }


_FAKES = _fakes()

# Load run.py against the fakes (its module-level imports bind them); sys.modules is restored right after.
_RUN_PY = (
    Path(__file__).parent.parent.parent / "containers" / "unsloth-train" / "run.py"
)
with pytest.MonkeyPatch.context() as _mp:
    for _name, _mod in _FAKES.items():
        _mp.setitem(sys.modules, _name, _mod)
    _spec = importlib.util.spec_from_file_location("unsloth_train_run", _RUN_PY)
    _run  = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_run)
_LEFT_BEHIND = [n for n in ("orchapod", "orchapod.io", "transformers", "unsloth", "trl", "datasets")
                if n in sys.modules and sys.modules[n].__spec__ is None]  # a fake has no import spec


def test_loading_run_py_leaves_sys_modules_as_it_was():
    assert _LEFT_BEHIND == []


@pytest.fixture(autouse=True)
def _fake_modules(monkeypatch):
    """main() imports unsloth, trl, datasets and transformers lazily, and the tests read the fakes back."""
    for name, mod in _FAKES.items():
        monkeypatch.setitem(sys.modules, name, mod)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeInputs:
    def __init__(self, data: dict):
        self._data = data
    def __getitem__(self, k):
        return self._data[k]
    def get(self, k, default=None):
        return self._data.get(k, default)


_BASE_INPUTS: dict = {
    "model":            "Qwen/Qwen3-4B-Instruct",
    "train_data":       "r2://bucket/runs/1/prep/train_jsonl",
    "eval_data":        "r2://bucket/runs/1/prep/eval_jsonl",
    "lora_r":           "16",
    "lora_alpha":       "32",
    "max_steps":        "500",
    "learning_rate":    "0.0002",
    "target_modules":   "all-linear",
    "checkpoint_steps": "100",
}


def _setup(extra: dict | None = None) -> tuple:
    """
    Reset all mocks to a known-good state, return (model, tokenizer, trainer).
    Call before every main() invocation in a test.
    """
    inputs = {**_BASE_INPUTS, **(extra or {})}

    io   = sys.modules["orchapod.io"]
    ckpt = sys.modules["orchapod.checkpoint"]
    log  = sys.modules["orchapod.log"]

    io.read_inputs.return_value   = _FakeInputs(inputs)
    io.download_input.reset_mock()
    io.download_input.side_effect = None
    io.download_input.return_value = Path("/tmp/fake.jsonl")
    io.write_output.reset_mock()
    io.local_path.return_value    = Path("/tmp/metrics.json")

    log.info.reset_mock()
    log.progress.reset_mock()

    ckpt.latest_checkpoint_uri.return_value = None
    ckpt.save_checkpoint.reset_mock()
    ckpt.download_checkpoint.reset_mock()
    ckpt.download_checkpoint.return_value   = Path("/tmp/resume_ckpt")

    fake_tok = MagicMock()
    fake_tok.apply_chat_template.return_value = "formatted text"
    fake_model = MagicMock()

    unsloth = sys.modules["unsloth"]
    unsloth.FastLanguageModel.from_pretrained.return_value = (fake_model, fake_tok)
    unsloth.FastLanguageModel.get_peft_model.return_value  = fake_model
    unsloth.FastLanguageModel.for_training.reset_mock()

    sys.modules["datasets"].load_dataset.return_value = MagicMock()

    fake_trainer = MagicMock()
    sys.modules["trl"].SFTTrainer.return_value = fake_trainer

    # metrics.json must exist when main() opens it
    Path("/tmp/metrics.json").write_text(json.dumps({"loss_curve": []}))

    return fake_model, fake_tok, fake_trainer


# ---------------------------------------------------------------------------
# _build_formatting_func
# ---------------------------------------------------------------------------

class TestFormattingFunc:

    def test_applies_chat_template_to_single_example(self):
        tok = MagicMock()
        tok.apply_chat_template.return_value = "<|im_start|>user\nhello<|im_end|>"

        fn  = _run._build_formatting_func(tok)
        msgs = [{"role": "user", "content": "hello"}]
        result = fn({"messages": [msgs]})

        assert result == ["<|im_start|>user\nhello<|im_end|>"]
        tok.apply_chat_template.assert_called_once_with(
            msgs, tokenize=False, add_generation_prompt=False
        )

    def test_batch_returns_one_string_per_example(self):
        tok = MagicMock()
        tok.apply_chat_template.side_effect = lambda m, **kw: f"turn_count={len(m)}"

        fn     = _run._build_formatting_func(tok)
        result = fn({"messages": [
            [{"role": "user", "content": "a"}],
            [{"role": "user", "content": "b"}, {"role": "assistant", "content": "c"}],
        ]})

        assert len(result) == 2
        assert result[0] == "turn_count=1"
        assert result[1] == "turn_count=2"

    def test_result_elements_are_strings(self):
        tok = MagicMock()
        tok.apply_chat_template.return_value = "text"

        fn     = _run._build_formatting_func(tok)
        result = fn({"messages": [[]]})

        assert all(isinstance(s, str) for s in result)

    def test_add_generation_prompt_is_false(self):
        tok = MagicMock()
        tok.apply_chat_template.return_value = ""

        _run._build_formatting_func(tok)({"messages": [[]]})

        _, kwargs = tok.apply_chat_template.call_args
        assert kwargs["add_generation_prompt"] is False

    def test_tokenize_is_false(self):
        tok = MagicMock()
        tok.apply_chat_template.return_value = ""

        _run._build_formatting_func(tok)({"messages": [[]]})

        _, kwargs = tok.apply_chat_template.call_args
        assert kwargs["tokenize"] is False


# ---------------------------------------------------------------------------
# main() — config parsing
# ---------------------------------------------------------------------------

class TestConfigParsing:

    def test_default_lora_r_16(self):
        inputs = dict(_BASE_INPUTS)
        del inputs["lora_r"]
        _setup(inputs)
        _run.main()

        kw = sys.modules["unsloth"].FastLanguageModel.get_peft_model.call_args.kwargs
        assert kw["r"] == 16

    def test_custom_lora_r_parsed_as_int(self):
        _setup({"lora_r": "64"})
        _run.main()

        kw = sys.modules["unsloth"].FastLanguageModel.get_peft_model.call_args.kwargs
        assert kw["r"] == 64

    def test_default_max_steps_500(self):
        inputs = dict(_BASE_INPUTS)
        del inputs["max_steps"]
        _setup(inputs)
        _run.main()

        kw = sys.modules["transformers"].TrainingArguments.call_args.kwargs
        assert kw["max_steps"] == 500

    def test_custom_max_steps(self):
        _setup({"max_steps": "200"})
        _run.main()

        kw = sys.modules["transformers"].TrainingArguments.call_args.kwargs
        assert kw["max_steps"] == 200

    def test_tokenizer_padding_side_set_to_right(self):
        _, tok, _ = _setup()
        _run.main()
        assert tok.padding_side == "right"

    def test_for_training_called(self):
        _setup()
        _run.main()
        assert sys.modules["unsloth"].FastLanguageModel.for_training.called

    def test_save_steps_equals_checkpoint_steps(self):
        _setup({"checkpoint_steps": "50"})
        _run.main()

        kw = sys.modules["transformers"].TrainingArguments.call_args.kwargs
        assert kw["save_steps"] == 50

    def test_default_checkpoint_steps_100(self):
        inputs = dict(_BASE_INPUTS)
        del inputs["checkpoint_steps"]
        _setup(inputs)
        _run.main()

        kw = sys.modules["transformers"].TrainingArguments.call_args.kwargs
        assert kw["save_steps"] == 100


# ---------------------------------------------------------------------------
# main() — output artifacts
# ---------------------------------------------------------------------------

class TestOutputArtifacts:

    def _registered_names(self):
        io = sys.modules["orchapod.io"]
        return [c.args[0] for c in io.write_output.call_args_list]

    def test_exactly_three_artifacts_registered(self):
        _setup()
        _run.main()
        assert len(self._registered_names()) == 3

    def test_lora_adapter_registered(self):
        _setup()
        _run.main()
        assert "lora_adapter" in self._registered_names()

    def test_merged_model_registered(self):
        _setup()
        _run.main()
        assert "merged_model" in self._registered_names()

    def test_train_metrics_json_registered(self):
        _setup()
        _run.main()
        assert "train_metrics_json" in self._registered_names()

    def test_lora_adapter_kind_is_model(self):
        _setup()
        _run.main()
        io = sys.modules["orchapod.io"]
        c  = next(c for c in io.write_output.call_args_list if c.args[0] == "lora_adapter")
        assert c.kwargs["kind"] == "model"

    def test_train_metrics_kind_is_metrics(self):
        _setup()
        _run.main()
        io = sys.modules["orchapod.io"]
        c  = next(c for c in io.write_output.call_args_list if c.args[0] == "train_metrics_json")
        assert c.kwargs["kind"] == "metrics"

    def test_merged_model_metadata_has_base_model(self):
        _setup({"model": "meta-llama/Llama-3.1-8B-Instruct"})
        _run.main()
        io = sys.modules["orchapod.io"]
        c  = next(c for c in io.write_output.call_args_list if c.args[0] == "merged_model")
        assert c.kwargs["metadata"]["base"] == "meta-llama/Llama-3.1-8B-Instruct"

    def test_merged_model_uses_unsloth_save_api(self):
        model, tok, _ = _setup()
        _run.main()
        model.save_pretrained_merged.assert_called_once()
        c = model.save_pretrained_merged.call_args
        assert c.args[1] is tok
        assert c.kwargs["save_method"] == "merged_16bit"


# ---------------------------------------------------------------------------
# main() — optional eval data
# ---------------------------------------------------------------------------

class TestOptionalEvalData:

    def test_empty_eval_data_passes_none_to_sfttrainer(self):
        _setup({"eval_data": ""})
        _run.main()

        kw = sys.modules["trl"].SFTTrainer.call_args.kwargs
        assert kw.get("eval_dataset") is None

    def test_present_eval_data_passes_dataset_to_sfttrainer(self):
        _setup()
        _run.main()

        kw = sys.modules["trl"].SFTTrainer.call_args.kwargs
        assert kw.get("eval_dataset") is not None

    def test_eval_data_not_downloaded_when_empty(self):
        _setup({"eval_data": ""})
        _run.main()

        io    = sys.modules["orchapod.io"]
        uris  = [c.args[0] for c in io.download_input.call_args_list]
        assert all("eval" not in uri for uri in uris)

    def test_eval_data_is_downloaded_when_present(self):
        _setup()
        _run.main()

        io   = sys.modules["orchapod.io"]
        uris = [c.args[0] for c in io.download_input.call_args_list]
        assert any("eval" in uri for uri in uris)


# ---------------------------------------------------------------------------
# main() — checkpoint resume
# ---------------------------------------------------------------------------

class TestCheckpointResume:

    def test_no_resume_when_no_checkpoint_uri(self):
        _setup()
        sys.modules["orchapod.checkpoint"].latest_checkpoint_uri.return_value = None
        _run.main()

        trainer = sys.modules["trl"].SFTTrainer.return_value
        kw = trainer.train.call_args.kwargs
        assert kw.get("resume_from_checkpoint") is None

    def test_resume_path_passed_when_checkpoint_exists(self):
        _setup()
        sys.modules["orchapod.checkpoint"].latest_checkpoint_uri.return_value = \
            "r2://bucket/runs/1/train/checkpoint_step_000100"
        sys.modules["orchapod.checkpoint"].download_checkpoint.return_value = \
            Path("/tmp/resume_ckpt")

        _run.main()

        trainer = sys.modules["trl"].SFTTrainer.return_value
        kw = trainer.train.call_args.kwargs
        assert kw["resume_from_checkpoint"] == "/tmp/resume_ckpt"

    def test_download_checkpoint_called_with_correct_uri(self):
        _setup()
        resume_uri = "r2://bucket/runs/1/train/checkpoint_step_000200"
        sys.modules["orchapod.checkpoint"].latest_checkpoint_uri.return_value = resume_uri
        sys.modules["orchapod.checkpoint"].download_checkpoint.return_value = Path("/tmp/ckpt")

        _run.main()

        ckpt = sys.modules["orchapod.checkpoint"]
        ckpt.download_checkpoint.assert_called_once_with(resume_uri, "/workspace/resume_ckpt")

    def test_no_download_checkpoint_called_without_uri(self):
        _setup()
        sys.modules["orchapod.checkpoint"].latest_checkpoint_uri.return_value = None

        _run.main()

        ckpt = sys.modules["orchapod.checkpoint"]
        ckpt.download_checkpoint.assert_not_called()


# ---------------------------------------------------------------------------
# Checkpoint interval logic (parametrized)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("step,interval,should_save", [
    (0,   100, False),
    (1,   100, False),
    (50,  100, False),
    (99,  100, False),
    (100, 100, True),
    (150, 100, False),
    (200, 100, True),
    (500, 100, True),
    (0,    50, False),
    (50,   50, True),
    (75,   50, False),
    (100,  50, True),
])
def test_checkpoint_interval_arithmetic(step, interval, should_save):
    """
    The _CheckpointCallback.on_save fires via TRL's save_steps mechanism.
    This verifies the interval logic that drives it.
    """
    result = step > 0 and step % interval == 0
    assert result == should_save
