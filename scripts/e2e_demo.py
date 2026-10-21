"""Stub e2e of intent #2 (synthetic movie events), through the API only: no paid call, $0.

    python scripts/e2e_demo.py --stub     # the last step of `make check`; needs Docker and `make up` (Redis, MinIO)

It starts its own API (STUB=1, throwaway SQLite DB, first free port from 8002, no paid key in its env), builds the images
the plan needs (`orchapod/<node>:dev`), creates the workflow from GET /agent/templates (fallback: the JSON files it is
built from), runs it and polls GET /runs/{id}/summary. Asserted: the run succeeded in under 5 minutes; data-prep registered
dataset, train_jsonl and eval_jsonl; cost_usd is 0 with a cost_json on every node; the dataset's download link serves rows
with exactly the schema's fields.

A prerequisite that is not merged yet (backend-w2: the templates; data-w2: synth `structured`) prints SKIP with its
reason and exits 0; --strict makes that exit 3. The real golden run (--max-cost) is written on D3.
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
TEMPLATES = ROOT / "apps/api/agent/templates"
LIMIT_S = 300  # a stub run must end within 5 minutes
TERMINAL = ("succeeded", "failed", "cancelled")
NEEDED = ("dataset", "train_jsonl", "eval_jsonl")  # what data-prep must register
# A stub run can spend nothing: none of these reaches the API, and through it a node.
PAID = ("VASTAI_API_KEY", "RUNPOD_API_KEY", "NEBIUS_API_KEY", "NEBIUS_IAM_TOKEN", "NEBIUS_PROJECT_ID",
        "ORCHAPOD_ENDPOINT_TOKEN", "TAVILY_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "HF_TOKEN")
# The compose stack (`make up`): a stub run touches nothing else, whatever the shell exports.
LOCAL_STACK = {
    "REDIS_URL": "redis://localhost:6379", "ORCHAPOD_R2_ENDPOINT": "http://localhost:9000", "ORCHAPOD_R2_REGION": "auto",
    "ORCHAPOD_R2_ACCESS_KEY": "orchapod", "ORCHAPOD_R2_SECRET_KEY": "orchapod_dev", "ORCHAPOD_R2_BUCKET": "orchapod-artifacts",
}
# ponytail: SKIP scaffolding for wave 2; delete MISSING, skip_reasons, structured_supported and --strict once both merge.
MISSING = {
    "templates": "backend-w2 is not merged: GET /agent/templates answers 404 and apps/api/agent/templates/*.json is absent",
    "synth": 'data-w2 is not merged: SynthDistilabelInputs rejects pipeline_template "structured" '
             "(packages/workflow_schema/models.py)",
}


def say(msg: str) -> None:
    print(f"e2e: {msg}", flush=True)


def fail(msg) -> int:
    print(f"e2e FAIL: {msg}", flush=True)
    return 1


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/e2e)
# ---------------------------------------------------------------------------

def api_env(port: int, db: Path, environ) -> dict[str, str]:
    """The API's env: stub, no paid key, the compose stack, its own DB and port, the kill switch off."""
    env = {k: v for k, v in environ.items() if k not in PAID}
    return env | LOCAL_STACK | {
        "STUB": "1",
        "ORCHAPOD_KILL_SWITCH": "0",
        "DATABASE_URL": f"sqlite+aiosqlite:///{db}",
        "ORCHAPOD_CONTROL_URL": f"http://127.0.0.1:{port}",  # LocalDocker rewrites it to host.docker.internal
        "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "apps"), str(ROOT / "packages/sdk-py")]),
    }


def listen_on_free_port(start: int = 8002) -> socket.socket:
    """A listening socket on the first free port from `start` (8000 and 8001 belong to other projects on this Mac, and the dev
    API may hold 8002). The API gets this very socket, so no other process can take the port in between."""
    for port in range(start, start + 50):
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", port))
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


