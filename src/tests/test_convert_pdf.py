"""Unit tests for US3 convert_pdf (pytest).

One assertion per test (rule 05): each test fails for exactly one reason.
Render and OCR collaborators are injected as fakes (rule 01 — fast, offline).
Distinct example PDF names label what each case exercises (rule 08).
"""

import json
from pathlib import Path

from paper_degist.convert_pdf import DEFAULT_MODEL, convert_pdf
from paper_degist.ocr_page import REGISTRY


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fake_render(pages=("p0001.png", "p0002.png"), *, fail=False):
    """A render_pdf stand-in that creates placeholder PNGs or returns None."""

    def render_fn(pdf_path, *, pages_dir, manifest_path, **kwargs):
        if fail:
            return None
        out_dir = Path(pages_dir) / Path(pdf_path).stem
        out_dir.mkdir(parents=True, exist_ok=True)
        result = []
        for name in pages:
            p = out_dir / name
            p.write_bytes(b"\x89PNG")
            result.append(p)
        return result

    return render_fn


def _fake_ocr(content_map=None, *, none_for=()):
    """An ocr_page stand-in: writes placeholder Markdown and returns the path.

    ``content_map`` maps page-basename → Markdown content (default: "# <name>").
    ``none_for`` is a set of page basenames for which to return None (quarantine).
    """
    content_map = content_map or {}
    none_for = set(none_for)

    def ocr_fn(page, model, *, out_dir, manifest_path, **kwargs):
        page_path = Path(page)
        if page_path.name in none_for:
            return None
        target = Path(out_dir) / model.replace("/", "_") / (page_path.stem + ".md")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = content_map.get(page_path.name, f"# {page_path.stem}")
        target.write_text(content, encoding="utf-8")
        return target

    return ocr_fn


def _run(
    tmp_path,
    *,
    name="Attention_Is_All_You_Need.pdf",
    model_id=DEFAULT_MODEL,
    pages=("p0001.png", "p0002.png"),
    render_fail=False,
    none_for=(),
    content_map=None,
):
    """Arrange a PDF-like file and run convert_pdf; return (result, pdf, manifest)."""
    pdf = tmp_path / name
    pdf.write_bytes(b"%PDF-1.7 fake")
    manifest = tmp_path / "manifest.jsonl"
    result = convert_pdf(
        pdf,
        model_id=model_id,
        pages_dir=tmp_path / "pages",
        out_dir=tmp_path / "out",
        manifest_path=manifest,
        render_fn=_fake_render(pages, fail=render_fail),
        ocr_fn=_fake_ocr(content_map, none_for=none_for),
    )
    return result, pdf, manifest


def _records(manifest: Path) -> list[dict]:
    if not manifest.exists():
        return []
    return [json.loads(line) for line in manifest.read_text().splitlines()]


# ---------------------------------------------------------------------------
# AC1 — happy path: render + OCR + stitch + save
# ---------------------------------------------------------------------------


def test_returns_the_md_path_on_success(tmp_path):
    result, pdf, _ = _run(tmp_path, name="Attention_Is_All_You_Need.pdf")
    assert result == pdf.with_suffix(".md")


def test_saved_md_exists_on_disk(tmp_path):
    result, _, _ = _run(tmp_path)
    assert result.exists()


def test_stitched_content_contains_first_page(tmp_path):
    content_map = {"p0001.png": "# Page one content", "p0002.png": "# Page two content"}
    result, _, _ = _run(tmp_path, content_map=content_map)
    assert "# Page one content" in result.read_text(encoding="utf-8")


def test_stitched_content_contains_second_page(tmp_path):
    content_map = {"p0001.png": "# Page one content", "p0002.png": "# Page two content"}
    result, _, _ = _run(tmp_path, content_map=content_map)
    assert "# Page two content" in result.read_text(encoding="utf-8")


def test_pages_are_stitched_in_order(tmp_path):
    content_map = {"p0001.png": "FIRST", "p0002.png": "SECOND"}
    result, _, _ = _run(tmp_path, content_map=content_map)
    text = result.read_text(encoding="utf-8")
    assert text.index("FIRST") < text.index("SECOND")


# ---------------------------------------------------------------------------
# AC2 — idempotent skip: existing .md is returned unchanged
# ---------------------------------------------------------------------------


def test_idempotent_skip_returns_existing_md(tmp_path):
    pdf = tmp_path / "Deep_Residual_Learning.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")
    existing_md = pdf.with_suffix(".md")
    existing_md.write_text("already here", encoding="utf-8")
    result = convert_pdf(
        pdf,
        pages_dir=tmp_path / "pages",
        out_dir=tmp_path / "out",
        manifest_path=tmp_path / "manifest.jsonl",
    )
    assert result == existing_md


