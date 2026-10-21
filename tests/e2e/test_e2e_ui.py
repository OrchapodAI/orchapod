"""scripts/e2e_ui.py and tests/ui: the logic around the Playwright smoke. The smoke itself is `make ui-smoke` (Docker, `make up`)."""

import json
import os
import re
import signal
import subprocess
import time
from pathlib import Path

import e2e_agent as agent
import e2e_ui as ui
import pytest

from tests.e2e.test_e2e_agent import ERRORS_1, I1, I2, fake_api

ROOT = Path(__file__).resolve().parents[2]
SHELL = {"PATH": "/usr/bin", "NEBIUS_API_KEY": "secret", "TAVILY_API_KEY": "secret", "HF_TOKEN": "secret", "VASTAI_API_KEY": "secret"}


def test_web_env_points_at_the_api_and_carries_no_paid_key():
    env = ui.web_env("http://127.0.0.1:8003", SHELL)
    assert env["NEXT_PUBLIC_API_URL"] == "http://127.0.0.1:8003" and env["NEXT_PUBLIC_WS_URL"] == "ws://127.0.0.1:8003"
    assert env["PATH"] == "/usr/bin"
    assert not {"NEBIUS_API_KEY", "TAVILY_API_KEY", "HF_TOKEN", "VASTAI_API_KEY"} & set(env)


def test_playwright_env_says_where_the_app_is_what_cannot_run_and_whether_that_fails():
    env = ui.playwright_env("http://127.0.0.1:3100", "http://127.0.0.1:8003", {"1": ["ml-w4: vllm-serve"]}, True, SHELL)
    assert env["E2E_WEB_URL"] == "http://127.0.0.1:3100" and env["E2E_API_URL"] == "http://127.0.0.1:8003"
    assert json.loads(env["E2E_PENDING"]) == {"1": ["ml-w4: vllm-serve"]} and env["E2E_STRICT"] == "1"
    assert json.loads(env["E2E_SLUGS"]) == {"1": "real-estate-compliance", "2": "movie-engagement"}  # the spec drives these two
    assert ui.playwright_env("w", "a", {}, False, SHELL)["E2E_STRICT"] == ""  # blank, so `=== "1"` is false
    assert not {"NEBIUS_API_KEY", "TAVILY_API_KEY", "HF_TOKEN", "VASTAI_API_KEY"} & set(env)


def test_the_spec_and_the_config_read_exactly_what_the_driver_sets():
    """tests/ui is TypeScript and the driver is Python: a renamed variable on one side must not silently break the other."""
    text = "".join((ROOT / "tests/ui" / f).read_text() for f in ("smoke.spec.ts", "playwright.config.ts"))
    assert set(re.findall(r"process\.env\.(E2E_\w+)", text)) == set(ui.playwright_env("w", "a", {}, False, {}))


def test_playwright_is_pinned_and_locked():
    """pnpm install --frozen-lockfile (make ui-deps) fails when package.json and the lockfile disagree; the pin also fixes
    the browser build (1.63.0 = Chromium 1243)."""
    pinned = json.loads((ROOT / "tests/ui/package.json").read_text())["devDependencies"]["@playwright/test"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", pinned), f"{pinned}: pin an exact version"
    lock = (ROOT / "tests/ui/pnpm-lock.yaml").read_text()
    assert f"specifier: {pinned}" in lock and f"'@playwright/test@{pinned}':" in lock


def test_deps_missing_names_each_install(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "WEB", tmp_path / "apps/web")
    monkeypatch.setattr(ui, "UI", tmp_path / "tests/ui")
    monkeypatch.setattr(ui, "ROOT", tmp_path)
    problems = ui.deps_missing()
    assert len(problems) == 2 and all("make ui-deps" in p for p in problems)
    assert "apps/web has no next" in problems[0] and "tests/ui has no playwright" in problems[1]
    for d, tool in ((ui.WEB, "next"), (ui.UI, "playwright")):
        (d / "node_modules/.bin").mkdir(parents=True)
        (d / "node_modules/.bin" / tool).touch()
    assert ui.deps_missing() == []


def test_ui_pending_names_the_gaps_and_the_node_types_that_will_run():  # SKIP-SITE(ml-w4)
    api = fake_api({I1["intent"]: ERRORS_1})
    pending, types = ui.ui_pending(api)
    assert pending == {"1": [agent.VLLM]}
    assert types == {n["type"] for n in I2["plan"]["nodes"]}  # only the intent that runs needs its images
    pending, types = ui.ui_pending(fake_api())  # nothing missing: both run
    assert pending == {} and {n["type"] for n in I1["plan"]["nodes"]} <= types


def test_ui_pending_never_hides_an_error_that_is_not_a_named_gap():
    with pytest.raises(RuntimeError, match="intent #1: serve: unknown input 'bogus'"):
        ui.ui_pending(fake_api({I1["intent"]: ["serve: unknown input 'bogus'"]}))
    with pytest.raises(RuntimeError, match="intent #2"):  # intent #2 is the one that must always run
        ui.ui_pending(fake_api({I2["intent"]: ["synth: unknown input 'bogus'"]}))


def group(pgid: int) -> list[int]:
    done = subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True, text=True)
    return [int(pid) for pid in done.stdout.split()]


