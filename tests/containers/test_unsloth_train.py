"""Unit tests for containers/unsloth-train/run.py (docs/contracts.md "ML nodes → unsloth-train"). No GPU: unsloth, trl,
transformers, datasets and torch are fakes that sit in sys.modules only while a test runs."""

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from packages.workflow_schema.models import NODE_REGISTRY, NodeType, UnslothTrainInputs, UnslothTrainOutputs

from .conftest import load_container

ut = load_container("unsloth-train")

STUDENT = "nvidia/Llama-3.1-Nemotron-Nano-8B-v1"
TRAIN, EVAL = "r2://orchapod-artifacts/runs/r1/prep/train_jsonl", "r2://orchapod-artifacts/runs/r1/prep/eval_jsonl"
ROWS = [{"messages": [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}]} for i in range(3)]


class FakeDataset(list):
    @classmethod
    def from_list(cls, rows):
        return cls(rows)

    def map(self, fn, remove_columns=()):
        return FakeDataset({k: v for k, v in {**r, **fn(r)}.items() if k not in remove_columns} for r in self)


class FakeTrainer:
    """Logs two training steps and a validation at step 2, then saves checkpoint-2."""

    def __init__(self, **kw):
        self.kw = kw
        FakeTrainer.last = self

    def train(self, resume_from_checkpoint=None):
        self.resume = resume_from_checkpoint
        args, (report,) = self.kw["args"], self.kw["callbacks"]
        for step, logs in ((1, {"loss": 2.0}), (2, {"loss": 1.0}), (2, {"eval_loss": 1.5})):
            report.on_log(args, SimpleNamespace(global_step=step), None, logs=logs)
        report.on_save(args, SimpleNamespace(global_step=2), None)


@pytest.fixture
def gpu(monkeypatch):
    """Fake GPU libraries; gpu.model is what FastLanguageModel loads, gpu.flm the fake FastLanguageModel."""
    model = MagicMock()
    model.config.model_type = "llama"
    tok = MagicMock()
    tok.apply_chat_template.side_effect = lambda msgs, **kw: "<BOS>" + "|".join(m["content"] for m in msgs)
    flm = MagicMock()
    flm.from_pretrained.return_value = (model, tok)
    flm.get_peft_model.return_value = model
    mods = {"unsloth": {"FastLanguageModel": flm}, "datasets": {"Dataset": FakeDataset},
            "transformers": {"TrainerCallback": object},
            "trl": {"SFTTrainer": FakeTrainer, "SFTConfig": lambda **kw: SimpleNamespace(**kw)},
            "torch": {"cuda": SimpleNamespace(get_device_name=lambda i: "NVIDIA H100 80GB HBM3")}}
    for name, attrs in mods.items():
        monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(**attrs))
    return SimpleNamespace(model=model, tok=tok, flm=flm)


@pytest.fixture
def node(mock_orchapod_io, monkeypatch, tmp_path):
    """node(**inputs) runs main(); returns ({output: (path, metadata)}, metrics). node.objects maps r2 URIs to rows."""
    monkeypatch.delenv("STUB", raising=False)
    monkeypatch.setattr(ut, "WORK", tmp_path)
    monkeypatch.setattr(ut, "cost", MagicMock(BudgetExceeded=type("BudgetExceeded", (RuntimeError,), {})))
    monkeypatch.setattr(ut, "checkpoint", MagicMock(latest_checkpoint_uri=MagicMock(return_value=None)))
    objects = {TRAIN: ROWS, EVAL: ROWS[:1]}

    def download(uri, local_dir):
        path = Path(local_dir) / uri.rsplit("/", 1)[1]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in objects[uri]))
        return path

    mock_orchapod_io.download_input.side_effect = download

    def run(**inputs):
        mock_orchapod_io.read_inputs.return_value = {"model": STUDENT, "train_data": TRAIN, "eval_data": EVAL, **inputs}
        ut.main()
        outs = {c.args[0]: (Path(c.args[1]), c.kwargs["metadata"]) for c in mock_orchapod_io.write_output.call_args_list}
        return outs, mock_orchapod_io.write_metrics.call_args.args[0]

    run.objects = objects
    return run


def test_registry_row_is_a_16_bit_lora_gpu_node_on_the_spike_4_student():
    meta = NODE_REGISTRY[NodeType.UNSLOTH_TRAIN]
    assert meta["runtime"] == "gpu" and set(UnslothTrainOutputs.model_fields) == {"lora_adapter", "merged_model"}
    i = UnslothTrainInputs(train_data=TRAIN)
    assert (i.model, i.load_in_4bit, i.max_steps, i.lora_r, i.lora_alpha) == (STUDENT, False, 500, 16, 32)