def test_idempotent_skip_does_not_overwrite_content(tmp_path):
    pdf = tmp_path / "Deep_Residual_Learning.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")
    existing_md = pdf.with_suffix(".md")
    existing_md.write_text("already here", encoding="utf-8")
    convert_pdf(
        pdf,
        pages_dir=tmp_path / "pages",
        out_dir=tmp_path / "out",
        manifest_path=tmp_path / "manifest.jsonl",
    )
    assert existing_md.read_text(encoding="utf-8") == "already here"


def test_idempotent_skip_does_not_call_render(tmp_path):
    pdf = tmp_path / "Deep_Residual_Learning.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")
    pdf.with_suffix(".md").write_text("already here", encoding="utf-8")
    calls = []

    def render_fn(*a, **kw):
        calls.append(1)
        return []

    convert_pdf(
        pdf,
        pages_dir=tmp_path / "pages",
        out_dir=tmp_path / "out",
        manifest_path=tmp_path / "manifest.jsonl",
        render_fn=render_fn,
    )
    assert calls == []


# ---------------------------------------------------------------------------
# AC3 — quarantine: render failure
# ---------------------------------------------------------------------------


def test_render_failure_returns_none(tmp_path):
    result, _, _ = _run(tmp_path, name="BERT_Pretraining.pdf", render_fail=True)
    assert result is None


def test_render_failure_does_not_write_md(tmp_path):
    result, pdf, _ = _run(tmp_path, name="BERT_Pretraining.pdf", render_fail=True)
    assert not pdf.with_suffix(".md").exists()


# ---------------------------------------------------------------------------
# AC3 — quarantine: OCR failure on a page
# ---------------------------------------------------------------------------


def test_ocr_failure_returns_none(tmp_path):
    result, _, _ = _run(
        tmp_path, name="GPT4_Technical_Report.pdf", none_for={"p0001.png"}
    )
    assert result is None


def test_ocr_failure_does_not_write_md(tmp_path):
    result, pdf, _ = _run(
        tmp_path, name="GPT4_Technical_Report.pdf", none_for={"p0001.png"}
    )
    assert not pdf.with_suffix(".md").exists()


def test_ocr_failure_quarantines_to_manifest(tmp_path):
    _, _, manifest = _run(
        tmp_path, name="GPT4_Technical_Report.pdf", none_for={"p0001.png"}
    )
    records = _records(manifest)
    assert any(r.get("stage") == "convert-pdf" for r in records)


def test_ocr_failure_manifest_records_the_pdf(tmp_path):
    _, pdf, manifest = _run(
        tmp_path, name="GPT4_Technical_Report.pdf", none_for={"p0001.png"}
    )
    records = _records(manifest)
    cv = next(r for r in records if r.get("stage") == "convert-pdf")
    assert cv["pdf"] == str(pdf)


def test_ocr_failure_manifest_records_the_failing_page(tmp_path):
    _, _, manifest = _run(
        tmp_path, name="GPT4_Technical_Report.pdf", none_for={"p0001.png"}
    )
    records = _records(manifest)
    cv = next(r for r in records if r.get("stage") == "convert-pdf")
    assert "p0001" in cv["reason"]


# ---------------------------------------------------------------------------
# AC3 — quarantine: model not in registry
# ---------------------------------------------------------------------------


def test_unknown_model_returns_none(tmp_path):
    result, _, _ = _run(tmp_path, name="Mamba_SSM.pdf", model_id="unknown-vision-model")
    assert result is None


def test_unknown_model_quarantines_to_manifest(tmp_path):
    _, _, manifest = _run(tmp_path, name="Mamba_SSM.pdf", model_id="unknown-vision-model")
    records = _records(manifest)
    assert any(r.get("stage") == "convert-pdf" for r in records)


def test_unknown_model_does_not_call_render(tmp_path):
    pdf = tmp_path / "Mamba_SSM.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")
    calls = []

    def render_fn(*a, **kw):
        calls.append(1)
        return []

    convert_pdf(
        pdf,
        model_id="unknown-vision-model",
        pages_dir=tmp_path / "pages",
        out_dir=tmp_path / "out",
        manifest_path=tmp_path / "manifest.jsonl",
        render_fn=render_fn,
    )
    assert calls == []


def test_default_model_is_in_registry(tmp_path):
    assert DEFAULT_MODEL in REGISTRY
