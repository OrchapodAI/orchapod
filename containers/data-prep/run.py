"""
containers/data-prep/run.py

Node: data-prep
Runtime: CPU only (runs on control-plane host, no GPU pod needed)
Base image: python:3.12-slim + datasets, pandas, pyyaml

Inputs:
  dataset     — URI to JSONL/CSV or HuggingFace dataset name
  format      — "chatml" | "alpaca" | "sharegpt"
  train_split — float (default 0.9)

Outputs:
  train_jsonl — R2 URI to training JSONL (ChatML format)
  eval_jsonl  — R2 URI to eval JSONL
  stats_json  — R2 URI to dataset statistics JSON

Logic: load → validate → split → reformat to ChatML → write JSONL

Demo dataset: argilla/databricks-dolly-15k-curated-en (5K rows, public)
"""

import json
import sys
from pathlib import Path

from orchapod import io, log


def load_dataset(uri: str):
    if uri.startswith("hf://") or "/" in uri and not uri.startswith("/"):
        # HuggingFace dataset
        from datasets import load_dataset as hf_load
        dataset_name = uri.replace("hf://", "")
        log.info(f"Loading HuggingFace dataset: {dataset_name}")
        return hf_load(dataset_name, split="train")
    elif uri.startswith("r2://"):
        # Download from R2 first
        local = io.download_input(uri)
        return _load_local(local)
    else:
        return _load_local(Path(uri))


def _load_local(path: Path):
    import pandas as pd
    if path.suffix == ".csv":
        return pd.read_csv(path).to_dict("records")
    elif path.suffix in (".jsonl", ".json"):
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]
    raise ValueError(f"Unsupported file format: {path.suffix}")


def to_chatml(example: dict, fmt: str) -> dict | None:
    """Convert an example from any format to ChatML messages list."""
    if fmt == "chatml":
        return example  # already in format
    elif fmt == "alpaca":
        messages = [{"role": "user", "content": example.get("instruction", "") + "\n" + example.get("input", "")}]
        if example.get("output"):
            messages.append({"role": "assistant", "content": example["output"]})
        return {"messages": messages}
    elif fmt == "sharegpt":
        msgs = []
        for turn in example.get("conversations", []):
            role = "user" if turn["from"] in ("human", "user") else "assistant"
            msgs.append({"role": role, "content": turn["value"]})
        return {"messages": msgs}
    return None


def main():
    inputs = io.read_inputs()
    log.info(f"data-prep starting with inputs: {list(inputs.keys())}")

    dataset_uri  = inputs["dataset"]
    fmt          = inputs.get("format", "chatml")
    train_split  = float(inputs.get("train_split", 0.9))

    # 1. Load
    data = load_dataset(dataset_uri)
    log.info(f"Loaded {len(data)} examples")

    # 2. Validate + convert to ChatML
    converted, skipped = [], 0
    for ex in data:
        result = to_chatml(ex, fmt)
        if result and result.get("messages"):
            converted.append(result)
        else:
            skipped += 1
    log.info(f"Converted {len(converted)} examples ({skipped} skipped)")

    # 3. Split
    split_idx   = int(len(converted) * train_split)
    train_data  = converted[:split_idx]
    eval_data   = converted[split_idx:]
    log.info(f"Split: {len(train_data)} train / {len(eval_data)} eval")

    # 4. Write JSONL
    train_path = io.local_path("train.jsonl")
    eval_path  = io.local_path("eval.jsonl")
    stats_path = io.local_path("stats.json")

    with open(train_path, "w") as f:
        for ex in train_data:
            f.write(json.dumps(ex) + "\n")

    with open(eval_path, "w") as f:
        for ex in eval_data:
            f.write(json.dumps(ex) + "\n")

    # 5. Compute stats
    msg_lengths = [len(json.dumps(ex)) for ex in converted]
    stats = {
        "total": len(converted),
        "train": len(train_data),
        "eval": len(eval_data),
        "skipped": skipped,
        "avg_length_chars": sum(msg_lengths) / len(msg_lengths) if msg_lengths else 0,
        "max_length_chars": max(msg_lengths) if msg_lengths else 0,
    }
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    log.info(f"Stats: {stats}")

    # 6. Upload outputs to R2
    io.write_output("train_jsonl", train_path, kind="dataset")
    io.write_output("eval_jsonl",  eval_path,  kind="dataset")
    io.write_output("stats_json",  stats_path, kind="metrics")

    log.info("data-prep complete")


if __name__ == "__main__":
    main()
