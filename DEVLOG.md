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
- **Status:** open. Fine for the current sample blob (9 URLs, all clean).