def structured_supported(inputs: dict | None = None) -> bool:
    """False while SynthDistilabelInputs rejects pipeline_template "structured"; any other input error is not "unmerged"."""
    from pydantic import ValidationError

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from packages.workflow_schema import models

    try:
        models.SynthDistilabelInputs(**(inputs or {"pipeline_template": "structured", "row_schema": {"type": "object"}}))
    except ValidationError as e:
        return not any(err["loc"] == ("pipeline_template",) for err in e.errors())
    return True


def skip_reasons(have_templates: bool, have_structured: bool) -> list[str]:
    return [MISSING[k] for k, ok in (("templates", have_templates), ("synth", have_structured)) if not ok]


def check_run(summary: dict) -> list[str]:
    """What is wrong with a finished stub run; empty = fine."""
    nodes, artifacts = summary["nodes"], summary["artifacts"]
    if summary["status"] != "succeeded":
        def state(x):
            return x["status"] + (f": {x['error']}" if x["error"] else "")

        return [f"run {state(summary)}"] + [f"node {n['node_id']} {state(n)}" for n in nodes if n["status"] != "succeeded"]
    made = {n["node_id"]: {a["name"] for a in artifacts if a["node_id"] == n["node_id"]} for n in nodes}
    preps = [n["node_id"] for n in nodes if n["type"] == "data-prep"]
    problems = [] if preps else ["the run has no data-prep node"]
    for node_id in preps:  # synth also registers a `dataset`, so look on data-prep's own node
        if absent := [name for name in NEEDED if name not in made[node_id]]:
            problems.append(f"data-prep {node_id!r} did not register {', '.join(absent)}")
    if summary["cost_usd"] != 0:
        problems.append(f"cost_usd is {summary['cost_usd']}, expected 0 in STUB")
    for n in nodes:
        if n["usd"] != 0:
            problems.append(f"node {n['node_id']!r} reports usd {n['usd']}, expected 0 in STUB")
        if "cost_json" not in made[n["node_id"]]:
            problems.append(f"node {n['node_id']!r} wrote no cost_json, so its $0 was never measured")
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


def start_api(tmp: Path) -> tuple[subprocess.Popen, str]:
    """ponytail: binds 127.0.0.1, which Docker Desktop reaches as host.docker.internal; on Linux it needs 0.0.0.0."""
    with listen_on_free_port() as sock:
        port = sock.getsockname()[1]
        with open(tmp / "api.log", "w") as log:
            proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.main:app", "--fd", str(sock.fileno())], cwd=ROOT,
                                    env=api_env(port, tmp / "e2e.db", os.environ), stdout=log, stderr=subprocess.STDOUT,
                                    pass_fds=[sock.fileno()])
    return proc, f"http://127.0.0.1:{port}"


