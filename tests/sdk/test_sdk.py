"""Node SDK (packages/sdk-py/orchapod) per contracts "Node SDK": cost, outputs, metrics, logs, exit hooks."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
import urllib.request
from pathlib import Path

import pytest

SDK = Path(__file__).resolve().parents[2] / "packages" / "sdk-py"


@pytest.fixture
def sdk(monkeypatch):
    """The real SDK, freshly imported: tests/containers/test_unsloth_train.py leaves fakes in sys.modules."""
    for name in [m for m in sys.modules if m.split(".")[0] == "orchapod"]:
        monkeypatch.delitem(sys.modules, name)
    import orchapod
    return orchapod


@pytest.fixture
def node_env(sdk, monkeypatch, tmp_path):
    for k, v in {
        "ORCHAPOD_RUN_ID": "run1", "ORCHAPOD_NODE_ID": "prep", "ORCHAPOD_R2_BUCKET": "my-bucket",
        "ORCHAPOD_CONTROL_URL": "http://cp", "ORCHAPOD_INTERNAL_SECRET": "s3cret",
        "ORCHAPOD_NODE_OUTPUTS_DIR": str(tmp_path),
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("STUB", raising=False)
    monkeypatch.delenv("ORCHAPOD_MAX_COST_USD", raising=False)
    return tmp_path


@pytest.fixture
def posts(monkeypatch):
    """Every request the SDK sends to the control plane, answered 200."""
    sent = []

    def fake_urlopen(req, timeout=None):
        sent.append({"url": req.full_url, "secret": req.get_header("X-orchapod-secret"), "body": json.loads(req.data)})
        return contextlib.nullcontext()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return sent


def test_cost_add_aggregates_prices_and_caps(sdk, node_env, monkeypatch):
    cost = sdk.cost
    monkeypatch.setattr(cost, "PRICES", {
        "token_factory": {"m": {"in": 1.0, "out": 2.0}},
        "tavily": {"credit": 0.008},
        "nebius_serverless": {"gpu-h100-sxm": 4.5},
    })
    cost.add("token_factory", "m", 1_000_000, 500_000)       # priced from PRICES: 1.0 + 1.0
    cost.add("token_factory", "m", 0, 0, usd=0.5, calls=2)   # clients pass usd explicitly
    cost.add("tavily", "search", credits=2)                   # 0.016
    cost.add("nebius_serverless", "gpu-h100-sxm/1gpu-16vcpu-200gb", gpu_hours=0.5)  # 2.25
    s = cost.summary()
    tf, tavily, gpu = s["items"]
    assert (tf["calls"], tf["in_tokens"], tf["out_tokens"], tf["usd"]) == (3, 1_000_000, 500_000, 2.5)
    assert (tavily["credits"], gpu["gpu_hours"]) == (2, 0.5)
    assert s["usd"] == pytest.approx(4.766)

    with pytest.raises(LookupError):  # unpriced calls fail closed (R5)
        cost.add("token_factory", "unpriced/model", 10, 10)

    monkeypatch.setenv("ORCHAPOD_MAX_COST_USD", "5")
    with pytest.raises(cost.BudgetExceeded):
        cost.add("token_factory", "m", usd=0.3)


def test_write_output_validates_name_and_uses_bucket(sdk, node_env, posts, monkeypatch):
    io = sdk.io
    uploads = []
    monkeypatch.setattr(io, "_upload_to_r2", lambda local_path, r2_key: uploads.append(r2_key))
    for bad in ("corpus.jsonl", "Train", "1x", "ok\n", "logs"):  # logs: the SDK's own, written at exit
        with pytest.raises(ValueError):
            io.write_output(bad, node_env, "dataset")
    assert uploads == [] and posts == []

    uri = io.write_output("train_jsonl", node_env, "dataset", {"rows": 3})
    assert uri == "r2://my-bucket/runs/run1/prep/train_jsonl"
    assert uploads == ["runs/run1/prep/train_jsonl"]
    assert posts == [{
        "url": "http://cp/internal/artifact", "secret": "s3cret",
        "body": {"run_id": "run1", "node_id": "prep",
                 "artifact": {"name": "train_jsonl", "uri": uri, "kind": "dataset", "metadata": {"rows": 3}}},
    }]


def test_the_log_buffer_keeps_the_last_lines(sdk):
    log = sdk.log
    for i in range(log.lines.maxlen + 1):  # a long training job logs progress lines for an hour
        log.info(f"line {i}")
    assert len(log.lines) == log.lines.maxlen and log.lines[0]["message"] == "line 1"


def test_output_registration_retries_then_raises(sdk, node_env, monkeypatch):
    io, log = sdk.io, sdk.log
    monkeypatch.setattr(io, "_upload_to_r2", lambda **_: None)
    sleeps, calls = [], []
    monkeypatch.setattr(io.time, "sleep", sleeps.append)

    def flaky(path, payload, timeout=3):
        calls.append(path)
        if len(calls) < 4:
            raise OSError("control plane down")

    monkeypatch.setattr(log, "post", flaky)
    io.write_output("job", node_env, "metrics")
    assert (len(calls), sleeps) == (4, [1, 2, 4])

    def down(path, payload, timeout=3):
        raise OSError("control plane down")

    sleeps.clear()
    monkeypatch.setattr(log, "post", down)
    with pytest.raises(OSError):
        io.write_output("job", node_env, "metrics")
    assert sleeps == [1, 2, 4]


def test_log_and_progress_post_with_secret_and_never_raise(sdk, node_env, posts, monkeypatch):
    log = sdk.log
    log.info("hello")
    log.progress(3, 10, loss=0.5, extra={"phase": "running"})
    assert [p["url"] for p in posts] == ["http://cp/internal/log", "http://cp/internal/progress"]
    assert {p["secret"] for p in posts} == {"s3cret"}
    assert (posts[0]["body"]["level"], posts[0]["body"]["message"]) == ("INFO", "hello")
    assert posts[1]["body"] == {"run_id": "run1", "node_id": "prep", "step": 3, "total": 10,
                                "loss": 0.5, "extra": {"phase": "running"}}

    def down(*a, **k):
        raise OSError("control plane down")

    monkeypatch.setattr(urllib.request, "urlopen", down)
    log.error("still fine")
    log.progress(4, 10)


def test_write_metrics_fills_stub_and_truncates_metadata(sdk, node_env, monkeypatch):
    io = sdk.io
    out = []
    monkeypatch.setattr(io, "write_output", lambda name, path, kind, metadata=None:
                        out.append((name, json.loads(Path(path).read_text()), kind, metadata)))
    monkeypatch.setenv("STUB", "1")
    io.write_metrics({"rows": 5})
    assert out[0] == ("metrics_json", {"stub": True, "rows": 5}, "metrics", {"stub": True, "rows": 5})

    io.write_metrics({"blob": "x" * 20_000})  # > 16 KB: the file keeps everything
    assert out[1][3] == {"truncated": True} and len(out[1][1]["blob"]) == 20_000


# A node process: object storage and webhooks are captured into files under argv[2].
_NODE = textwrap.dedent("""
    import concurrent.futures, json, os, shutil, signal, sys, time
    from pathlib import Path
    from orchapod import cost, io, log
    cap = Path(sys.argv[2])

    class S3:  # boto3's upload_file runs on a thread pool (s3transfer), which is refused at interpreter exit
        def upload_file(self, filename, bucket, key):
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                pool.submit(shutil.copy, filename, cap / key.rsplit("/", 1)[1]).result()

        def put_object(self, Bucket, Key, Body):
            (cap / Key.rsplit("/", 1)[1]).write_bytes(Body.read())

    io._get_r2_client = S3
    log.post = lambda path, payload, timeout=3: open(cap / "posts.jsonl", "a").write(json.dumps([path, payload]) + "\\n")
    io.read_inputs()
    log.info("started")
    cost.add("token_factory", "m", 10, 20, usd=0.25)
    try:
        if sys.argv[1] == "raise":
            raise RuntimeError("boom")
        if sys.argv[1] == "sigterm":
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(10)
        if sys.argv[1] == "busy_pool":  # main returns while a worker is still in a slow call
            concurrent.futures.ThreadPoolExecutor(1).submit(time.sleep, 60)
        if sys.argv[1] == "pool_spends":  # a call still in flight when main returns bills after it
            concurrent.futures.ThreadPoolExecutor(1).submit(lambda: time.sleep(0.5) or cost.add("token_factory", "m", usd=0.5))
        if sys.argv[1] == "sigterm_in_pool":  # a cancel while the node's `with` block waits for its worker
            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                pool.submit(time.sleep, 60)
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(10)
    finally:
        (cap / "finally").write_text("ran")
