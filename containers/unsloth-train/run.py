"""
containers/unsloth-train/run.py — node unsloth-train (gpu: a Nebius Serverless Job). Contract: docs/contracts.md
"ML nodes → unsloth-train" (Lane B train).

Unsloth LoRA, 16-bit unless load_in_4bit, with spike 4's recipe and pins (containers/unsloth-train/spike) on data-prep's
chat rows: train_data, and eval_data ("" or an empty file = no validation). Training stops at max_steps, the demo's knob
(the Job times out at 1 h). Rows keep the chat template's BOS (spike 4: stripping it trained without one). target_modules
all-linear is Unsloth's q, k, v, o, gate, up, down; a NemotronH student trains attention, in_proj and the shared experts,
because PEFT refuses Mamba out_proj and conv1d and the router stays frozen. Every checkpoint_steps a
checkpoint_step_NNNNNN goes to the bucket (and validation runs); a retry resumes from ORCHAPOD_RESUME_CHECKPOINT_URI.
Outputs: lora_adapter (PEFT), merged_model (16-bit HF, vllm-serve's model) and metrics_json with
loss_curve [{step, train_loss, valid_loss}]. All I/O goes through the SDK. GPU time is billed as it runs, so
ORCHAPOD_MAX_COST_USD stops training. STUB=1: no GPU and no model download, tiny fixed outputs, a 2-point loss curve.
"""

import contextlib
import json
import os
import sys
import time
from pathlib import Path

from orchapod import checkpoint, cost, io, log

WORK = Path(os.environ.get("WORKSPACE_DIR", "/workspace"))
MAX_LEN = 2048
NEMOTRON_H = r".*\.(q_proj|k_proj|v_proj|o_proj|in_proj)|.*\.shared_experts\.(up_proj|down_proj)"  # spike 4
GPUS = {"H100": "gpu-h100-sxm/1gpu-16vcpu-200gb", "L40S": "gpu-l40s-a/1gpu-8vcpu-32gb"}  # NebiusProvider's presets


def fail(reason: str):
    log.error(reason)
    sys.exit(1)


def read_rows(uri: str) -> list[dict]:
    """data-prep's chat JSONL; "" or an empty file = none."""
    if not uri:
        return []
    with io.download_input(uri, WORK / "data").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def targets(model_type: str, given: str) -> dict:
    """get_peft_model's target_modules: all-linear → Unsloth's default list, or spike 4's regex for NemotronH."""
    if given != "all-linear":
        return {"target_modules": given if any(c in given for c in "*|()\\") else [t.strip() for t in given.split(",")]}
    return {"target_modules": NEMOTRON_H} if model_type == "nemotron_h" else {}


class Meter:
    """GPU time as it runs: cost.add raises BudgetExceeded once the node passes ORCHAPOD_MAX_COST_USD."""

    def __init__(self, device: str):
        self.model = next((p for k, p in GPUS.items() if k in device), device)  # another GPU is unpriced: fails closed
        self.last = time.monotonic()

    def __call__(self):
        now = time.monotonic()
        cost.add("nebius_serverless", self.model, gpu_hours=(now - self.last) / 3600)
        self.last = now