def test_trains_16_bit_lora_with_the_templates_bos_and_writes_adapter_merged_and_loss_curve(node, gpu):
    outs, metrics = node(max_steps=60, checkpoint_steps=20)
    assert gpu.flm.from_pretrained.call_args.args == (STUDENT,)
    assert {k: gpu.flm.from_pretrained.call_args.kwargs[k] for k in ("load_in_4bit", "load_in_16bit", "max_seq_length")} \
        == {"load_in_4bit": False, "load_in_16bit": True, "max_seq_length": 2048}
    peft = gpu.flm.get_peft_model.call_args.kwargs
    assert (peft["r"], peft["lora_alpha"], "target_modules" in peft) == (16, 32, False)  # Unsloth's q,k,v,o,gate,up,down
    trainer = FakeTrainer.last.kw
    assert [r["text"] for r in trainer["train_dataset"]] == ["<BOS>q0|a0", "<BOS>q1|a1", "<BOS>q2|a2"]  # BOS kept
    assert set(trainer["train_dataset"][0]) == {"text"} and len(trainer["eval_dataset"]) == 1
    args = trainer["args"]
    assert (args.max_steps, args.save_steps, args.eval_steps, args.eval_strategy, args.logging_steps, args.bf16) == (
        60, 20, 20, "steps", 1, True)
    assert gpu.model.save_pretrained_merged.call_args.kwargs == {"save_method": "merged_16bit"}
    assert {n: (p.name, m) for n, (p, m) in outs.items()} == {
        "lora_adapter": ("lora_adapter", {"format": "peft", "base_model": STUDENT}),
        "merged_model": ("merged_model", {"format": "hf", "base_model": STUDENT})}
    assert metrics["loss_curve"] == [{"step": 1, "train_loss": 2.0}, {"step": 2, "train_loss": 1.0, "valid_loss": 1.5}]
    assert (metrics["steps"], metrics["train_rows"], metrics["eval_rows"]) == (2, 3, 1)
    ut.log.progress.assert_any_call(2, 60, loss=1.0)
    ut.checkpoint.save_checkpoint.assert_called_once_with(2, Path(args.output_dir) / "checkpoint-2")
    bills = ut.cost.add.call_args_list
    assert len(bills) == 5 and all(b.args == ("nebius_serverless", "gpu-h100-sxm/1gpu-16vcpu-200gb") for b in bills)


@pytest.mark.parametrize("eval_data", ["", "empty"])
def test_no_validation_without_eval_rows(node, gpu, eval_data):
    node.objects["r2://orchapod-artifacts/runs/r1/prep/empty"] = []
    node(eval_data="r2://orchapod-artifacts/runs/r1/prep/empty" if eval_data else "")
    assert FakeTrainer.last.kw["eval_dataset"] is None and FakeTrainer.last.kw["args"].eval_strategy == "no"


@pytest.mark.parametrize("model_type, given, want", [
    ("nemotron_h", "all-linear", ut.NEMOTRON_H),  # PEFT refuses Mamba out_proj and conv1d (spike 4)
    ("llama", "q_proj, v_proj", ["q_proj", "v_proj"]),
    ("llama", r".*\.q_proj", r".*\.q_proj"),
], ids=["nemotron-h", "list", "regex"])
def test_target_modules(node, gpu, model_type, given, want):
    gpu.model.config.model_type = model_type
    node(target_modules=given)
    assert gpu.flm.get_peft_model.call_args.kwargs["target_modules"] == want


def test_4_bit_and_resume_from_the_newest_checkpoint(node, gpu):
    ut.checkpoint.latest_checkpoint_uri.return_value = "r2://orchapod-artifacts/runs/r1/train/checkpoint_step_000100"
    ut.checkpoint.download_checkpoint.return_value = Path("/workspace/resume")
    node(load_in_4bit=True)
    kw = gpu.flm.from_pretrained.call_args.kwargs
    assert (kw["load_in_4bit"], kw["load_in_16bit"]) == (True, False)
    assert FakeTrainer.last.resume == "/workspace/resume"


def test_the_budget_stops_training_and_nothing_is_written(node, gpu, mock_orchapod_io):
    ut.cost.add.side_effect = [None, ut.cost.BudgetExceeded("node spend passed ORCHAPOD_MAX_COST_USD")] + [None] * 9
    with pytest.raises(ut.cost.BudgetExceeded):
        node()
    assert not mock_orchapod_io.write_output.called and not gpu.model.save_pretrained_merged.called


@pytest.mark.parametrize("inputs, error", [
    ({"train_data": "${{ nodes.prep.outputs.train_jsonl }}"}, "unresolved ref train_data"),
    ({"train_data": "r2://orchapod-artifacts/runs/r1/prep/empty"}, "no training rows"),
])
def test_refused_before_the_gpu_is_touched(node, gpu, inputs, error):
    node.objects["r2://orchapod-artifacts/runs/r1/prep/empty"] = []
    with pytest.raises(SystemExit) as e:
        node(**inputs)
    assert e.value.code == 1 and error in ut.log.error.call_args.args[0]
    assert not gpu.flm.from_pretrained.called and not ut.cost.add.called


def test_stub_writes_small_fixed_outputs_without_gpu_libraries(node, monkeypatch):
    monkeypatch.setenv("STUB", "1")
    outs, metrics = node()  # no fake GPU modules are installed: importing one would fail
    assert json.loads((outs["lora_adapter"][0] / "adapter_config.json").read_text())["base_model_name_or_path"] == STUDENT
    assert (outs["merged_model"][0] / "config.json").exists() and len(metrics["loss_curve"]) == 2
    assert not ut.cost.add.called
