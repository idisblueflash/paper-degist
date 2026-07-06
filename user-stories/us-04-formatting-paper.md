# US 4 Formatting Paper

> **❌ Cancelled — folded into [US 3](us-03-converting-pdf.md).**
>
> This story split the PDF path into two stages: US 3 extracts lossy *text* and
> US 4 reformats that text into Markdown. That split no longer reflects the
> implementation. The OCR model emits Markdown directly from each page image
> (every registered model's prompt is *"Convert the document to markdown."*,
> `src/paper_degist/ocr_page.py`), so there is no intermediate text stage to
> reformat. The PDF path is a single step, PDF → `files/<name>.md`, owned by
> US 3. The row is kept (status `❌ Cancelled` in the index) so US numbering
> stays stable and the rationale is on record.

As a *researcher*, i want to *convert text file into MD file*, so that i can
*process it with LLM* later.
