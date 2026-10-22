"""E2E of Orchapod through the API only: a stub run of intent #2 ($0), or the live golden run on the HOSTED API (it spends).

    python scripts/e2e_demo.py --stub     # `make check E2E=1` runs it; needs Docker and `make up` (Redis, MinIO)
    python scripts/e2e_demo.py --max-cost 3 --api https://api.<domain>   # `make e2e API=https://api.<domain>`: the live golden run, below

STUB RUN. It rebuilds and retags the shared `orchapod/<node>:dev` images, so parallel worktrees must not run it: it is opt-in.
It starts its own API (STUB=1, throwaway SQLite DB, first free port from 8003, no paid key in its env; on Linux it listens
on E2E_BIND_HOST, because the node containers reach it through the docker0 gateway, see bind_host), builds the images
the plan needs (`orchapod/<node>:dev`), creates the workflow from GET /agent/templates, runs it and polls
GET /runs/{id}/summary. Asserted: the run succeeded in under 5 minutes; data-prep registered dataset, train_jsonl and
eval_jsonl; cost_usd is 0 with a cost_json on every node; the dataset's download link serves rows with exactly the
schema's fields. e2e_agent.py (the three canonical intents and the golden path) and e2e_ui.py (the Playwright smoke) reuse its
stack, checks and image builds.

LIVE GOLDEN RUN. Nobody runs it before G2 (the GPU quota and the hosted API). Template 4, Lane B (R25): web research, grounded synth,
data-prep, unsloth-train on an H100 Job, vllm-serve on an L40S endpoint, the Ultra judge. It cannot use a local API: NebiusProvider
refuses a control URL or an object-storage endpoint that is not https, because Jobs report to a public URL. So it starts nothing of its
own (no Docker, no local API, none of your keys): it asks the hosted API, as its admin, to run the template. ORCHAPOD_ADMIN_TOKEN, from
the env, goes out as X-Orchapod-Admin on POST /agent/run and nowhere else (a download redirects to another host).
- Refused before any request, one line, exit 2: no --max-cost, or one at or under 0 or over the $3 run cap; no --api, or one that is not
  https; no ORCHAPOD_ADMIN_TOKEN, or one with a character that is not printable ASCII; --stub with --api. After one read of GET
  /agent/templates, and before anything starts: the golden template is not served, no longer has the golden path's shape
  (docs/agent_knowledge.md), or its full estimate is over --max-cost or takes longer than the LIVE_LIMIT_S the run waits. A refusal never
  shows the token or the URL (it can carry userinfo), and neither does anything else printed during the run: the output is scrubbed of both.
- Flow: POST /agent/run with the template's plan as served, then GET /agent/runs/{id}/report every 2 s until `ready`, for at most
  LIVE_LIMIT_S, two hours: the healthy worst case is 75 to 87 minutes, and every paid resource has a server-side stop of its own (the
  spend deadline, the Job's hour, the endpoint's TTL). Then the run is cancelled with the cancel token /agent/run returned, in two
  attempts. A poll that fails (no answer, a 5xx, a 2xx that is not JSON) is asked again until the limit, with a warning at most once a
  minute: nothing else gives up on a run. Ctrl-C and SIGTERM cancel it too (two attempts). A cancel that fails, or any other way out
  while the run lives (a poll the API refuses), prints the run id and the admin's curl, with the token as $ORCHAPOD_ADMIN_TOKEN, never
  its value; the server's caps bound the spend. A reply to POST /agent/run that never came, is a redirect, a 5xx or is no JSON, or
  an interrupt during that POST (no cancel token yet), says that a run may have started, and how to find it.
- Checks (e2e_agent's helpers, plus the endpoint): the run succeeded; 0 < cost_usd <= --max-cost; every node's contract artifacts
  and a cost_json (unsloth-train: lora_adapter); the data-prep dataset downloads with rows; judge-eval's eval_summary has the
  contract's shape and `stub` false; the report names the plan; vllm-serve registered an endpoint_url that is https and no stub-* id.
- Output: the run id is on the third line; the PASS or FAIL line of e2e_agent's real run, with the judge's numbers; the endpoint's
  expires_at (the L40S bills until then); each node's wall time and $ (GET /runs/{id}/summary) and the run's span against G1's 25-minute
  bar (shown, not a check). A summary that cannot be read is said so, and changes nothing. Exit 0 PASS, 1 FAIL or an error, 2 refused.
  The Orchestrator records the run id and the cost in hackathon/LOG.md.
"""

