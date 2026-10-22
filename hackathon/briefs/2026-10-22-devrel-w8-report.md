# devrel-w8 report: fresh-clone fixes to the README (2026-10-22)

**Status:** DONE. The README now fixes all five of the brief's items, and every one was checked against the code or qa-w10's evidence.

**Branch:** `hack/devrel-w8`, base 450389e (`git merge-base --is-ancestor 450389e HEAD` passes). Not pushed.

**Spend:** $0. Bash ran only git and the tests. To count the markers I piped `git grep -o` through `sort | uniq -c`.

## Commits
| SHA | What |
| --- | --- |
| 1a2ffad | docs(readme): the fresh-clone fixes, plus one tests/docs guard |

## Proof
- **TDD.** The new guard `test_a_code_block_starts_the_web_app_on_pnpm_11` requires that one of the README's bash blocks holds `pnpm --config.verify-deps-before-run=false dev`.
  - I stashed my README edit to test the base README: 1 failed, 27 passed. The base had the flag only in prose, which is qa-w10's F1.
  - With my README: 28 passed.
- **`make check`** (no E2E) at 1a2ffad: exit 0.
  - ruff gave `All checks passed!`.
  - pytest gave `1124 passed, 2 warnings`.
  - The web tests gave `tests 36, pass 36, fail 0`.
  - The output ended with `SKIP stub e2e`.
- **Trial merges.** `git merge-tree --write-tree` exits 0 against NebiusHackathon b6accc2 and against hack/frontend-w7.

## The five items
1. **pnpm 11 in the Setup code block (F1).**
   - The block now runs `cd apps/web`, then `pnpm install`, commented that pnpm 11 ends with ERR_PNPM_IGNORED_BUILDS (sharp) and that this is harmless.
   - Then it runs `pnpm --config.verify-deps-before-run=false dev`, commented that without the flag pnpm 11 reruns that install and stops. qa-w10 saw "Ready in 839ms" with that command.
   - The pnpm-11 prose under the block is gone, since it was a duplicate. The `make check PNPM=pnpm` advice for pnpm 9 stays at README:116.
2. **Moving the API off 8001 (F2).** One new paragraph after the block says:
   - Run uvicorn with `--port N`, and put `ORCHAPOD_CONTROL_URL=http://localhost:N` in `.env` before loading it.
   - Start the web app with `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` in front of the `pnpm` command.
   - A wrong control URL fails every run at its first node, with `ConnectionRefusedError` in that node's log.
   - **Checked.** The web defaults are lib/api.ts:7, lib/ws.ts:6 and next.config.ts:5–6. `.env.example:43` sets 8001. The failure mode is qa-w10's F2.
3. **The STUB planner (F4).**
   - **What the README says.** The planner is a stub too: it returns the template whose intent and title share the most words with your sentence. Any sentence gets one of the five plans, and one that shares no word gets the real-estate plan.
   - **Checked.** planner.py:341–342 picks by `max` over word overlap. On a tie, including zero overlap, `max` keeps the first template, and `templates()` sorts by filename (planner.py:73), so `1-real-estate-compliance.json` comes first.
4. **First-run cost (F3).**
   - **Download.** The setup and the first stub run download about 1.8 GB in all and use about 7 GB of disk after the builds. 1.8 GB is qa-w10's estimate from the registry manifests, hence "about".
   - **Timeout.** Each image build may take 600 s, pulls included (e2e_demo.py:286–288), so a slow link can time out on `quantize`.
   - **Time.** With warm caches, a fresh clone reached green in 6 min 38 s.
   - **Readability.** I split the 180-word paragraph in two, so the `make check E2E=1` details start a paragraph of their own.
5. **TODO markers in the opening (F6).**
   - The two top bullets became one "**Status (2026-10-22).**" note with a single TODO(D8): the live golden run, on the topic Hari picks by D6, and the links to the demo, video and Devpost.
   - I folded in README:21's topic TODO, because STATE.md:132 still lists that decision as open. I deleted README:31's status line, which repeated the note.
   - **Removed from the note.** Its TODO(G3) moved out, because Setup still carries it. The "Sections marked TODO(D8)…" sentence went too.
   - **Link.** The note links to [Setup](#setup).
   - **Count.** The README had 29 markers (26 TODO(D8) + 3 TODO(G3)) and now has 24 (22 + 2). Only one comes before "What it is".
   - **Tests.** No tests/docs pin moved, so no test changed except the new guard.

## Not done (outside the brief, or not mine)
- **`.env.example`.** Listing `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_WS_URL` there is platform's file (qa-w10 F2).
- **F6's other suggestions:** a `sed` one-liner for the two `.env` edits, and moving `python scripts/e2e_agent.py --stub` into the code block. The brief did not include them. Each is about one line if you want them.
- **F7's small items** (sidebar "Coming soon", internal ids in rationales, "tuned · tuned", page title) belong to frontend and backend. frontend-w7 takes the sidebar.
