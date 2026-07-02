# Rule 01 — Tech stack & test-first workflow

**Python + uv + behave (BDD) + pytest (unit), driven test-first.**

## Stack

- **Language:** Python (`requires-python >=3.11`).
- **Packages:** `uv`. Add with `uv add <pkg>` (dev deps: `uv add --dev <pkg>`);
  run with `uv run <cmd>`. Never bare `pip` / `venv` / `requirements.txt`.
  Commit `uv.lock`.

## Two test layers

- **BDD — `behave`.** Each user story's acceptance criteria in
  `user-stories.md` map to a `.feature` file under `features/`, with steps in
  `features/steps/`. Given/When/Then come straight from the AC wording.
- **Unit — `pytest`.** Fast, isolated tests under `src/tests/`. Configured via
  `[tool.pytest.ini_options]` (`pythonpath=["src"]`, `testpaths=["src/tests"]`).
- Shared sample/fixture data lives under `src/tests/samples/`.

## TDD loop (non-negotiable order)

**red → green → refactor.** Write the failing test/step first, confirm it
fails for the right reason, make it pass with the smallest change, then
refactor. No production code without a failing test driving it.

Run both suites before committing: `uv run pytest -q` and `uv run behave`.
