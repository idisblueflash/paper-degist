# Rule 03 — Every step is CLI-runnable

**Each pipeline step is invokable from the command line so it can be run in the
workflow — by a human or by Claude Code — without importing it as a library.**

## Requirements

- Every step module exposes a `main(argv=None) -> int` and an
  `if __name__ == "__main__": raise SystemExit(main())` guard.
- Register it as a console script in `pyproject.toml` under
  `[project.scripts]` (e.g. `parse-url = "paper_degist.parse_url:main"`), so
  `uv run <name>` works.
- Read input from a file argument, falling back to stdin; write results to
  stdout (one record per line where natural). This makes steps pipeable.

## Why

The pipeline must be driveable step by step from the shell. A step that only
exists as a Python function cannot be run in the workflow or invoked by Claude
between sessions; a CLI entry point keeps every step independently runnable and
composable (`fetch → convert → import` as piped commands).
