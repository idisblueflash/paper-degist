# paper-degist — Project Instructions

A Python script pipeline that converts papers (PDF/HTML) into Markdown for an
LLM wiki. See `user-stories.md` for the spec.

- Spec: [`user-stories.md`](user-stories.md)
- CLI manual (run any step by hand, no AI): [`doc/cli-manual.md`](doc/cli-manual.md)
- Deferred issues to revisit: [`DEVLOG.md`](DEVLOG.md)
- Project rules: [`.claude/rules/`](.claude/rules/)

## Tech stack & conventions

- **Language:** Python.
- **Package management:** `uv`. Add deps with `uv add <pkg>`; run with
  `uv run <cmd>`. Do not use bare `pip` / `venv` / `requirements.txt`.
- **BDD:** `behave`. Each user story's acceptance criteria become `.feature`
  files (Given/When/Then map directly from `user-stories.md`).
- **TDD:** red → green → refactor. Write the failing test/step first, make it
  pass with the smallest change, then refactor. No production code without a
  failing test driving it.

## Design principle (from US 2)

Consolidate case-handling knowledge **into the script**, not into per-run LLM
calls. The script classifies and dispatches deterministically; genuinely novel
cases are quarantined to a manifest (never crash, never call an LLM in the
loop) and become new code branches once. Goal: the workflow stays runnable
offline and cheap.