def train(model_id: str, rows: list[list[dict]], p: dict, meter: Meter, adapter_dir: Path, merged_dir: Path) -> list:
    from unsloth import FastLanguageModel  # first: Unsloth patches transformers and trl

    from datasets import Dataset
    from transformers import TrainerCallback
    from trl import SFTConfig, SFTTrainer

    log.info(f"loading {model_id} for {'4-bit' if p['load_in_4bit'] else '16-bit'} LoRA")
    model, tok = FastLanguageModel.from_pretrained(model_id, max_seq_length=MAX_LEN, load_in_4bit=p["load_in_4bit"],
                                                   load_in_16bit=not p["load_in_4bit"], trust_remote_code=True)
    model = FastLanguageModel.get_peft_model(model, r=p["lora_r"], lora_alpha=p["lora_alpha"], lora_dropout=0,
                                             use_gradient_checkpointing="unsloth", random_state=3407,
                                             **targets(model.config.model_type, p["target_modules"]))

    def text(row):  # the template's own BOS stays in the text: Unsloth then adds no special tokens (spike 4)
        return {"text": tok.apply_chat_template(row["messages"], tokenize=False, enable_thinking=False)}

    train_ds, eval_ds = (Dataset.from_list(r).map(text, remove_columns=list(r[0])) if r else None for r in rows)
    curve: dict[int, dict] = {}

    class Report(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kw):
            meter()
            row, logs = curve.setdefault(state.global_step, {"step": state.global_step}), logs or {}
            if "loss" in logs:
                row["train_loss"] = logs["loss"]
                log.progress(state.global_step, p["max_steps"], loss=logs["loss"])
            if "eval_loss" in logs:
                row["valid_loss"] = logs["eval_loss"]

        def on_save(self, args, state, control, **kw):
            checkpoint.save_checkpoint(state.global_step, Path(args.output_dir) / f"checkpoint-{state.global_step}")

    trainer = SFTTrainer(model=model, processing_class=tok, train_dataset=train_ds, eval_dataset=eval_ds,
                         callbacks=[Report()], args=SFTConfig(
                             dataset_text_field="text", max_length=MAX_LEN, per_device_train_batch_size=2,
                             gradient_accumulation_steps=4, max_steps=p["max_steps"], warmup_steps=5,
                             learning_rate=p["learning_rate"], lr_scheduler_type="linear", optim="adamw_8bit",
                             weight_decay=0.01, logging_steps=max(1, p["max_steps"] // 100), bf16=True, seed=3407,
                             save_strategy="steps", save_steps=p["checkpoint_steps"], save_total_limit=2,
                             eval_strategy="steps" if eval_ds else "no", eval_steps=p["checkpoint_steps"],
                             report_to="none", output_dir=str(WORK / "checkpoints")))
    resume = checkpoint.latest_checkpoint_uri()
    log.info(f"training on {len(rows[0])} rows for {p['max_steps']} steps" + (f", resuming {resume}" if resume else ""))
    trainer.train(resume_from_checkpoint=str(checkpoint.download_checkpoint(resume, WORK / "resume")) if resume else None)
    model.save_pretrained(str(adapter_dir))
    tok.save_pretrained(str(adapter_dir))
    log.info("merging the adapter into 16-bit weights")
    model.save_pretrained_merged(str(merged_dir), tok, save_method="merged_16bit")
    return [curve[step] for step in sorted(curve)]


def main():
    inputs = io.read_inputs()
    start = time.monotonic()
    for name in ("model", "train_data", "eval_data"):
        if "${{" in str(inputs.get(name) or ""):
            fail(f"unresolved ref {name}: {inputs.get(name)}")
    model_id = str(inputs.get("model") or "nvidia/Llama-3.1-Nemotron-Nano-8B-v1")
    p = {"lora_r": int(inputs.get("lora_r") or 16), "lora_alpha": int(inputs.get("lora_alpha") or 32),
         "max_steps": int(inputs.get("max_steps") or 500), "learning_rate": float(inputs.get("learning_rate") or 2e-4),
         "target_modules": str(inputs.get("target_modules") or "all-linear"),
         "checkpoint_steps": int(inputs.get("checkpoint_steps") or 100),
         "load_in_4bit": str(inputs.get("load_in_4bit")).lower() in ("true", "1")}
    rows = [read_rows(str(inputs.get(name) or "")) for name in ("train_data", "eval_data")]
    if not rows[0]:
        fail("no training rows in train_data")
    adapter_dir, merged_dir = WORK / "lora_adapter", WORK / "merged_model"
    meter = None
    try:
        if os.environ.get("STUB") == "1":
            curve = [{"step": 1, "train_loss": 1.0}, {"step": 2, "train_loss": 0.5}]
            adapter_dir.mkdir(parents=True, exist_ok=True)
            (adapter_dir / "adapter_config.json").write_text(json.dumps({
                "peft_type": "LORA", "base_model_name_or_path": model_id, "r": p["lora_r"], "lora_alpha": p["lora_alpha"]}))
            merged_dir.mkdir(parents=True, exist_ok=True)
            (merged_dir / "config.json").write_text(json.dumps({"stub": True, "base_model": model_id}))
        else:
            import torch

            meter = Meter(torch.cuda.get_device_name(0))
            meter()  # an unpriced GPU fails here, before the model download (R5)
            curve = train(model_id, rows, p, meter, adapter_dir, merged_dir)
        io.write_output("lora_adapter", adapter_dir, kind="model", metadata={"format": "peft", "base_model": model_id})
        io.write_output("merged_model", merged_dir, kind="model", metadata={"format": "hf", "base_model": model_id})
        io.write_metrics({"model": model_id, **p, "train_rows": len(rows[0]), "eval_rows": len(rows[1]),
                          "steps": curve[-1]["step"] if curve else 0, "loss_curve": curve,
                          "wall_s": round(time.monotonic() - start)})
        log.info(f"unsloth-train complete: {model_id}, {len(curve)} loss points, final {curve[-1] if curve else None}")
    finally:
        if meter:
            with contextlib.suppress(cost.BudgetExceeded):  # recorded either way; nothing is left to stop
                meter()


if __name__ == "__main__":
    main()
