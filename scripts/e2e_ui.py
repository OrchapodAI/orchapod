"""Playwright smoke of the web app, in STUB mode and $0, on the same stack as e2e_demo.py and e2e_agent.py.

    python scripts/e2e_ui.py [--strict] [-g REGEX]     # `make ui-smoke`; needs Docker, `make up`, node and pnpm

It starts the API (STUB=1, throwaway DB, full caps: the UI is anonymous) and `next dev` on the first free port from 3100, builds
the node images of the canonical intents that can run, and runs tests/ui (Playwright, version pinned in tests/ui/package.json,
headless Chromium) against them. The tests: /agent intent #2 to a finished report; the template gallery's one-click Run of
intent #2 with its dataset card; the eval view and the compare playground on a run served from a fixture; the golden path
(intent #1: one click, the run, its eval view, the playground).

A step whose piece is not merged yet (vllm-serve for intent #1: see e2e_agent.PENDING) prints SKIP with its reason and does not
fail; --strict fails it. The pieces the API still lacks are found here, from the planner's own errors, and passed on in
E2E_PENDING. The UI, judge-eval and POST /compare are on NebiusHackathon: a missing one fails.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import e2e_agent as agent
import e2e_demo as demo
import httpx

ROOT = demo.ROOT
WEB, UI = ROOT / "apps/web", ROOT / "tests/ui"
# pnpm 11 runs `pnpm install` before every command unless told not to (the Makefile's PNPM, and why).
PNPM = ["pnpm", "--config.verify-deps-before-run=false"]
SPEC_INTENTS = ("1", "2")  # the canonical intents tests/ui drives
PLAYWRIGHT_TIMEOUT_S = 570  # tests/ui/playwright.config.ts: globalTimeout 9 min


def web_env(api_url: str, environ) -> dict[str, str]:
    """The web app's env: it talks to this API only, and no paid key reaches it."""
    env = {k: v for k, v in environ.items() if k not in demo.PAID}
    return env | {"NEXT_PUBLIC_API_URL": api_url, "NEXT_PUBLIC_WS_URL": api_url.replace("http", "ws", 1),
                  "NEXT_TELEMETRY_DISABLED": "1"}


def playwright_env(web_url: str, api_url: str, pending: dict, strict: bool, environ) -> dict[str, str]:
    """What tests/ui reads: where the app and the API are, what cannot run yet, and whether that fails."""
    env = {k: v for k, v in environ.items() if k not in demo.PAID}
    return env | {"E2E_WEB_URL": web_url, "E2E_API_URL": api_url, "E2E_PENDING": json.dumps(pending),
                  "E2E_STRICT": "1" if strict else "", "E2E_OUT": str(UI / "test-results")}


def deps_missing() -> list[str]:
    """The installs this run needs (pnpm 11 exits 1 on apps/web with ERR_PNPM_IGNORED_BUILDS: sharp, which is harmless)."""
    return [f"{d.relative_to(ROOT)} has no {tool}: run `make ui-deps`" for d, tool in ((WEB, "next"), (UI, "playwright"))
            if not (d / "node_modules/.bin" / tool).exists()]


def ui_pending(c: httpx.Client) -> tuple[dict[str, list[str]], set[str]]:
    """({intent: why it cannot run yet}, node types of the intents that can) for the canonical intents the tests drive.
    A plan error that is not a named gap raises: that is a failure, not a SKIP."""
    templates, pending, types = demo.get_templates(c), {}, set()
    for number in SPEC_INTENTS:
        template = agent.canonical(templates, number)
        if template is None:
            raise RuntimeError(f"none of the {len(templates)} templates is canonical intent #{number}")
        reply = demo.call(c, "POST", "/agent/plan", json={"intent": template["intent"]})
        if reasons := agent.skip_reasons(reply["errors"], reply["plan"]):
            pending[number] = reasons
        elif reply["errors"]:
            raise RuntimeError(f"intent #{number}: {'; '.join(reply['errors'])}")
        else:
            types |= {n["type"] for n in reply["plan"]["nodes"]}
    return pending, types


