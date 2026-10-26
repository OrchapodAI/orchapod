# G3 checklist — the freeze (Oct 27 evening) and what the judging window needs

A box is something that must be true before `git tag -a v0.1-hackathon` is pushed. "Hari" marks a human step; everything
else the orchestrator runs and logs in LOG.md with its output.

### A. Code and tests (orchestrator)
- [ ] Every agent branch is merged or dropped. `git worktree list` shows only the main checkout; `git status` is clean.
- [ ] `make check E2E=1` is green on the tag commit: pytest, web tests, ruff, the stub e2e, and the golden path through the Agent.
- [ ] `make ui-smoke` 5/5 on the tag commit.
- [ ] qa-w11's fresh-clone retest is green, with its fixes merged (hackathon/briefs/2026-10-25-qa-w11-report.md).
- [ ] The security review's critical and high findings are fixed. Its medium ones are fixed or triaged in STATE.md
      (hackathon/briefs/2026-10-25-security-review.md).
- [ ] `gitleaks git --redact --log-opts=--all` is clean; each false positive is listed in .gitleaksignore with its reason.

### B. Hosted demo (orchestrator)
- [ ] deploys.log on the VM ends with the tag commit; `https://api.orchapod.dev/health` is ok; `https://app.orchapod.dev/agent` is 200.
- [ ] Both live golden runs (d20d30f3, 0ee1e20a) open, with logs, eval, report and an honest expired Compare tab.
- [x] (2026-10-26 00:11Z on dfe67d7; re-run only if a deploy follows) Anonymous, after 00:00 UTC (the public share resets): the golden sentence plans to six nodes marked admin-only, with the
      golden-run link, and the movie template runs to its dataset card. That spends the public's share, cents.
- [ ] No Nebius GPU resource is left: `nebius ai endpoint list` and `nebius ai job list` are empty.
- [ ] No admin runs on the hosted app from here on (docs/HOSTING.md): admin spend uses up the public's day share.

### C. Docs (devrel, then orchestrator)
- [ ] README and docs/devpost.md: TODO(D8) remains only for the video link and the Devpost link. The status note is current.
- [ ] CHANGELOG.md has every user-facing change up to the tag.
- [ ] docs/feedback.md is ready to paste into Devpost.

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
`git tag -a v0.1-hackathon -m "Nebius × NVIDIA hackathon submission"` on the tested commit, then `git push origin v0.1-hackathon`.
Never move the tag. A later fix gets a new tag.
