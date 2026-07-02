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

## fetch_one — redirect hop cap (US2 AC5) not explicitly bounded

- **Where:** `src/paper_degist/fetch_one.py::_default_fetch`.
- **Case not handled:** AC5 says "follow it (cap the hops)". `_default_fetch`
  passes `follow_redirects=True` to `httpx.get`, which follows up to httpx's
  own default `max_redirects` (20) — the hop cap is implicit, not a stated
  policy of ours, and the re-classify-final-response behavior is untested
  (tests inject a fake fetch, so no redirect chain is exercised).
- **Trigger to fix:** when a real input redirects (or loops) and we want a
  tighter/explicit cap, or when adding an integration test that exercises a
  live redirect. Set an explicit `httpx.Client(max_redirects=...)` and add a
  scenario then.
- **Status:** OPEN.

## fetch_one — JS-rendered HTML may be saved as a thin/empty shell

- **Where:** `src/paper_degist/fetch_one.py::classify` (the `text/html` branch)
  and `_default_fetch`.
- **Case not handled:** `_default_fetch` does a plain `httpx.get` with no JS
  execution. For a client-rendered SPA (Next.js/React/etc.), the response can be
  a near-empty shell whose real content only appears after client-side
  hydration. `classify` sees a valid `text/html` body and saves it as a
  legitimate `.html`, so a content-thin page passes as success rather than being
  quarantined. Observed live on `https://keymagine.app/keyword-method` — a
  Next.js app (`_next/static/...`); that particular page did carry its content
  inline, so it was fine, but the shape is the risk.
- **Trigger to fix:** the first time the convert step yields near-empty Markdown
  from a saved `.html`, or a real input SPA returns a hollow shell. Add an
  "HTML too thin" signal (e.g. text-density / body-length threshold, or a
  `<div id="__next"></div>`-empty check) that quarantines to `manifest.jsonl`
  with that reason, driven by a failing test on a captured hollow-shell fixture.
  Now specified as US 5 AC2 in `user-stories.md`.
- **Status:** ADDRESSED at the convert stage (US 5). `convert_html` measures the
  extracted Markdown's non-whitespace character count and quarantines anything
  below `_MIN_CONTENT_CHARS` (200) to `manifest.jsonl` with reason
  `"HTML too thin"` — a hollow `<div id="__next"></div>` yields 0 non-ws chars,
  a real paper thousands (the captured `keyword-method.html` sample: 7623).
  `fetch_one` still *saves* the shell (it cannot tell inline-rendered from
  hollow without converting); the thin-shell judgment now lives one stage later
  where the Markdown makes it cheap and deterministic.

## convert_html — density threshold is a fixed char count, not a ratio

- **Where:** `src/paper_degist/convert_html.py` (`_MIN_CONTENT_CHARS`,
  `_content_chars`).
- **Case not handled:** the "too thin" signal is an absolute non-whitespace
  character count (200). A genuinely short-but-real note under 200 chars would
  be quarantined as a false positive, and a hollow shell that happens to inline
  200+ chars of boilerplate nav/footer would pass. A text-density *ratio*
  (content chars / raw HTML bytes) or a boilerplate strip would be more robust.
- **Trigger to fix:** the first real paper wrongly quarantined as thin, or a
  hollow shell wrongly saved. Add the offending fixture as a failing test, then
  switch to a ratio or add a boilerplate-strip pass.
- **Status:** OPEN.

## convert_html — non-UTF-8 HTML is quarantined, not transcoded

- **Where:** `src/paper_degist/convert_html.py::convert_html` (the
  `read_text(encoding="utf-8")` guard).
- **Case not handled:** a file whose bytes are not valid UTF-8 (e.g. a page
  served as `charset=iso-8859-1`) would have crashed with `UnicodeDecodeError`;
  it is now caught and quarantined with reason `"undecodable HTML (not UTF-8)"`
  so the batch finishes (rule 02: never crash). We do **not** yet sniff the
  declared charset or transcode — a real Latin-1 paper is quarantined rather
  than converted.
- **Trigger to fix:** the first real input quarantined for this reason. Add a
  branch that reads the `<meta charset>` / HTTP charset and decodes with it
  (falling back to `errors="replace"`), driven by a failing test on a captured
  non-UTF-8 fixture.
- **Status:** OPEN.

## convert stage — extension dispatcher (.pdf vs .html) not built yet

- **Where:** the convert stage as a whole; only `convert_html` (the `.html`
  branch) exists.
- **Case not handled:** US 5's case handling says the convert stage dispatches
  by file extension — `.pdf` → the PDF path (US 3 + US 4), `.html` →
  `convert_html` — both converging on `files/<name>.md`. Only the `.html` branch
  is built; there is no top-level `convert` entry point that classifies by
  extension and dispatches, because the PDF path (US 3/US 4) does not exist yet.
- **Trigger to fix:** when US 3/US 4 land. Add a `convert` step that classifies
  by suffix and dispatches to `convert_html` or the PDF path, mirroring
  `fetch_one`'s Content-Type dispatch; quarantine unknown extensions.
- **Status:** OPEN.

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