import argparse
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
LIMIT_S = 300  # a stub run must end within 5 minutes
TERMINAL = ("succeeded", "failed", "cancelled")
ADMIN_ENV = "ORCHAPOD_ADMIN_TOKEN"  # the live run's admin token (budget.admin): the hosted API's, never a local one
# The live golden run waits two hours (intents 1 to 3 keep e2e_agent.REAL_LIMIT_S, an hour): its healthy worst case is 75 to 87 minutes,
# and every paid resource has a server-side stop of its own (R14's spend deadline, the Job's hour, the endpoint's TTL), so a shorter
# wait protects nothing and risks cancelling a run that is going well.
LIVE_LIMIT_S = 7200
BAR_MIN = 25  # G1: the golden path ends within 25 minutes (hackathon/PLAN.md)
# What each node type must register, by contract (docs/contracts.md "Data nodes", "ML nodes"); the SDK adds cost_json to all.
MUST_REGISTER = {
    "web-research": ("corpus",), "synth-distilabel": ("dataset",), "data-prep": ("dataset", "train_jsonl", "eval_jsonl"),
    "tf-finetune": ("job", "lora_adapter"), "vllm-serve": ("model_ref",), "judge-eval": ("eval_summary",),
    "hf-download": ("hf_model",), "quantize": ("gguf_file",),
    "unsloth-train": ("lora_adapter",),  # no merged_model: templates 4 and 5 set merge: false
}
# The stub stack builds these from a slim stage: unsloth-train's default stage is a 20 GB amd64 CUDA image (ml-w7). A real run never
# builds a node that rents a GPU, so it never needs a stage that has no torch.
STUB_TARGETS = {"unsloth-train": "stub"}
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
    """Build orchapod/<node>:dev for each node type (an unchanged image is a cache hit, seconds), from its STUB_TARGETS stage if it
    has one; the failure, or None."""
    for node in dict.fromkeys(node_types):
        if not (ROOT / "containers" / node / "Dockerfile").exists():
            return f"no containers/{node}/Dockerfile for node type {node!r}"
        target = ["--target", STUB_TARGETS[node]] if node in STUB_TARGETS else []
        cmd = ["docker", "build", "-q", *target, "-t", f"orchapod/{node}:dev", "-f", f"containers/{node}/Dockerfile", "."]
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