def until(condition, seconds: float = 20) -> bool:
    """Polls: a loaded machine takes seconds for what takes milliseconds on an idle one."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False


def test_stop_group_ends_the_server_and_everything_it_started():
    """`pnpm exec next dev` is pnpm, node and more: killing only the first would leave a dev server on its port."""
    proc = subprocess.Popen(["sh", "-c", "sleep 60 & sleep 60 & wait"], start_new_session=True)
    pgid = os.getpgid(proc.pid)
    assert until(lambda: len(group(pgid)) == 3), "the shell and its two sleeps should be one process group"
    ui.stop_group(proc)
    if not until(lambda: not group(pgid)):  # the orphaned sleeps are reaped by init a moment later
        os.killpg(pgid, signal.SIGKILL)
        pytest.fail("part of the process group survived stop_group")
    ui.stop_group(proc)  # already gone: no error


def test_stop_group_kills_what_outlives_the_leader_and_ignores_sigterm():
    """pnpm exits on SIGTERM before the node it started; a child that ignores SIGTERM would be left behind without the SIGKILL."""
    proc = subprocess.Popen(["sh", "-c", "(trap '' TERM; exec sleep 60) & exit 0"], start_new_session=True)  # the leader exits at once
    pgid = os.getpgid(proc.pid)
    assert until(lambda: proc.poll() == 0 and group(pgid)), "the leader has gone and its child lives"
    ui.stop_group(proc)
    if not until(lambda: not group(pgid)):
        os.killpg(pgid, signal.SIGKILL)
        pytest.fail("a child that ignores SIGTERM survived stop_group")


def test_run_playwright_returns_its_exit_code(monkeypatch):
    monkeypatch.setattr(ui, "PNPM", ["sh", "-c", "exit 3", "pnpm"])  # the rest of the command line becomes sh's arguments
    assert ui.run_playwright([], {"PATH": "/usr/bin:/bin"}) == 3


def test_run_playwright_that_outlives_its_timeout_is_stopped_with_its_children(monkeypatch, tmp_path):
    marker = tmp_path / "child.pid"

    class Outlives(subprocess.Popen):
        """The first wait is run_playwright's timeout: let the child start, then say that the time is up."""
        asked = False

        def wait(self, timeout=None):
            if not Outlives.asked:
                Outlives.asked = True
                assert until(lambda: marker.exists() and marker.read_text().strip()), "the child never started"
                raise subprocess.TimeoutExpired(self.args, timeout)
            return super().wait(timeout)

    monkeypatch.setattr(ui.subprocess, "Popen", Outlives)
    monkeypatch.setattr(ui, "PNPM", ["sh", "-c", f"sleep 60 & echo $! > {marker}; wait", "pnpm"])
    with pytest.raises(RuntimeError, match=f"took over {ui.PLAYWRIGHT_TIMEOUT_S} s and was stopped"):
        ui.run_playwright([], {"PATH": "/usr/bin:/bin"})
    child = int(marker.read_text())

    def alive() -> bool:
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            return False
        return True

    if not until(lambda: not alive()):  # a browser started by playwright is such a child
        os.kill(child, signal.SIGKILL)
        pytest.fail("the child of the stopped playwright is still running")
