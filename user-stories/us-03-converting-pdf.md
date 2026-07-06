# US 3 Converting PDF

As a *researcher*, i want to *convert a PDF paper into an MD file*, so that i
can *process it with LLM* later.

A PDF is scanned page-by-page and OCR'd straight to Markdown — the OCR model
emits Markdown directly (every registered model's prompt is literally *"Convert
the document to markdown."*, `src/paper_degist/ocr_page.py`), so there is no
intermediate plain-text stage. This folds in the old US 4 (text → MD), which is
retired: the PDF path is one step, PDF → `files/<name>.md`, not two.

The OCR machinery already exists from the model bench: `render-pdf` (US 19)
rasterizes the PDF to per-page images, `ocr-page` (US 20) OCRs one page against
a registered model, and this story wires them into the pipeline's `.pdf` branch.

## Default model

**`deepseek-ocr-2`** is the default OCR model, chosen by the US 19–23 / US 28
benchmark (`score-gold`, `ocr-report`). Against the OmniDocBench gold subset it
won both accuracy metrics — lowest text edit distance (0.117) and highest table
TEDS (0.727) — with clean reference-free output (hyphen artifacts 0.14 vs the
8-bit quant's 12.18) and ~19 s/page. The model id stays a registry lookup, so a
future bench can re-default without touching this branch.

## Acceptance Criteria

1. Given a saved `files/<name>.pdf`
   - when the PDF path processes it with the default OCR model
     - then each page is OCR'd to Markdown and the pages are stitched in order
     - and saved as `files/<name>.md`

2. Given a re-run over a PDF that already has `files/<name>.md`
   - when the PDF path processes it
     - then it skips and does not overwrite (re-runs stay safe)

## Case handling (classify-then-dispatch)

The convert stage dispatches by file extension (mirroring fetch-one's
Content-Type dispatch): `.pdf` → this OCR path, `.html` → convert-html (US 5).
Both paths converge on `files/<name>.md`.

3. Given a page whose OCR call fails or returns a non-`stop` finish (truncation,
   transport error), or a PDF requesting a model not in the registry
   - when the PDF path hits it
     - then quarantine to `manifest.jsonl` (path, page, reason) and skip it so
       the batch still finishes — never crash, never call an LLM to rescue it.