class ApiError(RuntimeError):
    """A reply that is not a JSON 2xx; `status` tells a refusal (4xx) from a failure (5xx), a redirect (3xx) from a 2xx that is no JSON."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def call(c: httpx.Client, method: str, path: str, **kw):
    r = c.request(method, path, **kw)
    if not r.is_success:  # a 3xx is not an answer either: the request may or may not have reached the API
        raise ApiError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}", r.status_code)
    try:
        return r.json()
    except ValueError:
        raise ApiError(f"{method} {path} -> HTTP {r.status_code} with a body that is not JSON: {r.text[:100]!r}", r.status_code) from None


def get_templates(c: httpx.Client) -> list[dict]:
    """GET /agent/templates: the three canonical intents, the golden path (template 4) and its CPU variant."""
    return call(c, "GET", "/agent/templates")


def cancel_run(c: httpx.Client, run_id: str, cancel_token: str, attempts: int = 2) -> str | None:
    """POST /runs/{id}/cancel with the run's token (the stack has no admin, so without it an anonymous cancel is a 403), up to
    `attempts` times: the cancel waits for the executor, so the first may time out while it goes through, and the second then finds the
    run ended (409, which is done). None when the run is cancelled or had ended, else what went wrong the last time."""
    for _ in range(attempts):
        say(f"cancelling run {run_id} (up to 90 s)")
        try:
            r = c.post(f"/runs/{run_id}/cancel", headers={"X-Orchapod-Cancel-Token": cancel_token}, timeout=90)
        except httpx.TransportError as e:
            problem = f"POST /runs/{run_id}/cancel failed: {type(e).__name__}: {e}"
        else:
            if r.is_success or r.status_code == 409:  # 409: it ended while we asked
                say(f"cancelled run {run_id}" if r.is_success else f"run {run_id} had ended")
                return None
            problem = f"POST /runs/{run_id}/cancel -> HTTP {r.status_code}: {r.text[:300]}"
    return problem


def poll_run(c: httpx.Client, run_id: str, path: str, done=lambda reply: reply["status"] in TERMINAL, *,
             cancel_token: str, limit: float | None = None, tolerate: bool = False) -> tuple[dict | None, float]:
    """Poll `path` (a /summary-shaped reply: the summary, or an agent report) until done(reply) or `limit` seconds (default
    LIMIT_S) pass (then cancel the run with `cancel_token`, which start or /agent/run returned); the last reply and the seconds
    taken. With `tolerate`, a poll that fails (no answer, a 5xx, a 2xx that is not JSON: a hosted API behind a proxy blinks) is asked
    again until the limit, with a warning at most once a minute, and the last good reply stands for the run (None if there was none);
    a 3xx or 4xx never heals, and is raised.
    ponytail: a fixed 2 s poll, no backoff."""
    limit = limit or LIMIT_S
    t0 = time.monotonic()
    reply = last = warned = None
    while True:
        failure = None
        try:
            reply = call(c, "GET", path)
        except (ApiError, httpx.TransportError) as e:
            if not tolerate or (isinstance(e, ApiError) and 300 <= e.status < 500):
                raise
            failure = e
        seconds = (now := time.monotonic()) - t0
        if failure is None:
            state = (reply["status"], [(n["node_id"], n["status"]) for n in reply["nodes"]])
            if state != last:
                say(f"{seconds:5.1f} s  run {state[0]}: " + ", ".join(f"{i} {s}" for i, s in state[1]))
                last = state
        elif warned is None or now - warned >= 60:
            warned = now
            say(f"poll failed at {seconds:.0f} s ({type(failure).__name__}: {failure}); asking again until the limit")
        finished = failure is None and done(reply)
        if finished or seconds >= limit:
            break
        time.sleep(2)
    if not finished and (problem := cancel_run(c, run_id, cancel_token)):
        raise RuntimeError(f"run {run_id} did not end within {limit} s, and {problem}")
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


# ---------------------------------------------------------------------------
# The live golden run, on the hosted API
# ---------------------------------------------------------------------------

def _agent():
    import e2e_agent  # lazy: it imports this module

    return e2e_agent


def refusal(max_cost: float | None, api: str, token: str) -> str | None:
    """Why the live run must not start, in one line that shows neither the token nor the URL (it can carry userinfo); else None."""
    if max_cost is None or not max_cost > 0:  # `not > 0` also refuses nan
        return "refusing to run without --max-cost: the live golden run rents GPUs, so it needs a USD cap above 0"
    if max_cost > (cap := _agent().CAP_USD):
        return f"refusing --max-cost {max_cost:g}: the project caps a run at ${cap:g}"
    if not api:
        return "refusing to run without --api: the live golden run needs the hosted API, https://api.<domain> (a local API cannot run its GPU nodes)"
    parts = urlparse(api)
    if parts.scheme != "https" or not parts.hostname:
        return "refusing to run: --api must be an https URL with a host (the admin token would travel in the clear; its value is not shown)"
    if not token:
        return f"refusing to run: {ADMIN_ENV} is unset (the hosted API's admin token: only the admin can start a run that rents a GPU)"
    if not (token.isascii() and token.isprintable()):  # httpx would quote a header value it cannot send, in a form the scrub misses
        return f"refusing to run: {ADMIN_ENV} holds a character that is not printable ASCII (a newline, a NUL...; its value is not shown)"
    return None


def refuse(message: str):
    """A refusal: one line on stderr, exit 2, nothing started."""
    print(f"e2e: {message}", file=sys.stderr, flush=True)
    raise SystemExit(2)


class Scrub:
    """A text stream that hides the secrets in whatever is written to the stream it wraps, longest first."""

    def __init__(self, stream, secrets):
        self.stream, self.secrets = stream, sorted({s for s in secrets if s}, key=len, reverse=True)

    def write(self, text):
        for secret in self.secrets:
            text = text.replace(secret, "<hidden>")
        return self.stream.write(text)

    def flush(self):
        self.stream.flush()


def endpoint_faults(artifact: dict) -> list[str]:
    """What is wrong with a registered endpoint_url (/internal/ttl records it with the URL Nebius reports): not https, a stub's id."""
    scheme = urlparse(artifact.get("uri") or "").scheme
    endpoint_id = (artifact.get("meta") or {}).get("endpoint_id")
    faults = [] if scheme == "https" else [f"not https ({scheme or 'no scheme'})"]
    if not endpoint_id:
        faults.append("unnamed (no endpoint_id)")
    elif str(endpoint_id).startswith("stub-"):
        faults.append(f"a stub-* endpoint ({endpoint_id!r})")
    return faults


