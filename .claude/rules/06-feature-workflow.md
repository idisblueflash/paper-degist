# Rule 06 — Feature workflow (per user story)

**Every user story is processed through the same phased loop: spec →
sample-measured constants → strict red/green → CLI → BDD → DEVLOG → real
end-to-end run → self-review → chunked commits → second-opinion review → CLI
manual → flip status to Done → PR → merge → clean up.**
Each phase ends at a natural checkpoint; do not skip ahead.

This rule is the *process* that rules 01–05 are the *grain* of: it says in what
order to apply the test-first loop (rule 01/05), the classify-then-dispatch
shape (rule 02), the CLI contract (rule 03), and the review-anchoring discipline
(rule 04) when building out a story from `user-stories.md`.

## The phases

### 1. Orient — read before writing
- Find the US in the index [`user-stories.md`](../../user-stories.md), then open
  **only** its own file under `user-stories/` (rule 07) — its acceptance
  criteria *are* the test list, and its "Case handling" section names the
  classify-then-dispatch branches. Don't read the other stories.
- Read [`DEVLOG.md`](../../DEVLOG.md) for deferred flags this US is the trigger
  to fix, plus [`CLAUDE.md`](../../CLAUDE.md) and the other rules.
- Read the nearest **sibling step** and copy its conventions (module shape,
  `_quarantine`, Typer `app`/`main`, test helpers). `convert_html.py` was built
  from `fetch_one.py`.

### 2. Set up ground truth
- Add deps with `uv add` (never bare pip — rule 01).
- If the story needs a threshold or heuristic, **measure a real sample first**
  so the constant is evidence-based, not guessed (the HTML density threshold was
  set against `keyword-method.html`). Copy the sample into `src/tests/samples/`.

### 3. TDD loop — one test at a time (rules 01, 05)
- Pure core function first, then the file-level orchestrator.
- Per fact: write **one** failing test → confirm it fails for the right reason →
  smallest change to green → refactor → next. One logical assertion per test;
  factor shared arrange/act into helpers.
- Build the **classify-then-dispatch** shape (rule 02): each known case a
  branch; the fallthrough **quarantines to `manifest.jsonl`** — never crash,
  never call an LLM. Each quarantine branch earns its own returns-`None` and
  records-reason tests. Quarantine writes go through the shared
  `paper_degist._manifest.append` helper with a `stage` discriminator.

### 4. Make it runnable — rule 03
- Typer `app` + `main(argv) -> int` + `__main__` guard; register the console
  script in `pyproject.toml`; add the step to the root signpost.

### 5. BDD — behave (rule 01)
- One `.feature` per US, Given/When/Then lifted from the AC wording; steps under
  `features/steps/`. Behave shares one step registry across all step
  files — **rename colliding step phrases** rather than redefining them.

