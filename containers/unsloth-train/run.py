"""
containers/unsloth-train/run.py

Node: unsloth-train
Base image: nvcr.io/nvidia/pytorch:24.10-py3 + Unsloth, TRL, transformers
GPU: 1x H100 80GB (Qwen3-4B fits with batch 8 in QLoRA)
Demo runtime: ~12 minutes for 500 steps on Dolly subset

Inputs:
  model            — HuggingFace model ID (default: Qwen/Qwen3-4B-Instruct)
  train_data       — R2 URI to train JSONL
  eval_data        — R2 URI to eval JSONL (optional, "" = skip)
  lora_r           — LoRA rank (default: 16)
  lora_alpha       — LoRA alpha (default: 32)
  max_steps        — Training steps (default: 500)
  learning_rate    — (default: 2e-4)
  target_modules   — (default: "all-linear")
  checkpoint_steps — Save checkpoint to R2 every N steps (default: 100)

Outputs:
  lora_adapter       — PEFT format adapter
  merged_model       — Full HF format (adapter merged into base, 16-bit)
  train_metrics_json — Loss curve and final metrics JSON
"""

import json
from pathlib import Path

from orchapod import io, log, checkpoint
from transformers import TrainerCallback


def _build_formatting_func(tokenizer):
    """Apply the model's chat template to convert messages lists into training strings."""
    def formatting_func(examples):
        return [
            tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            for msgs in examples["messages"]
        ]
    return formatting_func


def main():
    inputs = io.read_inputs()
    log.info("unsloth-train starting")

    model_id         = inputs.get("model", "Qwen/Qwen3-4B-Instruct")
    train_data_uri   = inputs["train_data"]
    eval_data_uri    = inputs.get("eval_data", "")
    lora_r           = int(inputs.get("lora_r", 16))
    lora_alpha       = int(inputs.get("lora_alpha", 32))
    max_steps        = int(inputs.get("max_steps", 500))
    learning_rate    = float(inputs.get("learning_rate", 2e-4))
    target_modules   = inputs.get("target_modules", "all-linear")
    checkpoint_steps = int(inputs.get("checkpoint_steps", 100))

    # Download datasets
    log.info("Downloading training data")
    train_path = io.download_input(train_data_uri, "/workspace/data/train")

    eval_path = None
    if eval_data_uri:
        log.info("Downloading eval data")
        eval_path = io.download_input(eval_data_uri, "/workspace/data/eval")

    # Load model + LoRA
    log.info(f"Loading {model_id} with Unsloth (4-bit QLoRA)")
    from unsloth import FastLanguageModel
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_id,
        max_seq_length=2048,
        dtype=None,       # auto-detect bf16/fp16
        load_in_4bit=True,
    )
    tokenizer.padding_side = "right"

    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_r,
        target_modules=target_modules,
        lora_alpha=lora_alpha,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )
    FastLanguageModel.for_training(model)
    log.info("Model loaded, LoRA applied")

    # Load HF datasets
    from datasets import load_dataset
    train_ds = load_dataset("json", data_files=str(train_path), split="train")
    eval_ds = (
        load_dataset("json", data_files=str(eval_path), split="train")
        if eval_path else None
    )

    # Resume from checkpoint if the control plane injected one
    resume_ckpt = checkpoint.latest_checkpoint_uri()
    resume_path = None
    if resume_ckpt:
        log.info(f"Resuming from checkpoint: {resume_ckpt}")
        resume_path = checkpoint.download_checkpoint(resume_ckpt, "/workspace/resume_ckpt")

    from trl import SFTTrainer
    from transformers import TrainingArguments

    metrics_log: list[dict] = []

    class _MetricsCallback(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            if not logs:
                return
            step = state.global_step
            loss = logs.get("loss")
            if loss is not None:
                metrics_log.append({"step": step, "loss": loss})
                log.progress(step=step, total=max_steps, loss=loss)

    class _CheckpointCallback(TrainerCallback):
        """Upload each TRL-managed checkpoint directory to R2 as it's written."""
        def on_save(self, args, state, control, **kwargs):
            step = state.global_step
            ckpt_dir = Path(args.output_dir) / f"checkpoint-{step}"
            if ckpt_dir.exists():
                checkpoint.save_checkpoint(step, ckpt_dir)
            return control

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        formatting_func=_build_formatting_func(tokenizer),
        max_seq_length=2048,
        args=TrainingArguments(
            per_device_train_batch_size=8,
            gradient_accumulation_steps=1,
            warmup_steps=10,
            max_steps=max_steps,
            learning_rate=learning_rate,
            fp16=False,
            bf16=True,
            logging_steps=10,
            save_steps=checkpoint_steps,
            save_total_limit=3,
            optim="adamw_8bit",
            output_dir="/workspace/training_output",
            report_to="none",
        ),
        callbacks=[_MetricsCallback(), _CheckpointCallback()],
    )
    trainer.train(resume_from_checkpoint=str(resume_path) if resume_path else None)
    log.info("Training complete")

    # Save LoRA adapter (PEFT format)
    adapter_path = Path("/workspace/lora_adapter")
    model.save_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))
    log.info("Adapter saved")

    # Merge adapter into base weights and save full model (16-bit)
    log.info("Merging LoRA weights (16-bit)")
    merged_path = Path("/workspace/merged_model")
    model.save_pretrained_merged(str(merged_path), tokenizer, save_method="merged_16bit")

    # Write metrics JSON
    metrics_path = io.local_path("train_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump({
            "model": model_id,
            "lora_r": lora_r,
            "lora_alpha": lora_alpha,
            "max_steps": max_steps,
            "learning_rate": learning_rate,
            "final_loss": metrics_log[-1]["loss"] if metrics_log else None,
            "loss_curve": metrics_log,
        }, f, indent=2)

    # Upload all outputs to R2
    io.write_output("lora_adapter",       adapter_path, kind="model",   metadata={"format": "peft"})
    io.write_output("merged_model",       merged_path,  kind="model",   metadata={"format": "hf", "base": model_id})
    io.write_output("train_metrics_json", metrics_path, kind="metrics")

    log.info("unsloth-train complete")


if __name__ == "__main__":
    main()
