"""Spike 4: Unsloth 16-bit LoRA on 200 alpaca rows (60 steps), then merge to 16-bit.

python train.py MODEL OUT_DIR  ->  OUT_DIR/merged/ and OUT_DIR/train_metrics.json
Env: TARGETS = LoRA target regex (default: Unsloth's q,k,v,o,gate,up,down list);
     SYSTEM  = system prompt (default "detailed thinking off"; "" = none).
"""
import json
import os
import sys
import time

from unsloth import FastLanguageModel  # import first: Unsloth patches transformers and trl

import torch
from datasets import load_dataset
from trl import SFTConfig, SFTTrainer

model_id, out = sys.argv[1], sys.argv[2]
system = os.environ.get("SYSTEM", "detailed thinking off")
secs = {}

t = time.time()
model, tok = FastLanguageModel.from_pretrained(
    model_id, max_seq_length=1024, load_in_4bit=False, load_in_16bit=True, trust_remote_code=True
)
secs["load_s"] = time.time() - t
targets = {"target_modules": os.environ["TARGETS"]} if os.environ.get("TARGETS") else {}
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=16, lora_dropout=0, use_gradient_checkpointing="unsloth", random_state=3407, **targets
)


def fmt(row):
    msgs = [{"role": "system", "content": system}] if system else []
    msgs += [
        {"role": "user", "content": row["instruction"] + ("\n\n" + row["input"] if row["input"] else "")},
        {"role": "assistant", "content": row["output"]},
    ]
    # Keep the template's BOS: Unsloth's SFT prep skips add_special_tokens when the template contains BOS
    # (run 1 stripped it, so it trained without BOS; first-step loss 4.5 instead of about 2).
    return {"text": tok.apply_chat_template(msgs, tokenize=False, enable_thinking=False)}


ds = load_dataset("yahma/alpaca-cleaned", split="train[:200]")
ds = ds.map(fmt, remove_columns=ds.column_names)
trainer = SFTTrainer(
    model=model,
    processing_class=tok,
    train_dataset=ds,
    args=SFTConfig(
        dataset_text_field="text", max_length=1024, per_device_train_batch_size=2, gradient_accumulation_steps=4,
        max_steps=60, warmup_steps=5, learning_rate=2e-4, lr_scheduler_type="linear", optim="adamw_8bit",
        weight_decay=0.01, logging_steps=1, bf16=True, seed=3407, save_strategy="no", report_to="none",
        output_dir=f"{out}/ckpt",
    ),
)
t = time.time()
trainer.train()
secs["train_s"] = time.time() - t
loss = [h["loss"] for h in trainer.state.log_history if "loss" in h]
peak = torch.cuda.max_memory_allocated() / 2**30

t = time.time()
model.save_pretrained_merged(f"{out}/merged", tok, save_method="merged_16bit")
secs["merge_s"] = time.time() - t

m = {"model": model_id, "rows": len(ds), "steps": len(loss), "loss_first5": loss[:5], "loss_last5": loss[-5:],
     "peak_vram_gib": round(peak, 1), **{k: round(v, 1) for k, v in secs.items()}, "loss": loss}
json.dump(m, open(f"{out}/train_metrics.json", "w"), indent=2)
print("TRAIN_METRICS", json.dumps({k: v for k, v in m.items() if k != "loss"}))
