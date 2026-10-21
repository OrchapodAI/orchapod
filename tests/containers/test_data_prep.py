"""Unit tests for containers/data-prep/run.py (docs/contracts.md "Data nodes → data-prep")."""

import json
import sys
from collections import Counter
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from packages.workflow_schema.models import DataPrepInputs, DataPrepOutputs

from .conftest import load_container

dp = load_container("data-prep")

R2 = "r2://orchapod-artifacts/runs/r1/synth/dataset"
METRIC_KEYS = {"total", "train", "eval", "test", "skipped", "exact_dupes", "near_dupes",
               "quality_dropped", "avg_length_chars", "max_length_chars", "fields"}


def chat(q, a="An answer.", **extra):
    return {"messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}], **extra}


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def run_node(mock_orchapod_io, tmp_path, monkeypatch):
    """Run main() on `lines`, served from their own directory under the URI's last segment (as io.download_input
    names the file: extensionless for an r2 dataset); return ({output: rows}, metrics)."""
    monkeypatch.delenv("STUB", raising=False)
    src, out = tmp_path / "in", tmp_path / "out"
    src.mkdir(), out.mkdir()
    mock_orchapod_io.local_path.side_effect = lambda name: out / name
    mock_orchapod_io.download_input.side_effect = lambda uri: src / uri.rsplit("/", 1)[-1]

    def run(lines=(), **inputs):
        inputs = {"dataset": R2, **inputs}
        (src / (inputs["dataset"].rsplit("/", 1)[-1] or "unused")).write_text("\n".join(lines) + "\n", encoding="utf-8")
        mock_orchapod_io.write_output.reset_mock()
        mock_orchapod_io.write_metrics.reset_mock()
        mock_orchapod_io.read_inputs.return_value = inputs
        dp.main()
        calls = mock_orchapod_io.write_output.call_args_list
        assert all(c.kwargs == {"kind": "dataset"} for c in calls)
        (metrics,), _ = mock_orchapod_io.write_metrics.call_args
        return {c.args[0]: read_jsonl(c.args[1]) for c in calls}, metrics

    return run


# --- load ---------------------------------------------------------------------

def test_r2_uri_is_downloaded_and_read_as_extensionless_jsonl(mock_orchapod_io, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "datasets", None)  # any Hugging Face load would fail
    f = tmp_path / "dataset"
    f.write_text(json.dumps(chat("q1")) + "\n\n" + json.dumps(chat("q2")) + "\n")
    mock_orchapod_io.download_input.side_effect = lambda uri: f
    assert dp.load_rows(R2, "chatml") == [chat("q1"), chat("q2")]
    mock_orchapod_io.download_input.assert_called_once_with(R2)


def test_hf_dataset_gets_config_and_split(monkeypatch):
    fake = MagicMock(return_value=[{"question": "q", "answer": "a"}])
    monkeypatch.setitem(sys.modules, "datasets", SimpleNamespace(load_dataset=fake))
    monkeypatch.delenv("STUB", raising=False)
    assert dp.load_rows("hf://openai/gsm8k", "qa", "main", "test[:50]") == [{"question": "q", "answer": "a"}]
    fake.assert_called_once_with("openai/gsm8k", name="main", split="test[:50]")
    dp.load_rows("openai/gsm8k", "qa")
    fake.assert_called_with("openai/gsm8k", name=None, split="train")


def test_stub_replaces_hugging_face_with_fixed_rows(run_node, monkeypatch):
    monkeypatch.setitem(sys.modules, "datasets", None)
    inputs = {"dataset": "hf://openai/gsm8k", "hf_config": "main", "hf_split": "test[:50]", "format": "qa"}
    monkeypatch.setenv("STUB", "1")
    first = run_node(**inputs)
    assert run_node(**inputs) == first
    outs, metrics = first
    assert metrics["total"] == len(outs["dataset"]) > 0
    assert all(dp.tf_valid(r["messages"]) for r in outs["dataset"])


# --- convert and validate -----------------------------------------------------

def test_convert_formats():
    msgs = [{"role": "user", "content": "Q"}, {"role": "assistant", "content": "A"}]
    assert dp.convert({"question": "Q", "answer": "A", "source_url": "u"}, "qa") == {"messages": msgs, "source_url": "u"}
    assert dp.convert({"instruction": "Q", "input": "", "output": "A"}, "alpaca") == {"messages": msgs}
    turns = [{"from": "system", "value": "S"}, {"from": "human", "value": "Q"}, {"from": "gpt", "value": "A"}]
    assert dp.convert({"conversations": turns}, "sharegpt") == {"messages": [{"role": "system", "content": "S"}, *msgs]}
    assert dp.convert({"messages": msgs, "context": "c"}, "chatml") == {"messages": msgs, "context": "c"}
    assert dp.convert({"user_id": "u1", "n": None}, "structured") == {"user_id": "u1", "n": None}
    assert dp.convert(["not", "a", "dict"], "structured") is None
    assert dp.convert({"conversations": "oops"}, "sharegpt") is None
    assert dp.convert({"question": "Q"}, "qa") is None
    assert dp.convert({"messages": [{"role": ["user"], "content": "Q"}, msgs[1]]}, "chatml") is None  # unhashable


def test_csv_cells_stay_strings_and_a_ragged_row_is_skipped(run_node):
    lines = ["instruction,input,output", "Say hi,,Hi", "Spell it,NA,N-A", "Add 2 and 2,,4", "Ragged,row,has,4 cells"]
    outs, m = run_node(lines, dataset=f"{R2}.csv", format="alpaca")
    assert [[t["content"] for t in r["messages"]] for r in outs["dataset"]] == [
        ["Say hi", "Hi"], ["Spell it\nNA", "N-A"], ["Add 2 and 2", "4"]]  # blank, "NA" and a number stay text
    assert m["skipped"] == 1


U, A, S = ({"role": r, "content": "x"} for r in ("user", "assistant", "system"))


@pytest.mark.parametrize("msgs, ok", [
    ([U, A], True),
    ([S, U, A], True),
    ([U, A, U, A], True),
    ([U, S, A], False),                                   # system only first
    ([S, A], False),                                      # needs a user turn
    ([U, A, U], False),                                   # last turn is the assistant's
    ([U, {"role": "assistant", "content": " "}], False),  # non-empty content
    ([U, {"role": "assistant", "content": 3}], False),
    ([U, {"role": "tool", "content": "x"}], False),
    ([{"role": ["user"], "content": "x"}, A], False),     # an unhashable role is invalid, not a crash
    ([{"role": {"user": 1}, "content": "x"}, A], False),
    ([], False),
    ("not a list", False),
])
def test_tf_chat_rules(msgs, ok):
    assert bool(dp.tf_valid(msgs)) is ok


# --- dedupe and split ---------------------------------------------------------

def test_exact_then_near_dedupe(run_node):
    q = "Under the Fair Housing Act, which characteristics are protected from discrimination when selling or renting a home?"
    rows = [
        chat(q),
        chat(q),                                                                  # exact
        chat(q.replace("home?", "house?").replace("Fair Housing", "fair  housing"), "Other."),  # near (J≈0.95)
        chat("Under RESPA, how many business days before closing must the lender deliver the Closing Disclosure?"),
    ]
    outs, m = run_node([json.dumps(r) for r in rows])
    assert outs["dataset"] == [rows[0], rows[3]]
    assert (m["exact_dupes"], m["near_dupes"]) == (1, 1)


def test_split_is_deterministic_and_stratified_by_source():
    rows = [chat(f"q{s}-{i}", source_url=f"https://example.com/{s}") for s in range(20) for i in range(5)]
    train, ev, test = dp.split(rows, 0.8, 0.1)
    assert (train, ev, test) == dp.split(list(rows), 0.8, 0.1)
    assert (len(train), len(ev), len(test)) == (80, 10, 10)
    assert set(Counter(r["source_url"] for r in train).values()) == {4}  # every source keeps 4 of its 5 rows
    held_out = [{r["source_url"] for r in part} for part in (ev, test)]
    assert len(held_out[0] | held_out[1]) == 20 and not held_out[0] & held_out[1]  # its 5th: in eval or in test
    assert sorted(map(json.dumps, train + ev + test)) == sorted(map(json.dumps, rows))


@pytest.mark.parametrize("n, train, test, sizes", [
    (4, 0.8, 0.1, (3, 1, 0)),     # a requested test split can round to nothing
    (5, 0.9, 0.1, (4, 1, 0)),     # round() goes to even: 0.5 → 0
    (12, 0.8, 0.1, (10, 1, 1)),
    (20, 0.8, 0.1, (16, 2, 2)),
])
def test_small_inputs_can_leave_a_split_empty(n, train, test, sizes):
    rows = [chat(f"q{i}", source_url=f"https://example.com/{i % 3}") for i in range(n)]
    assert tuple(map(len, dp.split(rows, train, test))) == sizes


def test_one_row_sources_land_in_train():
    singles = [chat(f"s{i}", source_url=f"https://single.example/{i}") for i in range(10)]
    groups = [chat(f"g{s}-{i}", source_url=f"https://group.example/{s}") for s in range(4) for i in range(10)]
    train, ev, test = dp.split(singles + groups, 0.8, 0.1)
    assert (len(train), len(ev), len(test)) == (40, 5, 5) and all(r in train for r in singles)
    assert {r["source_url"] for r in ev + test} == {f"https://group.example/{s}" for s in range(4)}


# --- main ---------------------------------------------------------------------

def test_chat_outputs_and_metrics(run_node):
    rows = [chat(f"Question number {i} about RESPA disclosure timing rules?", f"Answer {i}.",
                 context=f"passage {i % 5}", source_url=f"https://example.com/{i % 5}") for i in range(20)]
    lines = [json.dumps(r) for r in rows] + [json.dumps(rows[0]), json.dumps({"messages": []}), "not json"]
    outs, m = run_node(lines, train_split=0.8, test_split=0.1)
    assert set(outs) == {"dataset", "train_jsonl", "eval_jsonl", "test_jsonl"}
    assert outs["dataset"] == rows
    assert all(set(r) == {"messages"} for r in outs["train_jsonl"] + outs["eval_jsonl"])
    assert all({"context", "source_url"} <= set(r) for r in outs["test_jsonl"])
    assert set(m) == METRIC_KEYS
    assert {k: m[k] for k in ("total", "train", "eval", "test", "skipped", "exact_dupes", "near_dupes",
                              "quality_dropped", "fields")} == {
        "total": 20, "train": 16, "eval": 2, "test": 2, "skipped": 2, "exact_dupes": 1, "near_dupes": 0,
        "quality_dropped": 0, "fields": None}
    assert 0 < m["avg_length_chars"] <= m["max_length_chars"]


def test_structured_rows_unchanged_with_field_stats(run_node):
    rows = [
        {"user_id": "u1", "action": "like", "timestamp": "2026-01-02T10:00:00Z", "watch_min": 12, "device": None},
        {"user_id": "u2", "action": "share", "timestamp": "2026-01-01T09:00:00Z", "watch_min": 3.5, "device": "tv"},
        {"user_id": "u3", "action": "like", "timestamp": "2026-01-03T08:00:00+00:00", "watch_min": 40, "device": "tv"},
        {"user_id": "u4", "action": "like", "timestamp": "2026-01-03T08:00:00+00:00", "watch_min": 40, "device": "tv"},
    ]
    outs, m = run_node([json.dumps(r) for r in rows + rows[:1]], format="structured")
    assert outs["dataset"] == rows
    assert sorted(map(json.dumps, outs["train_jsonl"] + outs["eval_jsonl"])) == sorted(map(json.dumps, rows))
    assert (m["exact_dupes"], m["near_dupes"]) == (1, 0)  # u3/u4 differ only in user_id: kept
    f = m["fields"]
    assert json.loads(json.dumps(m)) == m
    assert f["action"] == {"distinct": 2, "nulls": 0, "top": [["like", 3], ["share", 1]]}
    assert f["device"] == {"distinct": 1, "nulls": 1, "top": [["tv", 3]]}
    assert (f["watch_min"]["min"], f["watch_min"]["max"]) == (3.5, 40)
    assert (f["timestamp"]["min"], f["timestamp"]["max"]) == ("2026-01-01T09:00:00Z", "2026-01-03T08:00:00+00:00")
    assert "min" not in f["user_id"]


def test_counts_are_logged_before_near_dedupe(run_node, monkeypatch):
    logged = []
    monkeypatch.setattr(dp, "near_dedupe", lambda rows: logged.append(dp.log.info.call_args.args[0]) or rows)
    run_node([json.dumps(chat("q1")), json.dumps(chat("q1")), json.dumps(chat("q2")), "not json"])
    assert logged == ["4 rows loaded, 2 valid and distinct"]  # near dedupe can take minutes on large inputs


def test_an_empty_requested_test_split_is_warned(run_node):
    outs, _ = run_node([json.dumps(chat(f"Question {i} about escrow?")) for i in range(5)], test_split=0.1)
    assert outs["test_jsonl"] == []
    assert "test_jsonl is empty" in dp.log.warn.call_args.args[0]


@pytest.mark.parametrize("lines, inputs", [
    ([json.dumps({"messages": [{"role": "user", "content": "q"}]}), "not json"], {}),  # nothing survives cleaning
    ([json.dumps(chat("q"))], {"format": "csv"}),                                       # unknown format
    ([json.dumps(chat("q"))], {"dataset": ""}),                                         # no dataset
])
def test_fatal_errors_exit_1(run_node, mock_orchapod_io, lines, inputs):
    with pytest.raises(SystemExit) as e:
        run_node(lines, **inputs)
    assert e.value.code == 1
    dp.log.error.assert_called_once()
    mock_orchapod_io.write_output.assert_not_called()


# --- schema -------------------------------------------------------------------

def test_inputs_and_outputs_schema():
    i = DataPrepInputs(dataset="hf://openai/gsm8k", hf_config="main", hf_split="test[:50]", format="qa")
    assert (i.train_split, i.test_split, i.hf_split) == (0.9, 0.0, "test[:50]")
    DataPrepInputs(dataset="x", format="structured", train_split=0.8, test_split=0.2)
    with pytest.raises(ValidationError):
        DataPrepInputs(dataset="x", train_split=0.9, test_split=0.2)
    assert set(DataPrepOutputs.model_fields) == {"dataset", "train_jsonl", "eval_jsonl", "test_jsonl"}
