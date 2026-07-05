---
title: A second on-machine workspace is a full git clone, not a worktree
updated: 2026-07-05
status: proposed
sources: []
---

# A second on-machine workspace is a full git clone, not a worktree

**Decision.** To carry two branches at once on the *same* laptop (a lighter alternative to
rule 09's mac mini), the second workspace is a **full `git clone`** into a sibling folder
(`../paper-degist-02`, its own `.git`), with `origin` **repointed** from the local clone path
to `https://github.com/idisblueflash/paper-degist.git` so push/PR go straight to GitHub —
chosen over `git worktree` (which shares one object store). Full `.git` isolation between the
two checkouts, at the cost of a manual `git fetch` to sync.

**Where it sits relative to rule 09.** A same-machine clone separates the working tree and
terminal but **not the operator** — still one person, one head, one `git commit` from the
wrong tree. Rule 09's mac mini remains the stronger separation (a physically separate
machine). The clone is the right tool only when staying on the laptop, avoiding SSH
round-trips, and keeping the two folders on clearly distinct branches.

**Setup practices that carry (rule-02 encoded gotchas).**

- **`cp -r` is wrong** for duplicating the checkout — it drags the untracked `.venv/` (uv
  venvs can embed absolute paths) and `files/`. Use `git clone` (or `git worktree`) instead.
- **Each checkout runs its own `uv sync`** — the `.venv` is per-folder; `uv.lock` is
  committed (confirmed tracked) so versions match across them.
- **`files/` is untracked** (gitignored) and does not come across a clone/worktree — real
  inputs for an end-to-end run must be copied in manually.

**Sources.** [[session 6e18c177-4542-45e6-aadc-d8b575a1d307]] (second on-machine workspace via full clone).
