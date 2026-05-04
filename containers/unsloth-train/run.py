"""
containers/unsloth-train/run.py

Node: unsloth-train
Base image: nvcr.io/nvidia/pytorch:24.10-py3 + Unsloth, TRL, transformers
GPU: 1x H100 80GB (Qwen3-4B fits with batch 8 in QLoRA)
Demo runtime: ~12 minutes for 500 steps on Dolly subset

Inputs:
  model          — HuggingFace model ID (default: Qwen/Qwen3-4B-Instruct)
  train_data     — R2 URI to train JSONL
  eval_data      — R2 URI to eval JSONL
  lora_r         — LoRA rank (default: 16)
  lora_alpha     — LoRA alpha (default: 32)
  max_steps      — Training steps (default: 500)
  learning_rate  — (default: 2e-4)
  target_modules — (default: "all-linear")

Outputs:
  lora_adapter       — PEFT format adapter
  merged_model       — Full HF format (adapter merged into base)
  train_metrics_json — Loss curve and final metrics
"""

import json
from pathlib import Path

from orchapod import io, log, checkpoint


def main():
    inputs = io.read_inputs()
    log.info("unsloth-train starting")

    model_id        = inputs.get("model", "Qwen/Qwen3-4B-Instruct")
    train_data_uri  = inputs["train_data"]
    eval_data_uri   = inputs["eval_data"]
    lora_r          = int(inputs.get("lora_r", 16))
    lora_alpha      = int(inputs.get("lora_alpha", 32))
    max_steps       = int(inputs.get("max_steps", 500))
    learning_rate   = float(inputs.get("learning_rate", 2e-4))
    target_modules  = inputs.get("target_modules", "all-linear")

    # Download datasets from R2
    log.info("Downloading datasets from R2")
    train_path = io.download_input(train_data_uri, "/workspace/data")
    eval_path  = io.download_input(eval_data_uri,  "/workspace/data")

    # Load Unsloth model
    log.info(f"Loading {model_id} with Unsloth (4-bit QLoRA)")
    from unsloth import FastLanguageModel
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_id,
        max_seq_length=2048,
        dtype=None,       # auto
        load_in_4bit=True,
    )
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
    log.info("Model loaded and LoRA configured")

    # Load datasets
    from datasets import load_dataset
    train_ds = load_dataset("json", data_files=str(train_path), split="train")
    eval_ds  = load_dataset("json", data_files=str(eval_path),  split="train")

    # Check for checkpoint resume
    resume_ckpt = checkpoint.latest_checkpoint_uri()
    if resume_ckpt:
        log.info(f"Resuming from checkpoint: {resume_ckpt}")
        resume_path = io.download_input(resume_ckpt, "/workspace/resume_ckpt")
    else:
        resume_path = None

    # Train
    from trl import SFTTrainer
    from transformers import TrainingArguments

    metrics_log = []

    class MetricsCallback:
        def on_log(self, args, state, control, logs=None, **kwargs):
            if logs:
                step = state.global_step
                loss = logs.get("loss")
                metrics_log.append({"step": step, "loss": loss})
                log.progress(step=step, total=max_steps, loss=loss)
                if checkpoint.should_checkpoint(step):
                    ckpt_path = Path(f"/workspace/checkpoints/step_{step:06d}")
                    ckpt_path.mkdir(parents=True, exist_ok=True)
                    model.save_pretrained(str(ckpt_path))
                    checkpoint.save_checkpoint(step, ckpt_path)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
        dataset_text_field="messages",
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
            optim="adamw_8bit",
            output_dir="/workspace/training_output",
            report_to="none",
        ),
        callbacks=[MetricsCallback()],
    )
    trainer.train(resume_from_checkpoint=str(resume_path) if resume_path else None)
    log.info("Training complete — saving adapter")

    # Save LoRA adapter
    adapter_path = Path("/workspace/lora_adapter")
    model.save_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))

    # Merge and save full model
    log.info("Merging LoRA into base model")
    merged_path = Path("/workspace/merged_model")
    model.merge_and_unload().save_pretrained(str(merged_path))
    tokenizer.save_pretrained(str(merged_path))

    # Save metrics
    metrics_path = io.local_path("train_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump({
            "model": model_id,
            "lora_r": lora_r,
            "max_steps": max_steps,
            "learning_rate": learning_rate,
            "final_loss": metrics_log[-1]["loss"] if metrics_log else None,
            "loss_curve": metrics_log,
        }, f, indent=2)

    # Upload outputs
    io.write_output("lora_adapter",       adapter_path, kind="model",   metadata={"format": "peft"})
    io.write_output("merged_model",       merged_path,  kind="model",   metadata={"format": "hf", "base": model_id})
    io.write_output("train_metrics_json", metrics_path, kind="metrics")

    log.info("unsloth-train complete")


if __name__ == "__main__":
    main()
