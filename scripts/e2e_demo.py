"""Stub e2e of intent #2 (synthetic movie events), through the API only: no paid call, $0.

    python scripts/e2e_demo.py --stub     # `make check E2E=1` runs it; needs Docker and `make up` (Redis, MinIO)

It rebuilds and retags the shared `orchapod/<node>:dev` images, so parallel worktrees must not run it: it is opt-in.

It starts its own API (STUB=1, throwaway SQLite DB, first free port from 8003, no paid key in its env; on Linux it listens
on E2E_BIND_HOST, because the node containers reach it through the docker0 gateway, see bind_host), builds the images
the plan needs (`orchapod/<node>:dev`), creates the workflow from GET /agent/templates, runs it and polls
GET /runs/{id}/summary. Asserted: the run succeeded in under 5 minutes; data-prep registered dataset, train_jsonl and
eval_jsonl; cost_usd is 0 with a cost_json on every node; the dataset's download link serves rows with exactly the
schema's fields. e2e_agent.py (the three canonical intents) and e2e_ui.py (the Playwright smoke) reuse its stack, checks
and image builds. The real golden run (--max-cost) is written on D3.
"""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
LIMIT_S = 300  # a stub run must end within 5 minutes
TERMINAL = ("succeeded", "failed", "cancelled")
# What each node type must register, by contract (docs/contracts.md "Data nodes", "ML nodes"); the SDK adds cost_json to all.
MUST_REGISTER = {
    "web-research": ("corpus",), "synth-distilabel": ("dataset",), "data-prep": ("dataset", "train_jsonl", "eval_jsonl"),
    "tf-finetune": ("job", "lora_adapter"), "vllm-serve": ("model_ref",), "judge-eval": ("eval_summary",),
    "hf-download": ("hf_model",), "quantize": ("gguf_file",),
}
# A stub run can spend nothing: none of these reaches the API, and through it a node.
PAID = ("VASTAI_API_KEY", "RUNPOD_API_KEY", "NEBIUS_API_KEY", "NEBIUS_IAM_TOKEN", "NEBIUS_PROJECT_ID",
        "ORCHAPOD_ENDPOINT_TOKEN", "TAVILY_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HF_TOKEN")
# The compose stack (`make up`): a stub run touches nothing else, whatever the shell exports.
LOCAL_STACK = {
    "REDIS_URL": "redis://localhost:6379", "ORCHAPOD_R2_ENDPOINT": "http://localhost:9000", "ORCHAPOD_R2_REGION": "auto",
    "ORCHAPOD_R2_ACCESS_KEY": "orchapod", "ORCHAPOD_R2_SECRET_KEY": "orchapod_dev", "ORCHAPOD_R2_BUCKET": "orchapod-artifacts",
}


def say(msg: str) -> None:
    print(f"e2e: {msg}", flush=True)


def fail(msg) -> int:
    print(f"e2e FAIL: {msg}", flush=True)
    return 1


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/e2e)
# ---------------------------------------------------------------------------

def api_env(port: int, db: Path, environ, extra: dict[str, str | None] | None = None) -> dict[str, str]:
    """The API's env: STUB=1, no paid key, the compose stack, its own DB and port, the kill switch off. `extra` lands last:
    budget knobs such as ORCHAPOD_ANON_SCALE, and for a real run (e2e_agent.py --max-cost) the few keys it forwards; a None
    in it removes the name, which is how a real run drops STUB."""
    env = {k: v for k, v in environ.items() if k not in PAID}
    env |= LOCAL_STACK | {
        "STUB": "1",
        "ORCHAPOD_KILL_SWITCH": "0",
        "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
        "ORCHAPOD_CONTROL_URL": f"http://127.0.0.1:{port}",  # LocalDocker rewrites it to host.docker.internal
        "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "apps"), str(ROOT / "packages/sdk-py")]),
    } | (extra or {})
    return {k: v for k, v in env.items() if v is not None}


