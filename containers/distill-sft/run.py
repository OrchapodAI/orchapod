"""
containers/distill-sft/run.py

Node: distill-sft  (knowledge distillation, off-policy)
Base image: same as unsloth-train + vLLM (for teacher inference)
GPU: 1x H100 80GB (4B teacher + 1.7B student fit together)
Demo runtime: ~20 minutes (10 min teacher inference + 10 min student SFT)

Method: off-policy distillation (classic, not on-policy)
  1. Spin up teacher in vLLM on the same pod
  2. For each training prompt, sample 1 completion (temperature=0.7)
  3. Save (prompt, teacher_completion) pairs as new dataset
  4. SFT the student on this synthetic dataset via Unsloth

Why off-policy not on-policy:
  On-policy distillation (Tinker's Oct 2025 technique) needs the student to roll out
  and the teacher to score logprobs in lockstep — V1 work.

Inputs:
  teacher       — R2 URI or HF ID of teacher model
  student_base  — HF ID of student base model (default: Qwen/Qwen3-1.7B-Instruct)
  train_data    — R2 URI to prompts-only JSONL
  n_synthetic   — number of synthetic examples to generate (default: 5000)

Outputs:
  student_model       — trained student in HF format
  synthetic_dataset   — the generated (prompt, completion) pairs
  distill_metrics_json
"""

import json
import subprocess
import time
from pathlib import Path

from orchapod import io, log


def start_teacher_vllm(model_path: Path) -> str:
    """Start vLLM server with the teacher model. Returns the base URL."""
    log.info(f"Starting teacher vLLM server with {model_path}")
    proc = subprocess.Popen([
        "python", "-m", "vllm.entrypoints.openai.api_server",
        "--model", str(model_path),
        "--port", "8001",
        "--max-model-len", "4096",
        "--dtype", "bfloat16",
    ])
    # Wait for server to be ready
    import urllib.request
    for _ in range(60):
        try:
            urllib.request.urlopen("http://localhost:8001/health", timeout=2)
            log.info("Teacher vLLM server ready")
            return "http://localhost:8001"
        except Exception:
            time.sleep(2)
    raise RuntimeError("Teacher vLLM server failed to start after 120 seconds")


def generate_completions(prompts: list[str], vllm_url: str, n: int, model_name: str) -> list[dict]:
    """Sample teacher completions for each prompt."""
    import urllib.request
    completions = []
    for i, prompt in enumerate(prompts[:n]):
        if i % 100 == 0:
            log.info(f"Generating synthetic example {i}/{n}")
        payload = json.dumps({
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 512,
        }).encode()
        req = urllib.request.Request(
            f"{vllm_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        resp = json.loads(urllib.request.urlopen(req).read())
        answer = resp["choices"][0]["message"]["content"]
        completions.append({"messages": [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": answer},
        ]})
    return completions


def main():
    inputs = io.read_inputs()
    log.info("distill-sft starting")

    teacher_uri   = inputs["teacher"]
    student_base  = inputs.get("student_base", "Qwen/Qwen3-1.7B-Instruct")
    train_data_uri = inputs["train_data"]
    n_synthetic   = int(inputs.get("n_synthetic", 5000))

    # Download teacher model
    log.info("Downloading teacher model from R2")
    teacher_path = io.download_input(teacher_uri, "/workspace/teacher")

    # Download training prompts
    train_path = io.download_input(train_data_uri, "/workspace/data")
    with open(train_path) as f:
        train_examples = [json.loads(l) for l in f if l.strip()]

    # Extract prompts only (user messages)
    prompts = []
    for ex in train_examples:
        msgs = ex.get("messages", [])
        user_msgs = [m["content"] for m in msgs if m["role"] == "user"]
        if user_msgs:
            prompts.append(user_msgs[0])

    log.info(f"Extracted {len(prompts)} prompts from training data")

    # Start teacher inference
    vllm_url = start_teacher_vllm(teacher_path)

    # Generate synthetic dataset
    log.info(f"Generating {n_synthetic} synthetic examples from teacher")
    synthetic = generate_completions(prompts, vllm_url, n=n_synthetic, model_name=str(teacher_path))
    log.info(f"Generated {len(synthetic)} examples")

    # Save synthetic dataset
    synth_path = io.local_path("synthetic_dataset.jsonl")
    with open(synth_path, "w") as f:
        for ex in synthetic:
            f.write(json.dumps(ex) + "\n")
    io.write_output("synthetic_dataset", synth_path, kind="dataset")

    # Train student on synthetic dataset
    log.info(f"Training student {student_base} on synthetic dataset")
    from unsloth import FastLanguageModel
    from trl import SFTTrainer
    from transformers import TrainingArguments
    from datasets import load_dataset

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=student_base,
        max_seq_length=2048,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(model, r=16, lora_alpha=32,
                                             target_modules="all-linear",
                                             lora_dropout=0, bias="none",
                                             use_gradient_checkpointing="unsloth")

    ds = load_dataset("json", data_files=str(synth_path), split="train")

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=ds,
        dataset_text_field="messages",
        max_seq_length=2048,
        args=TrainingArguments(
            per_device_train_batch_size=8,
            max_steps=500,
            learning_rate=2e-4,
            bf16=True,
            output_dir="/workspace/student_output",
            report_to="none",
        ),
    )
    trainer.train()

    student_path = Path("/workspace/student_model")
    model.merge_and_unload().save_pretrained(str(student_path))
    tokenizer.save_pretrained(str(student_path))

    # Metrics
    metrics_path = io.local_path("distill_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump({"teacher": str(teacher_path), "student_base": student_base,
                   "n_synthetic": n_synthetic, "examples_generated": len(synthetic)}, f)

    io.write_output("student_model",        student_path, kind="model")
    io.write_output("distill_metrics_json", metrics_path, kind="metrics")
    log.info("distill-sft complete")


if __name__ == "__main__":
    main()