def check_endpoints(report: dict, plan: dict) -> list[str]:
    """A live vllm-serve registered an endpoint_url that is https and no stub-* id (a hosted API that runs on STUB makes those). One
    good registration is the node's endpoint: a superseded row may be anything."""
    problems = []
    for node in plan["nodes"]:
        if node["type"] != "vllm-serve":
            continue
        found = [a for a in report["artifacts"] if a["node_id"] == node["id"] and a["name"] == "endpoint_url"]
        faults = [endpoint_faults(a) for a in found]
        if not found:
            problems.append(f"vllm-serve {node['id']!r} registered no endpoint_url")
        elif all(faults):
            problems.append(f"vllm-serve {node['id']!r} registered an endpoint_url that is {', '.join(faults[0])}")
    return problems


def node_lines(summary: dict) -> tuple[list[str], float | None]:
    """A line per node of GET /runs/{id}/summary (status, wall time from its own timestamps, $), and the run's span in seconds: the
    first node's start to the last node's end, None when no node has both."""
    def when(node, key):
        return datetime.fromisoformat(node[key]) if node.get(key) else None

    lines, starts, ends = [], [], []
    for n in summary["nodes"]:
        t0, t1 = when(n, "started_at"), when(n, "finished_at")
        secs = (t1 - t0).total_seconds() if t0 and t1 else None
        wall = "-" if secs is None else f"{secs:.0f} s" if secs < 120 else f"{secs / 60:.1f} min"
        lines.append(f"{n['node_id']:<10} {n['type']:<17} {n['status']:<10} {wall:>8} ${n['usd']:.4f}")
        starts += [t0] if t0 else []
        ends += [t1] if t1 else []
    return lines, (max(ends) - min(starts)).total_seconds() if starts and ends else None


