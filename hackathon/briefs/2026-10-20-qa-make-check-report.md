# Report — qa make-check (2026-10-20), as returned by the qa agent

Branch `hack/qa-check` (base ef983ab verified): `60cffe2` ruff.toml + lint fixes in 17 files; `7e77488` ci.yml. 19 files touched, $0, nothing pushed.

`make check` exits 0 (ruff "All checks passed!"); tail:
```
153 passed, 58 warnings in 2.34s
sys:1: RuntimeWarning: coroutine '_terminate_after_ttl' was never awaited
SKIP stub e2e: scripts/e2e_demo.py not written yet (qa)
```
Deviations from the brief: the CI test job also installs `huggingface_hub` and `ruff==0.17.1` on top of the two requirements files (without huggingface_hub 13 container tests fail: 140 passed / 13 failed in a clean scratch venv; with it 153 pass in a scrubbed env). ruff.toml uses `extend-exclude` instead of `exclude` so ruff keeps its default excludes (.venv, .git, …).

Behaviour-touching hand fixes: distill-sft keeps the `subprocess.Popen(...)` call, only `proc =` dropped; `per_call` deleted (pure arithmetic); `_ttl_tasks` moved below the imports in routes/internal.py.

Not fixed (outside the brief): the new synth-distilabel matrix entry will fail at COPY in CI — its Dockerfile copies `sdk/` and `run.py` relative to containers/synth-distilabel/ while CI builds with `context: .`; data-prep, distill-sft, hf-download, lm-eval, quantize and vllm-serve have the same mismatch (`COPY run.py`, `COPY ../../packages/...`); only unsloth-train uses repo-root paths. Suggested DECISION: repo root is the build context everywhere (matches CI, scripts/build-and-push-containers.sh and the local_docker hint); Dockerfile owners switch to `COPY packages/sdk-py/orchapod` and `COPY containers/<node>/run.py`.
