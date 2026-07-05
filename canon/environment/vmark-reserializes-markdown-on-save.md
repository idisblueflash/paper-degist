---
title: VMark.app corrupts Markdown by re-serializing open files on save
updated: 2026-07-05
status: verified
sources: []
---

# VMark.app corrupts Markdown by re-serializing open files on save

**What.** VMark.app re-serializes any Markdown file it has open whenever the file is saved,
silently injecting HTML entities (`&#xA;`, `&#x20;`), reflowing tables, and adding stray
bold. This is the root cause of recurring `.md` corruption in the spec files — not
intentional edits. The mitigation is to **close the VMark tab** for a file being edited by
other tooling.

**Confirmed in the repo (HEAD).** The artifact is still present:
`user-stories/us-15-browser-fetch-bot-walled.md:26` reads
`a **new CLI step,&#x20;****` `` browser-fetch `` `****, over a single URL**` — the `&#x20;`
entity and doubled `**` bold are exactly this corruption, committed (landed in `96ac1b9`).
A `git grep '&#x'` sweep is the cheap detector, but it will not catch the reflow/bold damage,
so a committed VMark save needs a fuller diff audit.

**Operational rules that follow.**

- Do **not** stash-hop a VMark-churned file across a fast-forward — if the same file also
  changed upstream, the `stash pop` hits the silent-mangle hazard rule 06 phase 14 step 0
  warns about. Move real WIP to its own branch and **discard** the churn.
- Distinguish churn from work before a PR: a `user-stories.md` table reflow that appears with
  no intended edit is VMark output, and should be dropped from the PR (take the clean
  version), not shipped.

**Sources.** [[session a8521e68-7693-4af4-9f5e-d179bf13c735]] (traced markdown corruption to VMark).
