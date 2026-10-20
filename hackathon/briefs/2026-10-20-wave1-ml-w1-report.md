# ml-w1 report — wave 1 (2026-10-20)
Status: DONE · branch `hack/ml-w1` (base 178d2e6 is an ancestor; `git merge-base --is-ancestor 178d2e6 HEAD` = yes) · cost $0 (no API calls, no GPU; Docker Hub and PyPI downloads only) · well inside the 2 h box.

## Commits (never pushed)
- `11978a0` fix(containers): build every image from the repo root (R19)
- `cee5243` fix(lm-eval): drop the Claude judge fallback; Nemotron on Token Factory is the only judge

## Task 1 — R19: every containers/*/Dockerfile builds from the repo root
- 7 Dockerfiles changed (data-prep, distill-sft, hf-download, lm-eval, quantize, vllm-serve: `COPY ../../packages/sdk-py/orchapod` + `COPY run.py`; synth-distilabel: `COPY sdk/` + `COPY run.py`). All now `COPY packages/sdk-py/orchapod …` and `COPY containers/<node>/run.py …`. unsloth-train was already right.
- `containers/synth-distilabel/sdk/` deleted (4 files, 308 lines). `diff -r` against packages/sdk-py/orchapod was empty before the delete.
- Test `tests/containers/test_dockerfiles.py` (per Dockerfile: every COPY/ADD source exists inside the root context and does not escape it; the image copies `packages/sdk-py/orchapod` and its own `containers/<node>/run.py`; plus no `containers/*/sdk` dir).
  - RED before the fix: `17 failed, 4 passed` (7 nodes × 2 checks, vendored sdk, lm-eval ×2). GREEN after: `21 passed` (this file + test_lm_eval.py).
- Doc: README §6 build command (it would have broken: it used `containers/synth-distilabel/` as context) now reads `docker build -t orchapod/synth-distilabel:dev -f containers/synth-distilabel/Dockerfile .`; docs/NODE_CONTRACT.md "Adding a new node" step 1 states the rule and names the test.

### Proof — two CPU images really build (repo root as context)
```
$ docker build -f containers/hf-download/Dockerfile -t orchapod/hf-download:dev .   -> exit 0, 15 s, context sent 16.9 kB
$ docker build -f containers/data-prep/Dockerfile   -t orchapod/data-prep:dev .     -> exit 0, 40 s, context sent 5.3 kB
$ docker run --rm --entrypoint python orchapod/<node>:dev -c "import orchapod, os; ..."   (both images)
orchapod from /app/orchapod/__init__.py
/app: ['orchapod', 'run.py']
sdk files: ['__init__.py', 'checkpoint.py', 'io.py', 'log.py']
```
Image ids: hf-download `3048f86f96a4`, data-prep `c6c993072070` (both left on the host, built from cee5243's tree; data-prep carries the BASE run.py, so rebuild after data-w1 merges).

### Extra cross-check — the other six images (CUDA/vLLM bases, not built)
COPY-only dry build (busybox base, only the COPY/ADD lines of each Dockerfile, repo-root context): `OK` for all 8 (data-prep, distill-sft, hf-download, lm-eval, quantize, synth-distilabel, unsloth-train, vllm-serve). The same dry build of the ORIGINAL data-prep, synth-distilabel and vllm-serve Dockerfiles fails with `"/run.py": not found`, so the technique and the unit test agree with real Docker.

## Task 2 — lm-eval: Claude/Anthropic fallback deleted
- `containers/lm-eval/run.py`: `_judge_via_anthropic`, the `ANTHROPIC_API_KEY` branch and the `use_claude` logic are gone (-34/+7 lines). Without NEBIUS_API_KEY the LLM judge is skipped (`judge: "none"`). The `anthropic` pip package is out of the Dockerfile. `grep -i "anthropic\|claude" containers/lm-eval/*` is empty.
- Test `tests/containers/test_lm_eval.py` (3): an Anthropic key alone starts no judge (it failed RED with "ran a judge on ANTHROPIC_API_KEY"); the Nebius judge path still scores (guard for the branch I edited); the Dockerfile has no anthropic (failed RED).
- Not changed (out of scope): lm-eval still calls the legacy `api.studio.nebius.ai` host through urllib, and still keeps `openai` in its pip line (vLLM needs it). lm-eval leaves the demo path; judge-eval replaces it in wave 2.

## Gate
`make check` on cee5243, tree clean: `All checks passed!` (ruff) and `174 passed, 58 warnings` (baseline was 153 passed, 58 warnings), exit 0. The stub e2e line still prints SKIP (qa's script not written).

## Open items for the Orchestrator (none block this branch)
1. DECISION to record: R19 is done and enforced by `tests/containers/test_dockerfiles.py`; lm-eval has no judge provider other than Nemotron on Token Factory.
2. Merge note: my README hunk (lines 166-167) will conflict with devrel-w1's README rewrite if it keeps §6; take theirs and drop the section or keep my two lines. I did not touch CHANGELOG.md (every branch would append to the same hunk); suggested lines: "every node image builds from the repo root; lm-eval no longer has a Claude judge fallback".
3. Still non-Nebius in images, not mine this wave: `containers/synth-distilabel/Dockerfile` still `pip install … openai anthropic` and its run.py keeps `teacher_kind` (data-eng, wave 2, with R12's jsonschema). `.env.example:44-47` still says ANTHROPIC_API_KEY is "required for lm-eval Claude-as-judge" and `infra/docker-compose.dev.yml:84` still passes it (contracts Config removes both; platform's `.env.example` rewrite covers the first, nobody in wave 1 is named for compose).
4. Dockerfile lines the contracts want but no code needs yet: `COPY packages/providers /app/packages/providers` + `pip install httpx` (add with the first run.py that imports packages.providers; the new test checks any added source automatically) and vllm-serve's `FROM …:latest` pin and cloudflared removal (my wave-2 vllm-serve rewrite).
5. No `.dockerignore` exists. BuildKit (Docker 28.1.1, CI's buildx) only sent 5-17 kB for the root context, so none was added; the legacy builder would upload the whole repo.
6. `scripts/build-and-push-containers.sh` still lists only 6 nodes (no hf-download, no synth-distilabel) and defaults to `GITHUB_ORG:-orchapod`; ponytail audit item 12 deletes it in favour of the CI matrix (qa/platform).
7. Commit trailer: I used the role file's "Co-Authored-By: Claude Opus 5.5" (the harness reminder named Sonnet 5.5; the role file is the project rule). Amend at merge if you prefer the other.
8. No GPU was rented, so there is no vast.ai instance to check.
