# Brief — fresh-clone fixes (2026-10-22) · devrel-w8 + frontend-w7 · base: NebiusHackathon @ the SHA in your dispatch
Source: hackathon/briefs/2026-10-22-qa-w10-report.md. A new user cloned the repo and followed the README; these are the frictions it hit.
Common rules: hackathon/briefs/2026-10-21-wave2.md "Common rules". Report to hackathon/briefs/2026-10-22-<name>-report.md; final message ≤ 8 lines.
The MinIO P0 is fixed (2b3cbce: pgsty/minio pinned by digest).

## devrel-w8 — README.md
Each change is small. Keep sentences plain and short.
1. **Setup code block (README ~137-138).** On pnpm 11, `pnpm install` exits 1 with ERR_PNPM_IGNORED_BUILDS (sharp), and a plain `pnpm dev` then dies. Put the working commands in the code block itself: `pnpm --config.verify-deps-before-run=false dev`, and the same for install if needed. Prose alone isn't enough.
2. **Ports (README ~134).** Say how to move the API off 8001. Set `ORCHAPOD_CONTROL_URL` in `.env`, and `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_WS_URL` for `pnpm dev`. Say also that a wrong `ORCHAPOD_CONTROL_URL` makes runs fail at their first node.
3. **STUB (README ~125).** With `STUB=1`, the planner answers with the closest of the five templates, so any other sentence gets one of them (often real estate).
4. **First run (README ~121).** It downloads about 1.8 GB (postgres, redis, minio, base images; about 7 GB on disk after the builds). Warm caches went from clone to green in 6 min 38 s (qa-w10).
5. **The opening's TODO markers.** qa-w10 counted 29. Fold the status ones near the top into one short "Status (2026-10-22)" note with a single TODO(D8). Leave any TODO that tests/docs pins, and adjust those tests only where a sentence moves.

## frontend-w7 — apps/web
1. **/agent plan card.** After a plan arrives, scroll the plan card into view (`scrollIntoView({block: "nearest"})`). At 1024×768 it renders about 150 px below the five template cards, so nothing seems to happen. Add one test if a pure function exists; otherwise give the browser check in your report.
2. **Sidebar.** 3 of the 10 sidebar pages say "Coming soon". Remove those links so judges never land on an empty page. Keep the routes if other pages link to them; otherwise delete the pages too. Shortest diff. A test asserts no sidebar link leads to a "Coming soon" page.

Acceptance: `make check` (no E2E) green, plus `pytest tests/docs` (devrel) and the web tests and tsc (frontend). Don't run the e2e or the smoke. Spend $0.
