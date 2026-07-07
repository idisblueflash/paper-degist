import json
import tempfile
from pathlib import Path

from behave import given, then, when

from paper_degist.convert_pdf import convert_pdf
from paper_degist.ocr_page import REGISTRY


def _root(context):
    if not getattr(context, "_convert_pdf_root", None):
        context._convert_pdf_root = Path(tempfile.mkdtemp())
        (context._convert_pdf_root / "files").mkdir()
    return context._convert_pdf_root


def _fake_render(root, pages=("p0001.png", "p0002.png")):
    def render_fn(pdf_path, *, pages_dir, manifest_path, **kwargs):
        out_dir = Path(pages_dir) / Path(pdf_path).stem
        out_dir.mkdir(parents=True, exist_ok=True)
        result = []
        for i, name in enumerate(pages):
            p = out_dir / name
            p.write_bytes(b"\x89PNG")
            result.append(p)
        return result

    return render_fn


def _fake_render_fail():
    def render_fn(pdf_path, *, pages_dir, manifest_path, **kwargs):
        return None

    return render_fn


def _fake_ocr(content_prefix="page content from ", *, none_for=()):
    none_for = set(none_for)

    def ocr_fn(page, model, *, out_dir, manifest_path, **kwargs):
        page_path = Path(page)
        if page_path.name in none_for:
            return None
        target = Path(out_dir) / model.replace("/", "_") / (page_path.stem + ".md")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content_prefix + page_path.name, encoding="utf-8")
        return target

    return ocr_fn


@given('a registered OCR model "{model_id}"')
def step_registered_model(context, model_id):
    assert model_id in REGISTRY, f"{model_id!r} is not in the OCR registry"
    context.model_id = model_id


@given('a saved PDF file "{name}"')
def step_pdf_file(context, name):
    root = _root(context)
    pdf = root / name
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.7 fake")
    context.pdf = pdf
    context.pdf_none_for = set()


@given('"{name}" already exists')
def step_md_already_exists(context, name):
    root = _root(context)
    md = root / name
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("pre-existing content", encoding="utf-8")
    context.existing_md = md


@given('OCR will fail for a page of "{name}"')
def step_ocr_will_fail(context, name):
    context.pdf_none_for = {"p0001.png"}


@when('I run convert-pdf on "{name}"')
def step_run_convert_pdf(context, name):
    root = _root(context)
    context.manifest = root / "manifest.jsonl"
    none_for = getattr(context, "pdf_none_for", set())
    context.result = convert_pdf(
        root / name,
        pages_dir=root / "pages",
        out_dir=root / "out",
        manifest_path=context.manifest,
        render_fn=_fake_render(root) if not none_for else _fake_render(root),
        ocr_fn=_fake_ocr(none_for=none_for),
    )


@then('"{name}" is saved with stitched page content')
def step_md_saved_stitched(context, name):
    root = _root(context)
    md = root / name
    assert md.exists(), f"{md} was not created"
    assert context.result == md


@then("the pages appear in order in the saved Markdown")
def step_pages_in_order(context):
    text = context.result.read_text(encoding="utf-8")
    assert "p0001" in text and "p0002" in text, f"page names not found in:\n{text}"
    assert text.index("p0001") < text.index("p0002"), "pages are not in order"


@then('"{name}" is returned unchanged')
def step_md_unchanged(context, name):
    root = _root(context)
    md = root / name
    assert context.result == md
    assert md.read_text(encoding="utf-8") == "pre-existing content"


@then('no Markdown file is saved for "{name}"')
def step_no_md_saved(context, name):
    root = _root(context)
    assert context.result is None
    assert not (root / name).with_suffix(".md").exists()


@then('a quarantine record is written to manifest.jsonl with stage "{stage}"')
def step_quarantine_record(context, stage):
    assert context.manifest.exists(), "manifest.jsonl was not created"
    records = [json.loads(line) for line in context.manifest.read_text().splitlines()]
    assert any(r.get("stage") == stage for r in records), (
        f"no record with stage={stage!r} in {records}"
    )
