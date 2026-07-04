---
title: browser-up keeps no state file
updated: 2026-07-04
status: verified
sources: []
---

# browser-up keeps no state file

**Decision.** `browser-up` (US 18) does **not** persist a local state file (CDP URL + PID) for
the running Chrome. It classifies on a **live port-reachability probe** and prints the endpoint
to stdout — no discovered state is stored. Confirmed in the repo: `src/paper_degist/browser_up.py`
writes no `.browser-up.state` (or any state file).

**Why.**

- The classify signal is a **live probe** ("is a dev-mode Chrome answering on the CDP port?"),
  which is self-correcting. A state file is *stale* truth — it can claim "running, PID N" after
  Chrome died or the OS recycled the PID, creating two sources of truth that disagree.
- The CDP endpoint is **deterministic configured input** (default `http://localhost:9222`,
  `--cdp` to override), not discovered state — `browser-fetch` attaches with the same
  default/flag, so nothing needs `browser-up` to hand it a discovered URL. Printing is a human
  convenience, not a handoff channel.
- A stored PID's only real uses — **kill / health-check** — are both out of scope: AC 6 leaves
  Chrome running and never kills a browser it didn't start, and "detect/relaunch a stale or
  crashed Chrome" is a named deferred later-stage.
- Honest verification is **re-probing the port**, not reading a file.

**Where a state file would earn its place (future trigger).** When the deferred stale-Chrome
health check is built, a stored PID becomes the natural discriminator for "the Chrome *we*
launched" vs. one the researcher started — i.e. "is it safe for us to recycle this." That is the
rule 02 "new case → new branch" moment to add `.browser-up.state`, not before. Logged as an open
deferred flag in `DEVLOG.md`.

**Sources.** [[session 5a774313-8a20-4405-8679-3b563de41dd4]]. Related:
[[Browser lane CDP fetch mechanism]].
