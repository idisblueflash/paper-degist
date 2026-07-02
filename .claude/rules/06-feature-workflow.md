# Rule 06 — Feature workflow (per user story)

**Every user story is processed through the same phased loop: spec →
sample-measured constants → strict red/green → CLI → BDD → DEVLOG → real
end-to-end run → self-review → chunked commits → second-opinion review → PR.**
Each phase ends at a natural checkpoint; do not skip ahead.

This rule is the *process* that rules 01–05 are the *grain* of: it says in what
order to apply the test-first loop (rule 01/05), the classify-then-dispatch
shape (rule 02), the CLI contract (rule 03), and the review-anchoring discipline
(rule 04) when building out a story from `user-stories.md`.

## The phases

### 1. Orient — read before writing
- Read the US in [`user-stories.md`](../../user-stories.md); its acceptance
  criteria *are* the test list, and its "Case handling" section names the
  classify-then-dispatch branches.
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

### 11. Ship
- Final DEVLOG touch-up, commit, push, open the PR with a body that states the
  **review trail** and the deferred follow-ups.

## Why

The pipeline's value is that it stays runnable offline, cheap, and
regression-locatable. That only holds if every story is added the same way:
tests before code (so the suite locates regressions), unknowns to the manifest
(so nothing crashes and Claude re-enters exactly once per new case), a CLI entry
(so the step is composable), and two review passes before merge (so
plausible-but-wrong code does not land). The invariant threaded through every
phase: **never crash, never call an LLM in the loop — unknowns go to the
manifest, and the manifest is where the next code branch comes from.**
