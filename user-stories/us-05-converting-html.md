# US 5 Converting HTML

As a *researcher*, i want to *convert an HTML paper into an MD file*, so that i
can *process it with LLM* later.

An HTML paper is already structured markup — unlike the PDF path (US 3 OCRs page
images to Markdown), headings, lists, tables, and code blocks map near-directly
to Markdown, so this is a distinct, structure-*preserving* converter rather than
a re-render of OCR'd text.

## Acceptance Criteria

1. Given a saved `files/<name>.html`
   - when convert-html processes it
     - then structure (headings, lists, tables, code) is preserved as Markdown
     - and saved as `files/<name>.md`

## Case handling (classify-then-dispatch)

The convert stage dispatches by file extension (mirroring fetch-one's
Content-Type dispatch): `.pdf` → the PDF path (US 3), `.html` → this
converter. Both paths converge on `files/<name>.md`.

2. Given an HTML file whose real content is JS-rendered (a hollow SPA shell,
   e.g. a near-empty `<div id="__next">`)
   - when convert-html finds the extracted Markdown is below a content-density
     threshold
     - then quarantine it to `manifest.jsonl` (path, reason: "HTML too thin")
     - and skip it so the batch still finishes — never crash, never call an LLM
       in the loop (see DEVLOG deferred flag)