def bind_host() -> str:
    """Where the API listens: E2E_BIND_HOST, else 127.0.0.1. A node container reaches it as host.docker.internal: Docker
    Desktop (macOS, Windows) forwards that name to the host's 127.0.0.1, but on Linux it is the docker0 gateway (LocalDocker's
    --add-host ...:host-gateway), which a 127.0.0.1 listener never answers. There set E2E_BIND_HOST to docker0's gateway
    (`docker network inspect bridge -f '{{(index .IPAM.Config 0).Gateway}}'`, usually 172.17.0.1), on a throwaway host only,
    and for a stub run only: the key-less STUB API takes runs from anyone who reaches it, whereas the API of e2e_agent.py's real
    run holds a key, so that run refuses when E2E_BIND_HOST is set and stays on 127.0.0.1 (so it needs Docker Desktop). A
    firewall that drops docker0 traffic needs a rule for ports 8003-8052 (preflight says so; never the hosted VM,
    docs/HOSTING.md)."""
    return os.environ.get("E2E_BIND_HOST") or "127.0.0.1"


def listen_on_free_port(start: int = 8003, host: str = "127.0.0.1") -> socket.socket:
    """A listening socket on `host` on the first free port from `start` (8000 and 8001 belong to other projects on this Mac, and
    8002 is the dev API, which a stub run must never mistake for its own). The API gets this very socket, so no other process
    can take the port in between."""
    for port in range(start, start + 50):
        sock = socket.socket()
        try:
            sock.bind((host, port))
        except OSError:
            sock.close()
            continue
        sock.listen()
        return sock
    raise RuntimeError(f"no free port in {start}..{start + 49}")


def plan_of(template: dict) -> dict:
    return template.get("plan") or template  # a template file may hold the bare plan


def synth_inputs(plan: dict) -> dict | None:
    return next((n.get("inputs") or {} for n in plan.get("nodes", []) if n.get("type") == "synth-distilabel"), None)


def find_intent2(templates: list[dict]) -> dict | None:
    """The template whose plan has a synth-distilabel node in structured mode."""
    return next((t for t in templates if (synth_inputs(plan_of(t)) or {}).get("pipeline_template") == "structured"), None)


def plan_yaml(plan: dict) -> str:
    return yaml.safe_dump(plan, sort_keys=False)  # contracts "Agent API": running a plan = safe_dump(plan) -> Workflow -> Run


def check_run(summary: dict, max_cost: float | None = None) -> list[str]:
    """What is wrong with a finished run (a summary, or an agent report, which holds the same fields); empty = fine. A STUB
    run (max_cost None) costs $0; a real one more than $0 (one that cost nothing called nothing) and at most max_cost, and no
    node less than $0."""
    nodes, artifacts = summary["nodes"], summary["artifacts"]
    if summary["status"] != "succeeded":
        def state(x):
            return x["status"] + (f": {x['error']}" if x["error"] else "")

        return [f"run {state(summary)}"] + [f"node {n['node_id']} {state(n)}" for n in nodes if n["status"] != "succeeded"]
    made = {n["node_id"]: {a["name"] for a in artifacts if a["node_id"] == n["node_id"]} for n in nodes}
    problems = [] if any(n["type"] == "data-prep" for n in nodes) else ["the run has no data-prep node"]
    for n in nodes:  # on the node's own id: synth and data-prep both register a `dataset`
        if absent := [name for name in MUST_REGISTER.get(n["type"], ()) if name not in made[n["node_id"]]]:
            problems.append(f"{n['type']} {n['node_id']!r} did not register {', '.join(absent)}")
    cost = summary["cost_usd"]
    if max_cost is None and cost != 0:
        problems.append(f"cost_usd is {cost}, expected 0 in STUB")
    elif max_cost is not None and not 0 < cost <= max_cost:
        problems.append(f"cost_usd ${cost} is over --max-cost ${max_cost:g}" if cost > max_cost
                        else f"cost_usd is {cost}: a real run that cost $0 called nothing")
    for n in nodes:
        if (n["usd"] != 0) if max_cost is None else (n["usd"] < 0):
            problems.append(f"node {n['node_id']!r} reports usd {n['usd']}, expected {'0 in STUB' if max_cost is None else 'at least 0'}")
        if "cost_json" not in made[n["node_id"]]:
            problems.append(f"node {n['node_id']!r} wrote no cost_json, so its {'$0' if max_cost is None else 'cost'} was never measured")
    return problems