def evidence(c: httpx.Client, run_id: str, report: dict, plan: dict) -> None:
    """What the run is for, after its verdict, which nothing here can change: when the endpoint expires (the L40S bills until then),
    then each node's wall time and $ and the run's span against G1's bar (shown, not a check)."""
    serves = {n["id"] for n in plan["nodes"] if n["type"] == "vllm-serve"}
    for a in report["artifacts"]:
        if a["node_id"] in serves and a["name"] == "endpoint_url":
            meta = a.get("meta") or {}
            say(f"endpoint {a['node_id']}: expires_at {meta.get('expires_at', 'unknown')} (keep_alive_min {meta.get('keep_alive_min', '?')}, billed until then)")
    try:
        lines, span = node_lines(call(c, "GET", f"/runs/{run_id}/summary"))
        say(f"nodes, from /runs/{run_id}/summary:")
        for line in lines:
            say(f"  {line}")
        say("run wall unknown (no node has a start and an end)" if span is None else
            f"run wall {span / 60:.1f} min (first node start to last node end); G1's {BAR_MIN}-minute bar: {'met' if span <= BAR_MIN * 60 else 'NOT met'}")
    except Exception as e:  # an unreadable summary (no answer, not JSON, off its shape) never turns a PASS into an exit 1
        say(f"could not read the summary of run {run_id}: {type(e).__name__}: {e}")


def still_running(c: httpx.Client, run_id: str) -> str:
    """What to do about a run the script leaves behind: the admin stops it. The token is a variable here, never its value."""
    base = c.base_url
    return (f'run {run_id} may still be running; cancel it as the admin: curl -X POST -H "X-Orchapod-Admin: ${ADMIN_ENV}" '
            f"{base.scheme}://{base.netloc.decode()}{base.path.rstrip('/')}/runs/{run_id}/cancel")


def live(c: httpx.Client, token: str, max_cost: float) -> int:
    """The live golden run on the hosted API that `c` talks to (module docstring): 0 PASS, 1 FAIL, 2 refused (SystemExit)."""
    agent = _agent()
    limit, number = LIVE_LIMIT_S, agent.GOLDEN
    templates = get_templates(c)
    template = agent.canonical(templates, number)
    if template is None:
        refuse(f"refusing to run: {len(templates)} templates, none is {agent.name_of(number)} (slug {agent.SLUGS[number]!r})")
    plan, estimate, intent = template["plan"], template["estimate"], template["intent"]
    if not agent.INTENTS[number][1](types := agent.node_types(plan)):
        refuse(f"refusing to run: the plan of {agent.name_of(number)} {agent.INTENTS[number][2]} (docs/agent_knowledge.md), but this one runs {types}")
    if estimate["usd"] > max_cost:
        refuse(f"refusing to run: the golden path's full estimate ${estimate['usd']} is over --max-cost ${max_cost:g}")
    if estimate["minutes"] * 60 > limit:
        refuse(f"refusing to run: the golden path's full estimate takes {estimate['minutes']:g} min, over the {limit / 60:g} min a live run waits")
    say(f"golden path = template {template['slug']!r}: plan {plan['name']!r}, nodes {[n['id'] for n in plan['nodes']]}, "
        f"full estimate ${estimate['usd']} / {estimate['minutes']:g} min, cap ${max_cost:g}")
    maybe = f"the run may have started: look for {plan['name']!r} among the runs and cancel it as the admin (POST /runs/<id>/cancel)"
    try:
        started = call(c, "POST", "/agent/run", json={"intent": intent, "plan": plan}, headers={"X-Orchapod-Admin": token})
    except ApiError as e:  # a 4xx is a refusal and nothing started; a 3xx, a 5xx and a 2xx that is not JSON are no proof of that
        hint = f"; check {ADMIN_ENV}: only the admin can start a run that rents a GPU" if e.status == 403 else "" if 400 <= e.status < 500 else f"; {maybe}"
        raise ApiError(f"{e}{hint}", e.status) from e
    except httpx.TransportError as e:
        raise RuntimeError(f"POST /agent/run: {type(e).__name__}: {e}; {maybe}") from e
    except (KeyboardInterrupt, SystemExit):  # Ctrl-C, SIGTERM: there is no cancel token yet
        say(f"interrupted during POST /agent/run; {maybe}")
        raise
    run_id, cancel_token = started["run_id"], started["cancel_token"]
    say(f"started run {run_id}; polling its report every 2 s for at most {limit} s, then it is cancelled")
    try:
        report, seconds = poll_run(c, run_id, f"/agent/runs/{run_id}/report", done=lambda r: r["ready"], cancel_token=cancel_token,
                                   limit=limit, tolerate=True)
    except BaseException as e:  # Ctrl-C and SIGTERM stop the run; any other way out leaves it, and says how to stop it (the server's caps bound the spend)
        if not isinstance(e, (KeyboardInterrupt, SystemExit)) or cancel_run(c, run_id, cancel_token):
            say(still_running(c, run_id))
        raise
    if report is None:  # the polls failed to the end of the limit
        agent.show("FAIL", "golden path", [f"the run was not seen once in {limit} s, so it was cancelled"], f" (run {run_id})")
        return 1
    problems = agent.check_report(report, intent, plan, max_cost)
    if seconds >= limit:
        problems.append(f"the run did not end within {limit} s, so it was cancelled")
    evals = []
    if not problems:
        try:
            problems = agent.check_outputs(c, report, plan, max_cost, evals) + check_endpoints(report, plan)
        except Exception as e:  # the verdict and the evidence matter more than this one read
            problems = [f"could not check the outputs: {type(e).__name__}: {e}"]
    cost = f"${report['cost_usd']:.4f}"
    if problems:
        agent.show("FAIL", "golden path", problems, f" (run {run_id} after {seconds:.0f} s, cost {cost}, estimate ${estimate['usd']})")
    else:
        say(f"PASS golden path: run {run_id} succeeded in {seconds:.0f} s (limit {limit} s), cost {cost}, estimate ${estimate['usd']}, "
            f"report ready ({len(report['markdown'])} chars)" + "".join(agent.eval_numbers(i, e) for i, e in evals))
    evidence(c, run_id, report, plan)
    return 1 if problems else 0


