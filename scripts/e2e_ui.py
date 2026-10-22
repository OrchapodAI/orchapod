"""Playwright smoke of the web app, in STUB mode and $0, on the same stack as e2e_demo.py and e2e_agent.py.

    python scripts/e2e_ui.py [-g REGEX]                # `make ui-smoke`; needs Docker, `make up`, node and pnpm

It rebuilds and retags the shared `orchapod/<node>:dev` images, like `make check E2E=1`, so only the orchestrator runs it, after
merges. It starts the API (STUB=1, throwaway DB, full caps: the UI is anonymous) and `next dev` on the first free port from 3100,
a second API at the public demo's scale (PUBLIC_CAPS) for the public-app tests, builds the node images of the templates it drives
(intent #2 and the golden path; unsloth-train from its stub stage), and runs tests/ui (Playwright, version pinned in
tests/ui/package.json, headless Chromium) against them; Playwright's own report counts the passes.

The tests: /agent intent #2 to a finished report; the template gallery's one-click Run of intent #2 with its dataset card; at
ORCHAPOD_ANON_SCALE=0.1, a template above the per-run cap keeps Run disabled and says why; on the public-scale API, a canvas edit
of a workflow that has runs is refused (409), saved as a copy instead, and leaves the original as it was; the golden path (template 4,
R25: one click, the run of its six nodes, its eval view, the compare playground). Intent #1 is covered through the API by
e2e_agent.py.

A canonical intent whose plan has any error, or a missing template, fails the run before anything is built: a missing piece is
never a SKIP. The golden path is run as its template, as in e2e_agent.py: its plan errors surface when /agent/run refuses it.
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
SPEC_INTENTS = ("2", "4")  # what tests/ui drives: canonical intent #2, and template 4, the golden path (R25)
PLAYWRIGHT_TIMEOUT_S = 570  # tests/ui/playwright.config.ts: globalTimeout 9 min
# The page's own API runs at full scale, so the golden path can run from the gallery; the template cap test reads
# GET /agent/templates from a second API at the public demo's scale, and the canvas copy test sends every call of the page there.
PUBLIC_CAPS = agent.FULL_CAPS | {"ORCHAPOD_ANON_SCALE": "0.1"}


def web_env(api_url: str, environ) -> dict[str, str]:
    """The web app's env: it talks to this API only, and no paid key reaches it."""
    env = {k: v for k, v in environ.items() if k not in demo.PAID}
    return env | {"NEXT_PUBLIC_API_URL": api_url, "NEXT_PUBLIC_WS_URL": api_url.replace("http", "ws", 1),
                  "NEXT_TELEMETRY_DISABLED": "1"}


def playwright_env(web_url: str, api_url: str, public_url: str, environ) -> dict[str, str]:
    """What tests/ui reads: where the app, its API and the public-scale API are, and the slugs of the templates it drives."""
    env = {k: v for k, v in environ.items() if k not in demo.PAID}
    return env | {"E2E_WEB_URL": web_url, "E2E_API_URL": api_url, "E2E_PUBLIC_API_URL": public_url,
                  "E2E_SLUGS": json.dumps({n: agent.SLUGS[n] for n in SPEC_INTENTS})}


def deps_missing() -> list[str]:
    """The installs this run needs (pnpm 11 exits 1 on apps/web with ERR_PNPM_IGNORED_BUILDS: sharp, which is harmless)."""
    return [f"{d.relative_to(ROOT)} has no {tool}: run `make ui-deps`" for d, tool in ((WEB, "next"), (UI, "playwright"))
            if not (d / "node_modules/.bin" / tool).exists()]


def ui_node_types(c: httpx.Client) -> set[str]:
    """The node types of the templates the tests drive, whose images get built. A canonical intent's plan error raises (a failure,
    never a skip); the golden path is its template, as in e2e_agent.py, so the planner is not asked."""
    templates, types = demo.get_templates(c), set()
    for number in SPEC_INTENTS:
        template = agent.canonical(templates, number)
        if template is None:
            raise RuntimeError(f"none of the {len(templates)} templates is {agent.name_of(number)} (slug {agent.SLUGS[number]!r})")
        plan, _, errors = agent.plan_for(c, template["intent"], template, number)
        if errors:
            raise RuntimeError(f"{agent.label_of(number)}: {'; '.join(errors)}")
        types |= {n["type"] for n in plan["nodes"]}
    return types


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
    """SIGTERM the whole process group, give its leader 20 s, then SIGKILL what is left of the group: pnpm exits before the
    node it started."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(20)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # nothing is left
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


def run(c: httpx.Client, extra: list[str]) -> int:
    if problems := demo.preflight() + deps_missing():
        return demo.fail("the stack is not ready:" + "".join(f"\n  - {p}" for p in problems))
    if err := demo.build_images(sorted(ui_node_types(c))):
        return demo.fail(err)
    api_url = str(c.base_url).rstrip("/")
    with tempfile.TemporaryDirectory(prefix="orchapod-ui-") as tmp:
        web, web_url = start_web(api_url, Path(tmp))
        public = None
        try:
            public, public_url = demo.start_api(Path(tmp), PUBLIC_CAPS)  # its own port, DB and api.log in this directory
            demo.wait_healthy(web, web_url, Path(tmp) / "web.log", path="/agent", tries=240)
            demo.wait_healthy(public, public_url, Path(tmp) / "api.log")
            demo.say(f"web up on {web_url} (next dev, API {api_url}; public-scale API {public_url})")
            code = run_playwright(extra, playwright_env(web_url, api_url, public_url, os.environ))
        except RuntimeError as e:
            return demo.fail(e)
        finally:
            stop_group(web)
            if public:
                demo.stop(public)
        if code:
            demo.say(f"web log (last lines):\n{demo.tail(Path(tmp) / 'web.log')}")
    if code:
        return demo.fail(f"playwright exited {code}; traces and screenshots of failures: {UI / 'test-results'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Playwright smoke of the web app (see the module docstring).")
    ap.add_argument("-g", "--grep", help="only the tests whose title matches (Playwright's --grep)")
    args = ap.parse_args(argv)
    return demo.with_stack(lambda c: run(c, ["--grep", args.grep] if args.grep else []), agent.FULL_CAPS)


if __name__ == "__main__":
    sys.exit(main())