def wait_healthy(proc: subprocess.Popen, base: str, log: Path) -> None:
    for _ in range(120):
        if proc.poll() is not None:
            break
        try:
            if httpx.get(f"{base}/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"the API did not start on {base}:\n{tail(log)}")


def stop(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(20)
    except subprocess.TimeoutExpired:
        proc.kill()


def preflight(stack: dict = LOCAL_STACK) -> list[str]:
    """What the nodes need from Docker and `make up`; empty = ready."""
    problems = []
    try:
        if subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode:
            problems.append("the Docker daemon is not answering (start Docker Desktop)")
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


def templates_on_disk() -> list[dict]:
    return [json.loads(f.read_text()) for f in sorted(TEMPLATES.glob("*.json"))]


def get_templates(c: httpx.Client) -> list[dict] | None:
    """GET /agent/templates; on 404 the JSON files it is built from; None when neither exists."""
    r = c.get("/agent/templates")
    if r.status_code == 200:
        return r.json()
    if r.status_code != 404:
        raise RuntimeError(f"GET /agent/templates -> HTTP {r.status_code}: {r.text[:300]}")
    return templates_on_disk() or None


def run_plan(c: httpx.Client, plan: dict) -> tuple[dict, float]:
    """Create the workflow and a run, start it, poll the summary until it ends or LIMIT_S passes (then cancel it).
    ponytail: a fixed 2 s poll and no retry of a failed call; add backoff if the API ever flaps."""
    wf = call(c, "POST", "/workflows", json={"name": plan.get("name") or "e2e-intent-2", "yaml": plan_yaml(plan)})
    run_id = call(c, "POST", "/runs", json={"workflow_id": wf["id"], "inputs": {}})["id"]
    t0 = time.monotonic()
    call(c, "POST", f"/runs/{run_id}/start")
    last = None
    while True:
        summary = call(c, "GET", f"/runs/{run_id}/summary")
        seconds = time.monotonic() - t0
        state = (summary["status"], [(n["node_id"], n["status"]) for n in summary["nodes"]])
        if state != last:
            say(f"{seconds:5.1f} s  run {state[0]}: " + ", ".join(f"{i} {s}" for i, s in state[1]))
            last = state
        if summary["status"] in TERMINAL or seconds >= LIMIT_S:
            break
        time.sleep(2)
    if summary["status"] not in TERMINAL:
        try:
            call(c, "POST", f"/runs/{run_id}/cancel", timeout=90)
        except RuntimeError:
            pass  # it may have just ended
    return summary, seconds


def fetch_dataset(c: httpx.Client, summary: dict, plan: dict) -> list[str]:
    """Follow the data-prep dataset's download link (intent #2's deliverable) and check its rows."""
    prep = next(n["node_id"] for n in summary["nodes"] if n["type"] == "data-prep")
    link = next(a["download_url"] for a in summary["artifacts"] if a["node_id"] == prep and a["name"] == "dataset")
    if not link:
        return ["the dataset artifact has no download_url"]
    r = c.get(link, follow_redirects=True)
    if r.is_error:
        return [f"GET {link} -> HTTP {r.status_code}"]
    say(f"downloaded the dataset through {link}: {len(r.text.splitlines())} rows")
    return check_rows(r.text, (synth_inputs(plan) or {}).get("row_schema"))


def run(c: httpx.Client, strict: bool) -> int:
    templates = get_templates(c)
    intent2 = find_intent2(templates) if templates is not None else None
    if templates is not None and intent2 is None:
        return fail(f"{len(templates)} templates, none is intent #2 (a synth-distilabel node with pipeline_template structured)")
    plan = plan_of(intent2) if intent2 else {}
    if reasons := skip_reasons(templates is not None, structured_supported(synth_inputs(plan))):
        print("\n".join(["e2e SKIP (this is NOT a pass: intent #2 did not run):", *(f"  - {r}" for r in reasons),
                         "  It runs for real once these merge; --strict turns this SKIP into a failure (exit 3)."]), flush=True)
        return 3 if strict else 0
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
        f"cost $0, {', '.join(NEEDED)} registered, dataset downloadable")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Stub e2e of intent #2 through the API (see the module docstring).")
    ap.add_argument("--stub", action="store_true", help="STUB=1: $0, no keys, no network beyond the local stack")
    ap.add_argument("--max-cost", type=float, help="the real golden run (written on D3)")
    ap.add_argument("--strict", action="store_true", help="a SKIP (prerequisite not merged) exits 3 instead of 0")
    args = ap.parse_args(argv)
    if not args.stub:
        ap.error("only --stub exists so far; the real run (--max-cost) is written on D3")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # unwind through the finally that stops the API
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="orchapod-e2e-") as tmp:
        proc, base = start_api(Path(tmp))
        try:  # the finally stops the API however this ends: failure, Ctrl-C, SIGTERM
            wait_healthy(proc, base, Path(tmp) / "api.log")
            say(f"API up on {base} (STUB=1, throwaway DB)")
            with httpx.Client(base_url=base, timeout=30) as client:
                code = run(client, args.strict)
        except (RuntimeError, httpx.HTTPError) as e:
            code = fail(e)
        finally:
            stop(proc)
        if code == 1:
            say(f"API log (last lines):\n{tail(Path(tmp) / 'api.log')}")
    say(f"done in {time.monotonic() - started:.0f} s, exit {code}")
    return code


if __name__ == "__main__":
    sys.exit(main())