def check_rows(text: str, row_schema: dict | str | None) -> list[str]:
    """Problems with a downloaded JSONL: no rows, a line that is no JSON object, fields other than the schema's."""
    schema = json.loads(row_schema) if isinstance(row_schema, str) else row_schema or {}
    props, required = set(schema.get("properties", {})), set(schema.get("required", []))
    lines = [ln for ln in text.splitlines() if ln.strip()]
    problems = [] if lines else ["the downloaded dataset has no rows"]
    for i, line in enumerate(lines, 1):
        try:
            row = json.loads(line)
        except ValueError:
            problems.append(f"row {i} is not JSON: {line[:60]!r}")
            continue
        if not isinstance(row, dict):
            problems.append(f"row {i} is not an object")
            continue
        missing, extra = required - set(row), (set(row) - props if props else set())
        if missing or extra:
            problems.append(f"row {i}: missing {sorted(missing)}, unexpected {sorted(extra)}")
    return problems[:5]


# ---------------------------------------------------------------------------
# Stack: API process, preflight, images
# ---------------------------------------------------------------------------

def tail(path: Path, n: int = 15) -> str:
    return "\n".join(path.read_text(errors="replace").splitlines()[-n:])


def start_api(tmp: Path, extra: dict[str, str | None] | None = None) -> tuple[subprocess.Popen, str]:
    """The API on its own port and database; the URL is 127.0.0.1 whichever address it listens on (bind_host)."""
    with listen_on_free_port(host=bind_host()) as sock:
        port = sock.getsockname()[1]
        with open(tmp / "api.log", "w") as log:
            proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.main:app", "--fd", str(sock.fileno())], cwd=ROOT,
                                    env=api_env(port, tmp / "e2e.db", os.environ, extra), stdout=log, stderr=subprocess.STDOUT,
                                    pass_fds=[sock.fileno()])
    return proc, f"http://127.0.0.1:{port}"


def wait_healthy(proc: subprocess.Popen, base: str, log: Path, path: str = "/health", tries: int = 120) -> None:
    """Wait (tries x 0.5 s) for GET base+path to answer 200 while `proc` lives; the API's /health, or a page of the web app."""
    for _ in range(tries):
        if proc.poll() is not None:
            break
        try:
            if httpx.get(f"{base}{path}", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"{base}{path} did not answer 200 ({'the process exited' if proc.poll() is not None else 'too slow'}):\n{tail(log)}")


def stop(proc: subprocess.Popen) -> None:
    """SIGTERM, then 45 s: the API's own shutdown stops a running node with `docker stop -t 30`, and a kill sooner would orphan it."""
    proc.terminate()
    try:
        proc.wait(45)
    except subprocess.TimeoutExpired:
        proc.kill()


def preflight(stack: dict = LOCAL_STACK) -> list[str]:
    """What the nodes need from Docker and `make up`; empty = ready."""
    problems = []
    try:
        if subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode:
            problems.append("the Docker daemon is not answering (start Docker Desktop, or the daemon on Linux)")
    except (OSError, subprocess.TimeoutExpired) as e:
        problems.append(f"docker is not usable: {e}")
    redis = urlparse(stack["REDIS_URL"])
    try:
        socket.create_connection((redis.hostname, redis.port), timeout=3).close()
    except OSError as e:
        problems.append(f"Redis is not reachable at {redis.hostname}:{redis.port} ({e}): run `make up`")
    try:
        httpx.get(f"{stack['ORCHAPOD_R2_ENDPOINT']}/minio/health/live", timeout=3).raise_for_status()
    except httpx.HTTPError as e:
        problems.append(f"MinIO is not reachable at {stack['ORCHAPOD_R2_ENDPOINT']} ({e}): run `make up`")
    if sys.platform.startswith("linux") and not os.environ.get("E2E_BIND_HOST"):
        problems.append("on Linux the node containers reach the API through the docker0 gateway: set E2E_BIND_HOST to it "
                        "(usually 172.17.0.1; see bind_host), on a throwaway host only")
    return problems


