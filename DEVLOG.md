# Dev log — deferred flags to revisit

Small, non-blocking issues noticed during development. Each names the code
location, the case not yet handled, and the trigger that should make us fix it.

## parse_url — trailing-punctuation stripping is heuristic

- **Where:** `src/paper_degist/parse_url.py` (`_URL_RE` + `rstrip(".,;")`).
- **Case not handled:** the regex captures up to whitespace or `)`, then strips
  trailing `.,;`. This is correct for URLs that end a sentence, but would wrongly
  strip a trailing `.`/`;`/`,` that is a *real* path or query character. Markdown
  links wrapped in `<...>` and URLs containing a legitimate closing `)` are also
  not handled.
- **Trigger to fix:** the first time a real input URL ends in one of these chars,
  or a `manifest.jsonl` entry shows a mangled URL. Add a failing scenario/unit
  test with that URL, then tighten the regex.
- **Status:** RESOLVED (PR #1 review). `_URL_RE` now matches generously
  (angle-brackets excluded, `re.IGNORECASE`, left-boundary lookbehind against
  embedded schemes) and `_trim_trailing` strips prose punctuation plus only
  *unbalanced* wrapper parens, so `paper_(v2).pdf` survives while `[t](url)`
  loses its wrapper. Balanced-paren, mixed-case, and embedded-scheme cases are
  pinned by unit tests. One residual heuristic remains: a trailing `.` after a
  path (`.../a.`) is still treated as sentence punctuation and stripped — an
  accepted policy, documented by `test_strips_trailing_prose_punctuation_*`.

## parse_url CLI — console entry point (`main`) is not unit-tested

- **Where:** `src/paper_degist/parse_url.py::main`, `src/tests/test_parse_url.py`.
- **Case not handled:** tests exercise `parse_url()` directly; `main([...])`,
  stdin input, one-URL-per-line stdout formatting, and error exit codes are
  unguarded. Deferred by the writer in PR #1 review ("let's not touch this from
  now, consider later").
- **Trigger to fix:** when CLI error handling lands (see the CLI-framework
  decision below), or the first CLI-behavior regression. Add `main`/stdin tests
  via `capsys`/`monkeypatch` plus a missing-file case then.
- **Status:** RESOLVED (Typer adoption PR). `src/tests/test_cli.py` drives the
  step's Typer `app` through `typer.testing.CliRunner`: file argument, stdin
  fallback, one-URL-per-line stdout, and the missing-file path (non-zero exit,
  no traceback). The `capsys`/`monkeypatch` plan is moot — `CliRunner` captures
  stdout and exit codes directly.

## CLI framework — adopt Typer project-wide (deferred to next PR)

- **Where:** every step's CLI surface, starting with
  `src/paper_degist/parse_url.py::main` (raw `open(args.file)` emits tracebacks
  for missing/unreadable files — PR #1 finding r3509869286).
- **Decision:** standardize the pipeline's CLI steps on **Typer** (Click under
  the hood) instead of hand-rolling `argparse` + per-step `try/except`. Typer's
  `Path(exists=True, readable=True)` gives early file validation, clean stderr
  messages, and POSIX exit codes for free, and its `CliRunner` makes `main`
  testable — closing both this finding and the untested-`main` item above with
  one convention. Chosen over a stdlib guard because paper-degist is many
  independent CLI steps that all need identical file-in/stdout-out/clean-error
  behavior.
- **Trigger to fix:** the **next PR** (writer's call — keep PR #1 scoped to
  URL-parsing). Add `typer` via `uv add typer`, refactor `parse-url` onto it as
  the pattern the other steps follow, then apply to `fetch`/`convert`/`import`.
- **Status:** RESOLVED (this PR). `typer` added via `uv add`; both existing CLI
  surfaces refactored onto it — `parse_url` (an `@app.command()` with a
  `typer.Argument(exists=True, dir_okay=False, readable=True)` that validates
  the file up front) and the root `paper_degist` signpost (an
  `invoke_without_command` callback). The convention for the remaining steps:
  a module-level `app = typer.Typer(add_completion=False)`, commands using
  `Annotated[..., typer.Argument(...)]` for validation, and a rule-03
  `main(argv=None) -> int` that delegates to `paper_degist._cli.invoke(app,
  argv)` — the single place that runs the app in standalone mode (clean error
  output) and normalizes the raised `SystemExit` into an int (`None`→0,
  non-int payload→1). Apply the same shape to `fetch`/`convert`/`import` as
  they land.
