# Brief — make check green (2026-10-20) · agent: qa
Worktree: /Users/hari/src/orchapod-hack/.claude/worktrees/qa-check (branch hack/qa-check, base NebiusHackathon @ ef983ab). Do not dispatch subagents.

## Why now
`make check` (ruff + pytest + stub e2e) is the merge gate. Today pytest passes (153) but ruff fails: ruff 0.17's built-in default rule set is broad (168 findings) and the repo has no ruff config. This lands before the D1–D2 coding wave so every agent branches from a green base.

## Task
1. Add a repo-root ruff.toml: target-version "py312"; [lint] select = ["E4", "E7", "E9", "F"]; exclude apps/web and node_modules. Nothing else.
2. Fix the 30 findings that remain (`ruff check apps packages containers`), minimal and behaviour-preserving: `ruff check --fix` for the safe fixes, hand-fix the rest; for F841 remove the unused assignment unless the call has a side effect. One-time exception to the ownership map, ruled by the Orchestrator: you may touch any file, for these lint fixes only.
3. CI (.github/workflows/ci.yml): the test job runs `ruff check apps packages containers` and `python -m pytest tests -q` on Python 3.12, installing from requirements-dev.txt and apps/api/requirements.txt; add synth-distilabel to the container build matrix. Leave everything else as it is.
4. Prove it: `make check` passes in your worktree with the shared venv activated (it prints the SKIP line for the stub e2e; that is expected).

## Done when
`make check` exits 0 and pytest still reports 153 passed. Commits on hack/qa-check. Final message at most 10 lines: branch, SHAs, the last 5 lines of `make check`, number of files touched, anything you could not fix safely.