""")


def node(mode: str, tmp_path: Path) -> list[str]:
    """The command of a node process in `mode`, and its env (the SDK only; object storage and webhooks are files)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORCHAPOD_", "STUB"))}
    env.update(PYTHONPATH=str(SDK), ORCHAPOD_NODE_INPUTS="{}", ORCHAPOD_RUN_ID="run1", ORCHAPOD_NODE_ID="prep",
               ORCHAPOD_R2_BUCKET="b", ORCHAPOD_NODE_OUTPUTS_DIR=str(tmp_path / "out"))
    return dict(args=[sys.executable, "-c", _NODE, mode, str(tmp_path)], env=env, cwd=tmp_path, text=True)


def registered(tmp_path: Path, name: str) -> list[dict]:
    """The metadata of each `name` artifact the node has registered so far (complete lines only: it may be writing)."""
    path = tmp_path / "posts.jsonl"
    posts = [json.loads(line) for line in path.read_text().split("\n")[:-1]] if path.exists() else []
    return [p[1]["artifact"]["metadata"] for p in posts if p[0] == "/internal/artifact" and p[1]["artifact"]["name"] == name]


def wait_for_cost_json(tmp_path: Path, proc: subprocess.Popen) -> None:
    deadline = time.monotonic() + 20
    while not registered(tmp_path, "cost_json"):
        assert proc.poll() is None and time.monotonic() < deadline, "no cost_json while the node was still running"
        time.sleep(0.05)