### 6. Record what you learned
- Update `DEVLOG.md`: mark deferred flags this US **resolved/addressed**, and log
  **new** deferred cases with location + trigger (rule 02's deferred flags).
- Run both gates before moving on: `uv run pytest -q` **and** `uv run behave`.

### 7. Run it for real — end-to-end on real input
Green fixtures are not proof the step works on the messy real thing. Run the
console script from the shell against a **real** input in `files/` and eyeball
the result before review:
- **Happy path** — run the step (`uv run convert-html files/<real>.html`) and
  read the actual output file, not just its exit code. Confirm the real
  structure survived (headings, tables, links), not just a toy fixture's.
- **Idempotency** — run it a second time; confirm it skips and does not
  overwrite (rule: re-runs stay safe).
- **A quarantine branch** — point it at an input it should reject (e.g. the
  fetched `.pdf`) and confirm it lands in `manifest.jsonl` with the right
  `stage`/`reason` and exits cleanly — never crashes.

This is the step that caught nothing new for US5 only because the sample was
already a fixture; for a story whose real input differs from its fixtures, this
is where the next `DEVLOG` deferred flag (or bug) surfaces. Note that `files/`
is untracked — clean up or keep the generated artifacts deliberately.

### 8. Self-review — `/code-review`
- Fan out finder angles → verify each survivor against the code → fix the real
  findings **test-first**. Anchor any `file:line` finding per rule 04.

### 9. Commit in logical, each-green chunks
- Feature branch off `master` (never commit to `master` directly). Separate a
  self-contained refactor from the feature so each commit passes on its own.
  Sign commits.

### 10. Second-opinion review — Codex
- Hand the branch diff to Codex; fix its findings **test-first**; re-run both
  suites.

### 11. Document the CLI — before opening the PR
- Update [`doc/cli-manual.md`](../../doc/cli-manual.md) so this story's console
  script has a section: what it does, its argument/options, a **happy-path**
  example, a **quarantine** example, and how it composes with the sibling steps.
  Keep it runnable **with no AI in the loop** — a human or Claude Code between
  sessions drives the pipeline from this manual alone. If the story added or
  renamed a flag on an existing step, fix that step's section too.

### 12. Flip status to Done — in the PR branch, before merge
- Flip the US to `✅ Done` in the **Status column of the index**
  [`user-stories.md`](../../user-stories.md) (rule 07 — status lives only there)
  as the **last commit on the feature branch**, so the flip rides this PR and
  merges atomically with the story. **Never a dedicated PR for the status flip,
  and never a direct commit to `master`.**
- This stays honest because the flag lives on the branch: `master` never claims
  a story is Done until the PR actually merges. An open PR can still be revised,
  rejected, or abandoned — and if it is, the Done flip dies with the branch and
  never reaches `master`. So the invariant "`master` only says Done once the code
  is on `master`" holds without a separate post-merge PR.
- Backfill any already-merged story that predates this rule with its own small
  change folded into the next branch that opens — not a dedicated PR.

### 13. Ship
- Final DEVLOG touch-up, commit, push, open the PR with a body that states the
  **review trail** and the deferred follow-ups. Merging this PR lands both the
  story and its `✅ Done` flip on `master` in one merge.

### 14. Clean up — after the merge
Once the PR merges on the remote, sync local and prune the branch in this
**exact order** — the order is a safety interlock, not a preference:

0. **Start from a clean working tree.** Commit or move any unrelated WIP to its
   own branch *first_. Do **not** stash-hop a dirty file across the fast-forward:
   if the stashed file also changed on `master`, the `stash pop` conflicts and
   can silently mangle the file (drop rows/lines) without clean markers.
1. **`git switch master`** — you cannot delete the branch you are standing on.
2. **`git pull --ff-only`** — fast-forward local `master` to the merged state.
   `--ff-only` refuses (loudly) rather than inventing a merge commit if history
   diverged (equivalently: `git fetch --prune` then `git merge --ff-only
   origin/master`; `--prune` also clears stale remote-tracking refs).
3. **`git branch -d <branch>`** — the *safe* delete, and it must come **after**
   step 2: `-d` only removes a branch already contained in the current `HEAD`,
   so pulling first lets `-d` confirm the merge landed. Deleting before the pull
   forces you onto `-D` (force), which discards genuinely-unmerged commits too.
   (Squash-merge repos are the exception: the squashed commit has a new SHA, so
   `-d` refuses and `-D` is expected — this repo uses merge commits, so `-d`
   works.)
4. **`git push origin --delete <branch>`** — only if GitHub's "delete branch on
   merge" did not already remove the remote branch.

The branch list stays scoped to live work and local `master` never lags the
remote, so the next story branches off the real tip instead of a stale one.

## Why

The pipeline's value is that it stays runnable offline, cheap, and
regression-locatable. That only holds if every story is added the same way:
tests before code (so the suite locates regressions), unknowns to the manifest
(so nothing crashes and Claude re-enters exactly once per new case), a CLI entry
(so the step is composable), and two review passes before merge (so
plausible-but-wrong code does not land). The invariant threaded through every
phase: **never crash, never call an LLM in the loop — unknowns go to the
manifest, and the manifest is where the next code branch comes from.**
