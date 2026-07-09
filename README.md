# paper-degist

Discover papers by topic, fetch them, and convert them (PDF/HTML) into Markdown
for an LLM wiki.

Give paper-degist a topic and it searches the literature (arXiv, Semantic
Scholar, OpenAlex, SerpAPI), fetches each paper's file — recovering bot-walled
sources through an open-access or browser lane — and converts the result to
Markdown with provenance frontmatter.

paper-degist is a pipeline of small, independent command-line steps. Each step
does one thing, reads from a file or stdin, writes to stdout, and **never calls
an LLM in its loop** — case-handling knowledge is baked into the script, and an
input the script can't yet handle is quarantined to `manifest.jsonl` instead of
crashing. The whole workflow stays runnable offline and cheap.

## How it works

The pipeline runs one step at a time, piping the output of one into the next:

```
discover → dedup-inputs → fetch-one → convert-html / convert-pdf → collect-papers
                                │
                                └── resolve-oa / browser-fetch  (recovery lanes)
```

- **Discover** candidate papers by topic or seed (arXiv, Semantic Scholar,
  OpenAlex, SerpAPI), then filter, rank, and enrich them.
- **Fetch** each paper's file, recognizing bot-walled sources and recovering
  them through an open-access lane (`resolve-oa`) or a dev-mode browser
  (`browser-fetch`).
- **Convert** HTML or PDF (OCR) into Markdown, then **collect** the converted
  papers with provenance frontmatter (`doi` / `url` / `pdf_url` / `venue`).

Every step is a console script: an unknown input is appended to
`manifest.jsonl` and the step exits cleanly, so a batch always finishes. The
manifest is the queue of cases to handle by hand or as the next code branch.

## Requirements

- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/) for dependency management

## Setup

```bash
uv sync
```

## Usage

Every step runs with `uv run <name>`. List all steps with the signpost:

```bash
uv run paper-degist
```

Run any single step, or see its options:

```bash
uv run parse-url notes.md          # extract URLs from a text file
uv run fetch-one <url>             # fetch one paper's file
uv run convert-html files/<x>.html # HTML → Markdown
uv run <step> --help               # authoritative option list
```

See [`doc/cli-manual.md`](doc/cli-manual.md) for a hand-runnable reference to
every step — what it does, its arguments, and how it composes with the others —
usable with no AI in the loop.

## Development

- **Tests:** `uv run pytest -q` (unit) and `uv run behave` (BDD). Run both
  before committing.
- **Test-first:** red → green → refactor; no production code without a failing
  test driving it.
- **Docs:** [`user-stories.md`](user-stories.md) is the spec index (one file per
  story under [`user-stories/`](user-stories/));
  [`DEVLOG.md`](DEVLOG.md) tracks deferred issues; project conventions live in
  [`.claude/rules/`](.claude/rules/).