@pytest.mark.parametrize("mode, code", [("ok", 0), ("raise", 1), ("sigterm", 143)])
def test_cost_json_written_at_every_exit(tmp_path, mode, code):
    proc = subprocess.run(**node(mode, tmp_path), capture_output=True, timeout=60)
    assert proc.returncode == code, proc.stderr

    assert json.loads((tmp_path / "cost_json").read_text())["usd"] == 0.25
    posts = [json.loads(line) for line in (tmp_path / "posts.jsonl").read_text().splitlines()]
    assert ["/internal/artifact", {"artifact": {"name": "cost_json", "uri": "r2://b/runs/run1/prep/cost_json",
                                                "kind": "metrics", "metadata": {"usd": 0.25}}}] in posts
    assert (tmp_path / "finally").exists()  # SIGTERM unwinds the node's finally (remote cleanup)
    errors = [p[1]["message"] for p in posts if p[0] == "/internal/log" and p[1]["level"] == "ERROR"]
    assert errors == (["RuntimeError: boom"] if mode == "raise" else [])
    # the node's log lines outlive the live stream: a finished run (and the golden-run fixture) keeps them
    assert ["/internal/artifact", {"artifact": {"name": "logs", "uri": "r2://b/runs/run1/prep/logs",
                                                "kind": "log", "metadata": {}}}] in posts
    lines = [json.loads(line) for line in (tmp_path / "logs").read_text().splitlines()]
    assert [(x["level"], x["message"]) for x in lines] == [("INFO", "started")] + [("ERROR", m) for m in errors]
    assert all(x["ts"] for x in lines)


def test_cost_json_does_not_wait_for_a_pool_still_busy_at_exit(tmp_path):
    """Main returns while a worker is still in a slow (paid) call: the interpreter joins that worker before atexit, so
    cost_json goes out first; then a SIGTERM (cancel, timeout) ends the wait at once, and `logs` are written too."""
    proc = subprocess.Popen(**node("busy_pool", tmp_path))
    try:
        wait_for_cost_json(tmp_path, proc)  # the worker still has most of its 60 s to go
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
    finally:
        proc.kill()
    assert registered(tmp_path, "cost_json") == [{"usd": 0.25}]  # once: nothing was spent after
    assert registered(tmp_path, "logs") == [{}]


def test_cost_json_is_written_at_sigterm_while_the_node_still_waits_for_its_pool(tmp_path):
    """A cancel while the node's own cleanup waits for its worker (ThreadPoolExecutor's `with`): past the 30 s grace
    SIGKILL ends the node before any exit hook, so the spend goes out from the SIGTERM handler."""
    proc = subprocess.Popen(**node("sigterm_in_pool", tmp_path))
    try:
        wait_for_cost_json(tmp_path, proc)
    finally:
        proc.kill()  # docker stop: SIGKILL after the grace
    assert registered(tmp_path, "cost_json") == [{"usd": 0.25}]


def test_what_calls_in_flight_at_exit_spend_is_added_after_them(tmp_path):
    proc = subprocess.run(**node("pool_spends", tmp_path), capture_output=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    # each cost_json adds its usd to the run: when main ended, then what the worker billed after
    assert registered(tmp_path, "cost_json") == [{"usd": 0.25}, {"usd": 0.5}]
    assert json.loads((tmp_path / "cost_json").read_text())["usd"] == 0.75  # the file: the node's whole spend


def test_each_cost_record_registers_its_own_spend(sdk, node_env, posts, monkeypatch):
    """Several nodes in one process (tests/drills runs them so, each with a fresh cost record): each cost_json carries
    its own node's spend, never the difference from the node before."""
    io, cost = sdk.io, sdk.cost
    monkeypatch.setattr(io, "_upload_to_r2", lambda **_: None)
    for usd in (0.25, 0.1, 0.0):
        monkeypatch.setattr(cost, "_items", {})
        if usd:
            cost.add("token_factory", "m", usd=usd)
        io._at_exit()
    assert [p["body"]["artifact"]["metadata"] for p in posts if p["body"].get("artifact", {}).get("name") == "cost_json"
            ] == [{"usd": 0.25}, {"usd": 0.1}, {"usd": 0.0}]
