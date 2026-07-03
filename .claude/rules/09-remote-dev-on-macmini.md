# Rule 09 — Two parallel branches, two machines (develop on the mac mini)

**To carry two branches at once without ever confusing them, put the second one
on the mac mini over SSH — a physically separate machine with its own checkout —
rather than juggling both on one laptop (the MBA). The laptop stays on its own
single branch; the mini is self-sufficient and develops, tests, commits, pushes,
and opens the PR itself, so no code round-trips back to the laptop.**

## Why a second machine, not just a second branch

A local branch switch, or even a git worktree, separates the *files* — but you
are still one operator on one machine, flipping HEAD and mental context, one
`git commit` away from landing work on the wrong branch. Two machines separate
everything that matters: the working tree, the checked-out branch, the terminal,
and the head-space. The laptop is "story A," the mini is "story B," and neither
can leak into the other. **That total separation — not any capability of the
mini — is the reason to reach for it.**

## When to reach for it (and when not)

- **Use it** when you genuinely want two stories in flight at once and kept
  apart: the laptop drives one branch, the mini drives the other, start to
  finish. A useful side benefit — not the motive — is that the mini can also
  host what the laptop cannot (a headed Chrome for the browser-lane stories, an
  always-on long run).
- **Do not use it** for single-focus work or a quick edit. If you are only
  carrying one branch, one machine is simpler; the SSH round-trips buy nothing.
  Reserve the mini for real parallelism, not as a default remote.

## The shape (mirrors the laptop)

- **Connect:** `ssh macmini` (key auth, non-interactive — drivable from the
  shell). Connection details live in the operator's SSH doc, not here; secrets
  never enter the repo.
- **Workspace:** the repo is cloned at `~/Projects/paper-degist`. Toolchain is
  installed **without brew** into `~/.local/bin` (`uv`, `gh`); prefix commands
  with `export PATH="$HOME/.local/bin:$PATH"`. `uv sync` provisions its own
  Python — do not rely on the system one.
- **Edit over SSH:** the laptop's file tools are local-only. Author changes on
  the mini by piping an **exact string-replacement** Python script over SSH
  stdin (`ssh macmini 'cd repo && python3 -' < edit.py`), mirroring a normal
  edit — never a heredoc with Python triple-quotes inside a single-quoted SSH
  argument (the quotes collide).
- **Same gates, same loop:** run `uv run pytest -q` **and** `uv run behave` on
  the mini. The feature workflow (rules 01–08) is unchanged; only the host moves.

## Ship from the mini, not the laptop

- The mini **pushes and PRs itself** — `git push` and `gh pr create`/`merge` run
  there, so the branch never round-trips through the laptop and the laptop's
  checkout stays cleanly on its own branch. If the mini had to hand code back to
  the laptop to ship, the separation would be broken and the laptop would be
  carrying both branches again — the very thing this rule avoids.
- This requires `gh` authenticated in a way a **headless SSH session** can read.
  `gh auth login` stores the token in the macOS login keychain by default, which
  is **locked** in a non-GUI SSH session — gh then reports the token "invalid"
  over SSH even after a good interactive login. Log in with
  `gh auth login --insecure-storage` so the token lands in plaintext
  `~/.config/gh/hosts.yml` (SSH-readable), and wire git's credential helper to
  gh's **absolute path** (`!$HOME/.local/bin/gh auth git-credential`). Verify
  with `gh auth status` over a plain `ssh macmini` before relying on it.

## Why

Parallelism is only real when the two efforts share nothing — not a working
tree, and not the one head and terminal an operator can hold at a time. A second
machine gives both kinds of separation, so two stories advance without either
contaminating the other or landing on the wrong branch. But the split is lost
the moment the mini cannot finish a job on its own: if every push detours
through the laptop, the laptop is back to holding both branches. Hence the rule
is not "you *may* use the mini" but "when you do, the mini is self-sufficient end
to end." The machine changes; the discipline (rules 01–08) does not.