def build_images(node_types: list[str]) -> str | None:
    """Build orchapod/<node>:dev for each node type (an unchanged image is a cache hit, seconds); the failure, or None."""
    for node in dict.fromkeys(node_types):
        if not (ROOT / "containers" / node / "Dockerfile").exists():
            return f"no containers/{node}/Dockerfile for node type {node!r}"
        cmd = ["docker", "build", "-q", "-t", f"orchapod/{node}:dev", "-f", f"containers/{node}/Dockerfile", "."]
        say(f"building orchapod/{node}:dev")
        try:
            done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return f"`{' '.join(cmd)}` took over 600 s"
        if done.returncode:
            return f"`{' '.join(cmd)}` failed:\n{(done.stdout + done.stderr)[-1500:]}"
    return None


# ---------------------------------------------------------------------------
# The run, through the API
# ---------------------------------------------------------------------------

def call(c: httpx.Client, method: str, path: str, **kw):
    r = c.request(method, path, **kw)
    if r.is_error:
        raise RuntimeError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def get_templates(c: httpx.Client) -> list[dict]:
    """GET /agent/templates: the three canonical intents."""
    return call(c, "GET", "/agent/templates")


def poll_run(c: httpx.Client, run_id: str, path: str, done=lambda reply: reply["status"] in TERMINAL, *,
             cancel_token: str, limit: float | None = None) -> tuple[dict, float]:
    """Poll `path` (a /summary-shaped reply: the summary, or an agent report) until done(reply) or `limit` seconds (default
    LIMIT_S) pass (then cancel the run with `cancel_token`, which start or /agent/run returned: the stack has no admin, so an
    anonymous cancel without it is a 403); the last reply and the seconds taken.
    ponytail: a fixed 2 s poll and no retry of a failed call; add backoff if the API ever flaps."""
    limit = limit or LIMIT_S
    t0 = time.monotonic()
    last = None
    while True:
        reply = call(c, "GET", path)
        seconds = time.monotonic() - t0
        state = (reply["status"], [(n["node_id"], n["status"]) for n in reply["nodes"]])
        if state != last:
            say(f"{seconds:5.1f} s  run {state[0]}: " + ", ".join(f"{i} {s}" for i, s in state[1]))
            last = state
        if done(reply) or seconds >= limit:
            break
        time.sleep(2)
    if not done(reply):
        r = c.post(f"/runs/{run_id}/cancel", headers={"X-Orchapod-Cancel-Token": cancel_token}, timeout=90)
        if r.is_error and r.status_code != 409:  # 409: it ended while we asked; anything else leaves it running
            raise RuntimeError(f"run {run_id} did not end within {limit} s, and POST /runs/{run_id}/cancel -> HTTP "
                               f"{r.status_code}: {r.text[:300]}")
    return reply, seconds


def run_plan(c: httpx.Client, plan: dict) -> tuple[dict, float]:
    """Create the workflow and a run, start it, poll the summary until it ends or LIMIT_S passes (then cancel it)."""
    wf = call(c, "POST", "/workflows", json={"name": plan.get("name") or "e2e-intent-2", "yaml": plan_yaml(plan)})
    run_id = call(c, "POST", "/runs", json={"workflow_id": wf["id"], "inputs": {}})["id"]
    started = call(c, "POST", f"/runs/{run_id}/start")  # RunOut plus cancel_token, once
    return poll_run(c, run_id, f"/runs/{run_id}/summary", cancel_token=started["cancel_token"])


