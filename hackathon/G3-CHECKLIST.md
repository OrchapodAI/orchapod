# G3 checklist — the freeze (Oct 27 evening) and what the judging window needs

A box is something that must be true before `git tag -a v0.1-hackathon` is pushed. "Hari" marks a human step; everything
else the orchestrator runs and logs in LOG.md with its output.

### A. Code and tests (orchestrator)
- [ ] Every agent branch is merged or dropped. `git worktree list` shows only the main checkout; `git status` is clean.
      (10-27 12:55Z: true at 8b9ab39; check again at the tag.)
- [ ] `make check E2E=1` is green on the tag commit: pytest, web tests, ruff, the stub e2e, and the golden path through the Agent.
- [ ] `make ui-smoke` 5/5 on the tag commit. (10-27 12:54Z at 8b9ab39, after Docker Desktop's pulls came back at 12:50Z:
      `make check E2E=1` exit 0: ruff clean, 1180 passed, web 51/51, the stub e2e and 4 PASS; `make ui-smoke` 5/5 in 33 s.
      Run both again on the tag commit.)
- [x] qa-w11's fresh-clone retest is green, with its fixes merged (hackathon/briefs/2026-10-25-qa-w11-report.md).
      (Green in 3 min 35 s, 10-25 10:11Z; its frictions fixed by wave 8, merged and deployed c5eab1f 10:22Z.)
- [x] The security review's critical and high findings are fixed. Its medium ones are fixed or triaged in STATE.md
      (hackathon/briefs/2026-10-25-security-review.md). (0 critical; H1 and M1 refuted with evidence, the lows accepted or
      parked: LOG 2026-10-25T09:52Z.)
- [ ] `gitleaks git --redact --log-opts=--all` is clean; each false positive is listed in .gitleaksignore with its reason.
      (10-27 06:22Z: 832 commits, no leaks; run again on the tag commit.)

### B. Hosted demo (orchestrator)
- [ ] deploys.log on the VM ends with the tag commit; `https://api.orchapod.dev/health` is ok; `https://app.orchapod.dev/agent` is 200.
- [ ] Both live golden runs (d20d30f3, 0ee1e20a) open, with logs, eval, report and an honest expired Compare tab.
      (10-27 ~06:25Z: both succeeded, 6/6 nodes, logs, eval and reports; check again after the tag's deploy.)
- [x] Anonymous, after 00:00 UTC (the public share resets): the golden sentence plans to six nodes marked admin-only, with the
      golden-run link, and the movie template runs to its dataset card. That spends the public's share, cents.
      (10-27 12:02Z on 4c1f7a6, after the 12:00Z reset: PASS, movie run e1f1b8b2 $0.006. Re-run only if a later deploy changes code.)
- [ ] No Nebius GPU resource is left: `nebius ai endpoint list` and `nebius ai job list` are empty. (10-27 ~06:25Z: 0 and 0,
      listed through the hosted API's client; check again at the tag.)
- [ ] No admin runs on the hosted app from here on (docs/HOSTING.md): admin spend uses up the public's day share.

### C. Docs (devrel, then orchestrator)
- [x] README and docs/devpost.md: TODO(D8) remains only for the video link and the Devpost link. The status note is current.
      (devrel-w13, merged 2b893b3. Ruling: devpost.md's submission-day TODO(D8)s stay as Hari's D8 checks: links logged out, the
      pages feedback.md cites, the paste. The TODO(G3)s at README:114, README:156 and devpost.md:66 are cleared in E.)
- [x] CHANGELOG.md has every user-facing change up to the tag. (Up to 2b893b3; tests/docs now fails if a CHANGELOG date has no
      bullet in the README or Devpost list.)
- [x] docs/feedback.md is ready to paste into Devpost. (5 sourced "what worked well" bullets, one question per finding, no TODO;
      tests/docs enforces it.)

### D. Hari
- [ ] Keys rotated (Token Factory, Tavily, the Nebius service-account keys, the storage key) before the repo is public. The
      new values go only into .env and the VM's /opt/orchapod/.env, then `dc up -d api`. The hosted day cap is unchanged.
- [ ] docs/Jira.csv reviewed for personal data (or removed).
- [ ] The repo made public (bangadpurva/orchapod.ai). GitHub's default branch is main (pre-hackathon code): Purva switches it to
      NebiusHackathon, or Devpost links the branch.
- [ ] The video: the voice-over on footage/video-draft's cut (or a re-record), uploaded public on YouTube, under 3:00.
- [x] The judging-window day cap: ORCHAPOD_MAX_DAY_USD=20 from Oct 29 (Hari, 2026-10-25). The VM's orchapod-daycap.timer applies it at 00:00 UTC.
      After it fires, check: `sudo grep MAX_DAY /opt/orchapod/.env` and `systemctl status orchapod-daycap.service`.
- [ ] Devpost submitted by Oct 29, 6 PM ET, every link checked logged out.

### E. The tag (orchestrator, after A–C and Hari's yes on D's repo step)
First clear the TODO(G3) markers (README:114 private repo, README:156 GHCR packages, docs/devpost.md:66) to match what Hari
and Purva made public. Then `git tag -a v0.1-hackathon -m "Nebius × NVIDIA hackathon submission"` on the tested commit, then `git push origin v0.1-hackathon`.
Never move the tag. A later fix gets a new tag.
