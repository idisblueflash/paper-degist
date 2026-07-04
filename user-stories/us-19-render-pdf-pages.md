# US 19 Render a PDF to per-page images

As a *maintainer benchmarking OCR models on paper-style PDFs*, i want *a step
that renders a PDF into one deterministic PNG per page*, so that *every model in
the bench sees the exact same page bitmaps and results are reproducible run to
run*.

## Background

The OCR bench (US 20–23) compares vision models by feeding each one a page image
and scoring the Markdown it returns. That comparison is only fair if every model
sees **identical** input, so rendering must be deterministic: same PDF, same dpi
→ byte-stable PNGs. The investigation report (`/Users/husongtao/Projects/tmp/report`)
settled the renderer of record: **Ghostscript** (`pdftoppm`/PyMuPDF were not
installable in the target env), at **150 dpi** → 1275×1650 px for a US-Letter
page (the quality/speed sweet spot for the local models).

This is the bench's input stage, sibling to `fetch-one` in shape: read a file
argument, classify it on a cheap signal, dispatch to the renderer, quarantine
anything that isn't a PDF. It never calls a model and never calls an LLM.

The scope is a **new CLI step, `render-pdf`, over a single PDF**. It sniffs the
file, renders each page to `pages/<stem>/pNN.png` at the configured dpi, prints
the saved page paths to stdout, and records the render to `manifest.jsonl`. It
does **not** OCR anything (US 20), score anything (US 21–22), or handle non-PDF
inputs beyond quarantining them.

## Acceptance Criteria

1. Given a real academic PDF (e.g. `files/WordCraft_Scaffolding_the_Keyword_Method.pdf`)
   - when render-pdf renders it at the default 150 dpi
     - then one PNG per page is saved as `pages/<stem>/pNN.png` (zero-padded,
       page order preserved) and their paths are printed to stdout, with a
       `rendered` record appended to `manifest.jsonl` (`stage: "render-pdf"`)
2. Given the **same** PDF rendered a second time at the same dpi
   - when render-pdf runs again
     - then the page PNGs are byte-identical to the first run (deterministic
       render — same input, same bitmaps), so downstream scores are reproducible
3. Given a PDF whose pages were already rendered by a prior run
   - when render-pdf runs again on the same PDF and dpi
     - then it skips and does not re-render or overwrite (re-runs stay safe),
       mirroring fetch-one's idempotency
4. Given an input that is **not** a PDF (e.g. a saved
   `files/Deep_Residual_Learning.html`, or a truncated/corrupt file)
   - when render-pdf sniffs it
     - then it quarantines the input to the manifest (`stage: "render-pdf"`,
       `reason` naming a non-PDF/unrenderable input), exits cleanly, and never
       crashes — the batch still finishes

## Case handling (classify-then-dispatch)

render-pdf classifies on one cheap signal first: does the file begin with the
`%PDF` magic bytes? **Not a PDF** → quarantine (`reason`: not a PDF) and move on
— never crash, never guess. **Is a PDF** → hand it to Ghostscript at the
configured dpi and write one PNG per page. The renderer and dpi are encoded
knowledge: a different dpi is a `--dpi` option (not a new code path), and if a
future env swaps Ghostscript for another engine that becomes one dispatch branch,
not a per-run decision. No signal beyond the magic-byte sniff and the render exit
status is needed, so the step stays deterministic and LLM-free.

## Later stages (deferred)

- **Batching a directory of PDFs.** This story renders one PDF per invocation.
  Looping a folder is a thin wrapper left for when the bench runs at corpus
  scale; a single-PDF step composes into that trivially.
- **Region crops for the figure hybrid.** The report's crop-and-embed hybrid
  needs sub-page crops (`magick`), not just full-page renders. That belongs with
  figure/table scoring (a later bench story), not here.
- **Alternate renderers.** PyMuPDF/poppler were unavailable in the report's env;
  if a future env has them, adding one as a dispatch branch (for speed or
  fidelity comparison) is deferred. See DEVLOG.
