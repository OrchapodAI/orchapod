"""
containers/data-prep/run.py — node data-prep (cpu). Contract: docs/contracts.md "Data nodes → data-prep".

load (r2:// JSONL or CSV, hf://<id> or <org>/<name>) → convert + validate → exact dedupe → near dedupe (chat)
→ deterministic split (seed 42, stratified by source_url) → outputs dataset, train_jsonl, eval_jsonl, test_jsonl
(always written) + io.write_metrics. STUB=1 swaps Hugging Face loads for fixed rows, so no network.
"""

import csv
import json
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from orchapod import io, log

FORMATS = ("chatml", "alpaca", "sharegpt", "qa", "structured")
ROLES = {"system", "user", "assistant"}
SHAREGPT_ROLES = {"human": "user", "user": "user", "system": "system"}  # gpt and the rest → assistant
NEAR = 0.9  # char 5-gram Jaccard on the normalised first user turn
SEED = 42


def dumps(obj, **kw) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str, **kw)


def fail(reason: str):
    log.error(reason)
    sys.exit(1)


def load_rows(uri: str, fmt: str, hf_config: str | None = None, hf_split: str = "train") -> list:
    if uri.startswith("r2://"):
        return read_file(io.download_input(uri))
    if uri.startswith("hf://") or ("/" in uri and not uri.startswith("/")):
        repo = uri.removeprefix("hf://")
        if os.environ.get("STUB") == "1":
            return stub_rows(fmt)
        from datasets import load_dataset
        log.info(f"Loading Hugging Face dataset {repo} (config={hf_config}, split={hf_split})")
        return list(load_dataset(repo, name=hf_config, split=hf_split))
    return read_file(Path(uri))


def read_file(path: Path) -> list:
    if path.name.endswith(".csv"):  # every cell stays text ("", "NA", "4"); a row with extra cells is skipped
        with open(path, encoding="utf-8-sig", newline="") as f:
            return [None if None in r else r for r in csv.DictReader(f)]
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for line in filter(str.strip, f):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                rows.append(None)  # counted as skipped
    return rows