def download(c: httpx.Client, summary: dict, node_id: str, name: str) -> tuple[str, str | None]:
    """(text, problem) of a node's artifact, fetched through its download link (a 307 to a presigned URL)."""
    link = next((a["download_url"] for a in summary["artifacts"] if a["node_id"] == node_id and a["name"] == name), None)
    if not link:
        return "", f"{node_id}.{name} has no download_url"
    r = c.get(link, follow_redirects=True)
    if r.is_error:
        return "", f"GET {link} -> HTTP {r.status_code}"
    return r.text, None


def fetch_dataset(c: httpx.Client, summary: dict, plan: dict) -> list[str]:
    """Follow the data-prep dataset's download link (intent #2's deliverable) and check its rows."""
    prep = next(n["node_id"] for n in summary["nodes"] if n["type"] == "data-prep")
    text, problem = download(c, summary, prep, "dataset")
    if problem:
        return [problem]
    say(f"downloaded the {prep} dataset: {len(text.splitlines())} rows")
    return check_rows(text, (synth_inputs(plan) or {}).get("row_schema"))


def run(c: httpx.Client) -> int:
    templates = get_templates(c)
    intent2 = find_intent2(templates)
    if intent2 is None:
        return fail(f"{len(templates)} templates, none is intent #2 (a synth-distilabel node with pipeline_template structured)")
    plan = plan_of(intent2)
    say(f"intent #2 = template {intent2.get('slug', '?')!r}, nodes {[n['id'] for n in plan['nodes']]}")
    if problems := preflight():
        return fail("the stack is not ready:" + "".join(f"\n  - {p}" for p in problems))
    if err := build_images([n["type"] for n in plan["nodes"]]):
        return fail(err)
    summary, seconds = run_plan(c, plan)
    problems = check_run(summary)
    if seconds >= LIMIT_S:
        problems.append(f"the run did not end within {LIMIT_S} s, so it was cancelled")
    if not problems:
        problems = fetch_dataset(c, summary, plan)
    if problems:
        return fail(f"run {summary['run_id']} after {seconds:.0f} s:" + "".join(f"\n  - {p}" for p in problems))
    say(f"PASS intent #2 (stub): run {summary['run_id']} succeeded in {seconds:.0f} s (limit {LIMIT_S} s), "
        f"cost $0, {', '.join(MUST_REGISTER['data-prep'])} registered, dataset downloadable")
    return 0


def with_stack(fn, extra_env: dict[str, str | None] | None = None) -> int:
    """fn(client) -> exit code, run against a fresh API (own port, own DB; STUB=1 unless extra_env sets STUB to None, see
    api_env). The API stops however this ends: a failure, Ctrl-C, SIGTERM; a start that fails is reported like any other failure."""
    old = signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # unwind through the finally that stops the API
    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="orchapod-e2e-") as tmp:
            proc = None
            try:
                proc, base = start_api(Path(tmp), extra_env)
                wait_healthy(proc, base, Path(tmp) / "api.log")
                stub = "STUB=1" if (extra_env or {}).get("STUB", "1") else "STUB unset"  # a real run's extra_env sets STUB to None
                say(f"API up on {base}, listening on {bind_host()} ({stub}, throwaway DB)")
                with httpx.Client(base_url=base, timeout=30) as client:
                    code = fn(client)
            except (RuntimeError, httpx.HTTPError) as e:
                code = fail(e)
            finally:
                if proc:
                    stop(proc)
            if code == 1 and proc:
                say(f"API log (last lines):\n{tail(Path(tmp) / 'api.log')}")
    finally:
        signal.signal(signal.SIGTERM, old)
    say(f"done in {time.monotonic() - started:.0f} s, exit {code}")
    return code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stub e2e of intent #2 through the API (see the module docstring).")
    ap.add_argument("--stub", action="store_true", help="STUB=1: $0, no keys, no network beyond the local stack")
    ap.add_argument("--max-cost", type=float, help="the real golden run (written on D3)")
    args = ap.parse_args(argv)
    if not args.stub:
        ap.error("only --stub exists so far; the real run (--max-cost) is written on D3")
    return with_stack(run)


if __name__ == "__main__":
    sys.exit(main())
