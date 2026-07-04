import json
import tempfile
from pathlib import Path

from behave import given, when, then
from pypdf import PdfWriter

from paper_degist.render_pdf import render_pdf


def _files_dir(context):
    """A literal files/ folder (the saved-input home) under a temp root."""
    if not getattr(context, "files_dir", None):
        context.files_dir = Path(tempfile.mkdtemp()) / "files"
        context.files_dir.mkdir()
    return context.files_dir


@given('a saved PDF "{name}" with {count:d} pages')
def step_saved_pdf(context, name, count):
    writer = PdfWriter()
    for _ in range(count):
        writer.add_blank_page(width=612, height=792)  # US-Letter points
    context.pdf = _files_dir(context) / name
    with context.pdf.open("wb") as fh:
        writer.write(fh)


@given('a saved non-PDF file "{name}"')
def step_saved_non_pdf(context, name):
    context.pdf = _files_dir(context) / name
    context.pdf.write_text("<html><body>not a pdf</body></html>", encoding="utf-8")


@when("render-pdf renders the PDF")
def step_render(context):
    root = _files_dir(context).parent
    context.manifest = root / "manifest.jsonl"
    context.pages_dir = root / "pages"
    context.result = render_pdf(
        context.pdf, pages_dir=context.pages_dir, manifest_path=context.manifest
    )


@then("one PNG per page is saved under pages/{stem}/")
def step_pages_saved(context, stem):
    out_dir = context.pages_dir / stem
    pngs = sorted(out_dir.glob("p*.png"))
    assert pngs, f"no page PNGs under {out_dir}"
    assert context.result == pngs, f"render_pdf returned {context.result}, expected {pngs}"


@then("the render is recorded in the manifest with {count:d} pages")
def step_manifest_pages(context, count):
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["stage"] == "render-pdf", record
    assert record["pages"] == count, f"recorded {record['pages']} pages, expected {count}"


@then("no page images are saved for it")
def step_no_pages(context):
    assert context.result is None
    assert not (context.pages_dir / context.pdf.stem).exists()


@then('the PDF is recorded in the manifest with reason "{reason}"')
def step_manifest_reason(context, reason):
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["pdf"] == str(context.pdf), f"{record} does not name {context.pdf}"
    assert record["reason"] == reason, f"reason was {record['reason']!r}, expected {reason!r}"