def golden(api: str, token: str, max_cost: float) -> int:
    """live() against `api`, and what its output may not hold: the token and the URL's userinfo are scrubbed from everything printed;
    SIGTERM unwinds like Ctrl-C, through live()'s cancel."""
    parts = urlparse(api)
    secrets = [x for part in (token, parts.username, parts.password) if part for x in (part, unquote(part))]
    old = signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        with contextlib.redirect_stdout(Scrub(sys.stdout, secrets)), contextlib.redirect_stderr(Scrub(sys.stderr, secrets)):
            say(f"live golden run on {parts.netloc.rpartition('@')[2]}, as its admin, cap ${max_cost:g}")
            try:
                with httpx.Client(base_url=api, timeout=30) as client:
                    return live(client, token, max_cost)
            except (RuntimeError, httpx.HTTPError, httpx.InvalidURL) as e:  # InvalidURL: a port that is no number, before any request
                return fail(e if isinstance(e, RuntimeError) else f"{type(e).__name__}: {e}")
    finally:
        signal.signal(signal.SIGTERM, old)


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
    ap = argparse.ArgumentParser(description="E2E through the API: --stub, a stub run of intent #2 ($0), or --max-cost and --api, the live "
                                             "golden run on the hosted API (see the module docstring).")
    ap.add_argument("--stub", action="store_true", help="STUB=1: $0, no keys, no network beyond the local stack")
    ap.add_argument("--max-cost", type=float, help="the live golden run: its USD cap, above 0 and at most $3 (the run is refused when the "
                                                   "template's full estimate is over it)")
    ap.add_argument("--api", help=f"the live golden run: the HOSTED API, https only (https://api.<domain>); the admin token is read from "
                                  f"{ADMIN_ENV} and sent as X-Orchapod-Admin")
    args = ap.parse_args(argv)
    api = (args.api or "").strip()
    if args.stub:
        if api:
            refuse("refusing --stub with --api: --api is for the live run; --stub runs on a local stack of its own")
        return with_stack(run)
    token = os.environ.get(ADMIN_ENV, "").strip()
    if message := refusal(args.max_cost, api, token):
        refuse(message)
    return golden(api, token, args.max_cost)


if __name__ == "__main__":
    sys.exit(main())