def stub_rows(fmt: str) -> list[dict]:
    rows = []
    for i in range(20):
        q, a = f"Stub question {i}: what is {i} plus {i * 7}?", f"{i} plus {i * 7} is {i * 8}."
        rows.append({
            "chatml": {"messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}]},
            "alpaca": {"instruction": q, "input": "", "output": a},
            "sharegpt": {"conversations": [{"from": "human", "value": q}, {"from": "gpt", "value": a}]},
        }.get(fmt, {"question": q, "answer": a}))
    return rows


def tf_valid(msgs) -> bool:
    """Token Factory chat rules: roles in ROLES, system only first, a user turn, last turn assistant, no empty content."""
    return (
        isinstance(msgs, list) and len(msgs) > 0
        and all(isinstance(m, dict) and isinstance(m.get("role"), str) and m["role"] in ROLES
                and isinstance(m.get("content"), str) and m["content"].strip() != "" for m in msgs)
        and all(m["role"] != "system" for m in msgs[1:])
        and any(m["role"] == "user" for m in msgs)
        and msgs[-1]["role"] == "assistant"
    )


def convert(row, fmt: str) -> dict | None:
    """A cleaned row, or None for a bad one. Chat formats → {"messages": [...], **other keys}; structured as is."""
    if not isinstance(row, dict):
        return None
    if fmt == "structured":
        return row
    rest = dict(row)
    msgs = rest.pop("messages", None)
    try:
        if fmt == "alpaca":
            prompt = "\n".join(s for s in (rest.pop("instruction", None), rest.pop("input", None)) if s)
            msgs = [{"role": "user", "content": prompt}, {"role": "assistant", "content": rest.pop("output", None)}]
        elif fmt == "sharegpt":
            msgs = [{"role": SHAREGPT_ROLES.get(t.get("from"), "assistant"), "content": t.get("value")}
                    for t in rest.pop("conversations", None) or []]
        elif fmt == "qa":
            msgs = [{"role": "user", "content": rest.pop("question", None)},
                    {"role": "assistant", "content": rest.pop("answer", None)}]
    except (AttributeError, TypeError):  # malformed turns
        return None
    return {"messages": msgs, **rest} if tf_valid(msgs) else None


def grams(text: str) -> set[str]:
    s = " ".join(text.lower().split())
    return {s[i:i + 5] for i in range(max(1, len(s) - 4))}


def near_dedupe(rows: list[dict]) -> list[dict]:
    kept, kept_grams = [], []
    for r in rows:
        g = grams(next(m["content"] for m in r["messages"] if m["role"] == "user"))
        # ponytail: O(n²) over kept rows: 1k rows 1 s, 15k rows ~2.5 min; prefix filtering or MinHash LSH if inputs grow
        if not any((i := len(g & k)) >= NEAR * (len(g) + len(k) - i)
                   for k in kept_grams if NEAR * len(k) <= len(g) <= len(k) / NEAR):
            kept.append(r)
            kept_grams.append(g)
    return kept


def split(rows: list[dict], train: float, test: float) -> tuple[list, list, list]:
    """Seed-42 split stratified by source_url: each source's shuffled rows spread evenly over one order, cut
    train|eval|test at round(n × share). Counts always add up to n, but small n can leave a split empty (n=5 at
    0.9/0.1 → 4/1/0), and only a source with about 1/share rows or more reaches eval and test: a one-row source
    sits mid-order, so it lands in train."""
    rng = random.Random(SEED)
    groups = defaultdict(list)
    for r in rows:
        groups[str(r.get("source_url", ""))].append(r)
    keyed = []
    for g in groups.values():
        rng.shuffle(g)
        keyed += [((i + 0.5) / len(g), rng.random(), r) for i, r in enumerate(g)]
    ordered = [r for *_, r in sorted(keyed, key=lambda x: x[:2])]
    n = len(ordered)
    n_train = round(n * train)
    n_test = min(round(n * test), n - n_train)
    return ordered[:n_train], ordered[n_train:n - n_test], ordered[n - n_test:]


def _iso(v):
    try:
        d = datetime.fromisoformat(v)
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def field_stats(rows: list[dict]) -> dict:
    stats = {}
    for f in dict.fromkeys(k for r in rows for k in r):
        present = [r[f] for r in rows if r.get(f) is not None]
        counts = Counter(v if isinstance(v, str | int | float) else dumps(v, sort_keys=True) for v in present)
        s = {"distinct": len(counts), "nulls": len(rows) - len(present),
             "top": [[v, c] for v, c in counts.most_common(10)]}
        if present and all(type(v) in (int, float) for v in present):
            s |= {"min": min(present), "max": max(present)}
        elif present and all(map(_iso, present)):
            s |= {"min": min(present, key=_iso), "max": max(present, key=_iso)}
        stats[f] = s
    return stats


def write_jsonl(name: str, rows: list) -> None:
    path = io.local_path(name)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(dumps(r) + "\n" for r in rows)
    io.write_output(name, path, kind="dataset")


def main():
    inputs = io.read_inputs()
    fmt = inputs.get("format") or "chatml"
    if fmt not in FORMATS:
        fail(f"unknown format {fmt!r}: use one of {', '.join(FORMATS)}")
    if not inputs.get("dataset"):
        fail("input dataset is required")

    raw = load_rows(inputs["dataset"], fmt, inputs.get("hf_config") or None, inputs.get("hf_split") or "train")
    converted = [c for c in (convert(r, fmt) for r in raw) if c is not None]
    unique = list({dumps(r, sort_keys=True): r for r in converted}.values())  # exact dupes: canonical JSON
    log.info(f"{len(raw)} rows loaded, {len(unique)} valid and distinct")  # first: near dedupe can take minutes
    rows = unique if fmt == "structured" else near_dedupe(unique)
    if not rows:
        fail(f"0 rows after cleaning {inputs['dataset']} as {fmt}")

    test_share = float(inputs.get("test_split") or 0)
    train, ev, test = split(rows, float(inputs.get("train_split") or 0.9), test_share)
    if test_share and not test:
        log.warn(f"test_jsonl is empty: test_split {test_share} of {len(rows)} rows rounds to 0")
    write_jsonl("dataset", rows)
    write_jsonl("test_jsonl", test)
    if fmt != "structured":  # training files carry only the turns
        train, ev = ([{"messages": r["messages"]} for r in part] for part in (train, ev))
    write_jsonl("train_jsonl", train)
    write_jsonl("eval_jsonl", ev)

    lengths = [len(dumps(r)) for r in rows]
    io.write_metrics({
        "total": len(rows), "train": len(train), "eval": len(ev), "test": len(test),
        "skipped": len(raw) - len(converted), "exact_dupes": len(converted) - len(unique),
        "near_dupes": len(unique) - len(rows), "quality_dropped": 0,  # quality_filter lands in wave 2
        "avg_length_chars": sum(lengths) / len(lengths), "max_length_chars": max(lengths),
        "fields": field_stats(rows) if fmt == "structured" else None,
    })
    log.info(f"data-prep complete: {len(train)} train / {len(ev)} eval / {len(test)} test")


if __name__ == "__main__":
    main()
