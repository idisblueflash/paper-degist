# US 39 Page-number markers in converted PDF Markdown

As a *researcher feeding converted papers to an LLM wiki*, i want *each page of
the stitched `.md` to carry its page number*, so that *an AI module (the wiki
compile/rate skills, or any LLM reading the file) can cite and locate content
by page in the original PDF*.

## Background

`convert-pdf` (US3) OCRs a PDF page by page and stitches the per-page Markdown
with an anonymous horizontal rule (`_PAGE_SEP = "\n\n---\n\n"` in
`src/paper_degist/convert_pdf.py`). The rule shows a human *that* a page ended,
but not *which* page — page identity is discarded at stitch time, even though
the page loop already knows the 1-based index (it renders `page-0001.png`,
`page-0002.png`, … in order). A downstream AI module quoting the paper
therefore cannot say "p. 7", and a human cannot jump from a quote back to the
PDF page.

This story stamps the index into the stitched output as an **HTML comment
marker** at the top of every page's content:

```markdown
<!-- page: 1 -->

# Attention Is All You Need

...page one's OCR output...

---

<!-- page: 2 -->

...page two's OCR output...
```

- **HTML comment, not visible text** — it renders invisibly in any Markdown
  viewer, is trivially machine-parseable (`<!-- page: (\d+) -->`), and cannot
  be confused with OCR'd body text the way a visible heading could.
- **The horizontal rule stays** — it still does its human-readable job of
  showing the boundary; the marker rides after it.
- **Page 1 is marked too** (before its content, after any US37 frontmatter) —
  otherwise the first page would be the one unaddressable page.
- The number is the **physical 1-based page index** of the PDF, matching
  `render-pdf`'s `page-NNNN.png` ordering — not the paper's printed pagination
  (a journal article whose first page is printed "1123" still gets
  `<!-- page: 1 -->`; the printed-number mapping is deferred).

## Acceptance Criteria

1. Given a saved `files/attention-is-all-you-need.pdf`
   - when the PDF path converts it
     - then each page's Markdown is preceded by `<!-- page: N -->` with its
       1-based index, page 1 included
     - and consecutive pages remain separated by the horizontal rule

2. Given a PDF whose source has a `<stem>.meta.json` sidecar (US37)
   - when the PDF path converts it
     - then the frontmatter block comes first and `<!-- page: 1 -->` follows
       it, ahead of page one's content

3. Given a page whose OCR failed (the loop emitted its
   `<!-- OCR FAILED: page-0003.png -->` placeholder)
   - when the pages are stitched
     - then that page still gets its `<!-- page: 3 -->` marker, so the
       numbering of every later page stays aligned with the PDF

4. Given a re-run over a PDF that already has `files/<name>.md`
   - when the PDF path processes it
     - then it skips and does not overwrite (US3 AC2 unchanged) — markers are
       not injected into an existing `.md`

## Case handling (classify-then-dispatch)

- `.pdf` branch → markers stamped as above; the page index comes from the
  render order, never from parsing OCR output.
- Non-contiguous rendered page set (e.g. a hand-pruned `pages/<stem>/` dir that
  the render step's idempotent skip returns as `p0001.png, p0003.png`) →
  quarantine to `manifest.jsonl` and skip, because numbering by position would
  silently mislabel every page after the gap — never misnumber, never crash.
- `.html` branch (`convert-html`, US5) → out of scope: an HTML source has no
  page geometry, so no markers are emitted and its output is unchanged.
- Already-converted papers → **no backfill.** The markers cannot be recovered
  from the `.md` alone (a bare `---` separator is ambiguous with genuine
  horizontal rules inside OCR output); to get markers, delete the `.md` and
  re-convert. This keeps the re-run guarantee (AC 4) simple and safe.

## Later stages (deferred)

- **Printed page numbers.** Mapping the physical index to the paper's printed
  pagination (offsets, roman-numeral front matter) needs OCR-output parsing
  and is a separate story.
- **Consumption format.** How the wiki skills (US7/US8) turn a marker into a
  citation (`p. 3`, a deep link) is the consumer's concern, not the
  converter's.
