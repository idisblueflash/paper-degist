# US 37 Provenance frontmatter on each collected paper

As a *researcher staging converted papers into a wiki*, i want *each paper's
`.md` to carry a YAML frontmatter block with its `doi`, landing `url`, `pdf_url`,
and `venue`*, so that *every collected paper is self-describing — its durable
citation and download provenance travel with the file, not just its body text*.

## Background

By convert time the pipeline has already lost the paper's provenance. `fetch-one`
(US2) saves the source file by URL basename and **discards the URL**; the convert
steps (US3/US5) only see the local file; `collect-papers` (US36) copies the
`.md` out of `files/<topic>/` with no knowledge of where it came from. Yet the
discover candidate records (US25) *do* carry the provenance — `doi`, `url`,
`pdf_url` — and OpenAlex additionally carries the `venue`.

This story threads that provenance through to the `.md`:

```
fetch-batch candidates.jsonl   → files/<topic>/<stem>.<ext>  +  <stem>.meta.json
convert-html / convert-pdf     → reads <stem>.meta.json, prepends the frontmatter
collect-papers                 → copies the already-stamped .md (unchanged)
```

The **sidecar** `<stem>.meta.json` is the carrier: `fetch-batch` writes it next
to the file it saved (the saved `Path` `fetch_one` returns, so the sidecar stem
always matches the source stem — no re-derivation). The convert steps read the
sidecar and emit the frontmatter; a paper with no sidecar simply gets no
frontmatter (the pre-US37 behaviour is unchanged).

The frontmatter always carries **all four keys** so the shape is uniform;
a field the record lacked is emitted as `null` (an arXiv paper has no `doi`,
no `venue`).

```yaml
---
doi: 10.xxxx/xxxxx
url: https://doi.org/10.xxxx/xxxxx
pdf_url: https://.../paper.pdf
venue: "Cognition"
---
```

`venue` is only populated for OpenAlex-sourced candidates (this story extends
the discover OpenAlex parser to capture it from `primary_location.source.
display_name` / `host_venue.display_name`); arXiv and Semantic Scholar records
carry no venue and emit `venue: null`.

## Acceptance Criteria

### `fetch-batch` — fetch a candidate batch and capture provenance

1. Given a candidates JSONL where each record has a `url` (and optionally `doi`,
   `pdf_url`, `venue`), when `fetch-batch candidates.jsonl --files-dir
   files/mnemonic-method` runs, then each record's URL is fetched into the
   files-dir and a `<stem>.meta.json` sidecar `{doi, url, pdf_url, venue}` is
   written next to the saved file (all four keys, `null` when the record lacked
   the field)
2. Given a record whose URL quarantines in `fetch_one` (a bot wall, an HTTP
   error), when `fetch-batch` runs, then no sidecar is written for it, the
   fetch's own manifest record stands, and the batch continues to the next
   record — never crashes
3. Given a record with no `url` field (malformed candidate), when `fetch-batch`
   runs, then it is quarantined to `manifest.jsonl` with `stage: fetch-batch`
   and skipped — never crashes, never calls an LLM

### `convert-html` / `convert-pdf` — stamp the frontmatter

4. Given a freshly-converted paper whose source has a `<stem>.meta.json`
   sidecar, when the convert step writes `<stem>.md`, then the `.md` begins with
   a YAML frontmatter block carrying all four keys followed by the body
5. Given a paper with **no** sidecar, when the convert step runs, then the `.md`
   is written with no frontmatter — the pre-US37 output is byte-for-byte
   unchanged
6. Given a `<stem>.md` that already exists **without** frontmatter and whose
   source now has a sidecar (a paper converted before this story), when the
   convert step runs again, then the frontmatter is injected in place ahead of
   the existing body (backfill)
7. Given a `<stem>.md` that already **has** frontmatter, when the convert step
   runs again, then it is left untouched — no double-stamp (idempotent)

## Case handling (classify-then-dispatch)

- `fetch-batch`: record has `url` → fetch + write sidecar; record has no `url`
  → quarantine (`stage: fetch-batch`); fetch quarantines the URL → skip sidecar,
  continue.
- convert stamp: sidecar absent → no frontmatter; `.md` absent → write body with
  frontmatter; `.md` present without frontmatter → inject; `.md` present with
  frontmatter → leave untouched.

## Arguments and options

```
uv run fetch-batch CANDIDATES_JSONL
                   [--files-dir DIR]       (default: files/)
                   [--manifest FILE]       (default: manifest.jsonl)
```

`CANDIDATES_JSONL` is a discover/rank output (one candidate record per line).

## Later stages (deferred)

- **Browser / recover lanes.** `fetch-batch` drives only the direct `fetch_one`
  lane. Papers landed by `browser-fetch` (US15) or `recover-blocked` (US17) get
  no sidecar yet; a later stage can write the sidecar from the same candidate
  record regardless of which lane fetched the file.
- **Richer citation heading.** Deriving a `# Author et al. (Year) — Title`
  heading from the record (beyond the frontmatter) is a separate concern.
- **Venue for arXiv/S2.** Only OpenAlex candidates carry a venue today; mapping
  an arXiv id or S2 paper to a venue is deferred.