def free_port(start: int) -> int:
    """ponytail: the port is free when chosen, not held (`next dev` cannot take a socket); a race needs a second process starting
    in the same instant."""
    with demo.listen_on_free_port(start) as sock:
        return sock.getsockname()[1]


def start_web(api_url: str, tmp: Path) -> tuple[subprocess.Popen, str]:
    port = free_port(3100)
    cmd = [*PNPM, "-C", str(WEB), "exec", "next", "dev", "--turbopack", "--hostname", "127.0.0.1", "--port", str(port)]
    with open(tmp / "web.log", "w") as log:  # its own process group: pnpm starts node, which starts more
        proc = subprocess.Popen(cmd, env=web_env(api_url, os.environ), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return proc, f"http://127.0.0.1:{port}"


def stop_group(proc: subprocess.Popen) -> None:
    """SIGTERM the whole process group, then SIGKILL it after 20 s."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(20)
    except ProcessLookupError:
        return
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(10)


def run_playwright(extra: list[str], env: dict[str, str]) -> int:
    """Playwright's exit code; in its own process group, so the timeout (and Ctrl-C) takes its browsers down too."""
    proc = subprocess.Popen([*PNPM, "-C", str(UI), "exec", "playwright", "test", *extra], cwd=UI, env=env, start_new_session=True)
    try:
        return proc.wait(PLAYWRIGHT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"playwright took over {PLAYWRIGHT_TIMEOUT_S} s and was stopped")
    finally:
        if proc.poll() is None:
            stop_group(proc)


def summarize(report: dict) -> str:
    """The honest count, from Playwright's JSON report: a SKIPped step is not a pass."""
    s = report["stats"]
    return f"{s['expected']} passed, {s['skipped']} SKIPPED (not passes), {s['unexpected']} failed, {s['flaky']} flaky"


def run(c: httpx.Client, strict: bool, extra: list[str]) -> int:
    if problems := demo.preflight() + deps_missing():
        return demo.fail("the stack is not ready:" + "".join(f"\n  - {p}" for p in problems))
    pending, types = ui_pending(c)
    for number, reasons in pending.items():
        demo.say(f"intent #{number} cannot run yet (its UI steps SKIP): " + "; ".join(reasons))
    if err := demo.build_images(sorted(types)):
        return demo.fail(err)
    api_url = str(c.base_url).rstrip("/")
    report = UI / "test-results/report.json"
    report.unlink(missing_ok=True)  # a failed start must not be read as the last run's result
    with tempfile.TemporaryDirectory(prefix="orchapod-ui-") as tmp:
        web, web_url = start_web(api_url, Path(tmp))
        try:
            demo.wait_healthy(web, web_url, Path(tmp) / "web.log", path="/agent", tries=240)
            demo.say(f"web up on {web_url} (next dev, API {api_url})")
            code = run_playwright(extra, playwright_env(web_url, api_url, pending, strict, os.environ))
        except RuntimeError as e:
            return demo.fail(e)
        finally:
            stop_group(web)
        if code:
            demo.say(f"web log (last lines):\n{demo.tail(Path(tmp) / 'web.log')}")
    demo.say("playwright: " + (summarize(json.loads(report.read_text())) if report.exists() else "no report.json"))
    if code:
        return demo.fail(f"playwright exited {code}; traces and screenshots of failures: {UI / 'test-results'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Playwright smoke of the web app (see the module docstring).")
    ap.add_argument("--strict", action="store_true", help="a step whose piece is not merged yet fails instead of SKIPping")
    ap.add_argument("-g", "--grep", help="only the tests whose title matches (Playwright's --grep)")
    args = ap.parse_args(argv)
    return demo.with_stack(lambda c: run(c, args.strict, ["--grep", args.grep] if args.grep else []), agent.FULL_CAPS)


if __name__ == "__main__":
    sys.exit(main())
