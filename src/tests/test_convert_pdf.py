"""Unit tests for US3 convert_pdf (pytest).

One assertion per test (rule 05): each test fails for exactly one reason.
Render and OCR collaborators are injected as fakes (rule 01 — fast, offline).
Distinct example PDF names label what each case exercises (rule 08).
"""

import json
from pathlib import Path

from paper_degist import _frontmatter
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
    meta=None,
    existing_md=None,
):
    """Arrange a PDF-like file and run convert_pdf; return (result, pdf, manifest)."""
    pdf = tmp_path / name
    pdf.write_bytes(b"%PDF-1.7 fake")
    if meta is not None:
        _frontmatter.write_sidecar(pdf, meta)
    if existing_md is not None:
        pdf.with_suffix(".md").write_text(existing_md, encoding="utf-8")
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
# US37 — provenance frontmatter stamped from the sidecar
# ---------------------------------------------------------------------------

_META = {"doi": "10.48550/arxiv.2602.00762", "url": "https://doi.org/10.48550/arxiv.2602.00762",
         "pdf_url": "https://arxiv.org/pdf/2602.00762.pdf", "venue": None}


def test_fresh_convert_with_sidecar_stamps_frontmatter(tmp_path):
    result, _pdf, _m = _run(tmp_path, name="SMART.pdf", meta=_META)
    assert result.read_text(encoding="utf-8").startswith("---\n")


def test_fresh_convert_without_sidecar_has_no_frontmatter(tmp_path):
    result, _pdf, _m = _run(tmp_path, name="SMART.pdf")
    assert not result.read_text(encoding="utf-8").startswith("---\n")


def test_backfill_injects_frontmatter_into_existing_md(tmp_path):
    result, _pdf, _m = _run(tmp_path, name="GPT.pdf", meta=_META, existing_md="# GPT body\n")
    assert result.read_text(encoding="utf-8").startswith("---\n")


def test_backfill_preserves_the_existing_body(tmp_path):
    result, _pdf, _m = _run(tmp_path, name="GPT.pdf", meta=_META, existing_md="# GPT body\n")
    assert result.read_text(encoding="utf-8").endswith("# GPT body\n")


def test_existing_md_with_frontmatter_is_not_double_stamped(tmp_path):
    already = _frontmatter.render(_META) + "# T5 body\n"
    result, _pdf, _m = _run(tmp_path, name="T5.pdf", meta=_META, existing_md=already)
    assert result.read_text(encoding="utf-8") == already


# ---------------------------------------------------------------------------
# page_gap — inter-page recovery gap (PoC for RAM-pressure mitigation)
# ---------------------------------------------------------------------------


def _fake_sleep():
    def sleep(seconds):
        sleep.calls.append(seconds)
    sleep.calls = []
    return sleep


def test_page_gap_is_waited_between_pages(tmp_path):
    """A non-zero page_gap must be slept between every pair of pages."""
    pdf = tmp_path / "Spaced_Repetition_Gap_Test.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")
    sleep = _fake_sleep()
    convert_pdf(
        pdf,
        pages_dir=tmp_path / "pages",
        out_dir=tmp_path / "out",
        manifest_path=tmp_path / "manifest.jsonl",
        render_fn=_fake_render(("p0001.png", "p0002.png", "p0003.png")),
        ocr_fn=_fake_ocr(),
        page_gap=7.0,
        sleep=sleep,
    )
    assert sleep.calls == [7.0, 7.0]


def test_page_gap_not_waited_before_first_page(tmp_path):
    """The gap must NOT be waited before the very first page OCR call."""
    pdf = tmp_path / "Keyword_Method_Gap_Test.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")
    sleep = _fake_sleep()
    convert_pdf(
        pdf,
        pages_dir=tmp_path / "pages",
        out_dir=tmp_path / "out",
        manifest_path=tmp_path / "manifest.jsonl",
        render_fn=_fake_render(("p0001.png", "p0002.png")),
        ocr_fn=_fake_ocr(),
        page_gap=7.0,
        sleep=sleep,
    )
    assert len(sleep.calls) == 1  # only between page 1→2, not before page 1


def test_zero_page_gap_waits_nothing(tmp_path):
    """Default gap=0 must never call sleep."""
    pdf = tmp_path / "Mnemonic_NoGap_Test.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")
    sleep = _fake_sleep()
    convert_pdf(
        pdf,
        pages_dir=tmp_path / "pages",
        out_dir=tmp_path / "out",
        manifest_path=tmp_path / "manifest.jsonl",
        render_fn=_fake_render(("p0001.png", "p0002.png")),
        ocr_fn=_fake_ocr(),
        page_gap=0.0,
        sleep=sleep,
    )
    assert sleep.calls == []


def test_two_pdfs_do_not_share_ocr_output_dir(tmp_path):
    """Pages from different PDFs must not collide on the same out/<model>/pNNNN.md."""
    shared_out = tmp_path / "out"

    def tracking_ocr(out_dirs):
        def ocr_fn(page, model, *, out_dir, manifest_path, **kwargs):
            out_dirs.append(Path(out_dir))
            target = Path(out_dir) / model.replace("/", "_") / (Path(page).stem + ".md")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"ocr of {Path(page).stem}", encoding="utf-8")
            return target

        return ocr_fn

    for pdf_name in ("Paper_Alpha.pdf", "Paper_Beta.pdf"):
        pdf = tmp_path / pdf_name
        pdf.write_bytes(b"%PDF-1.7 fake")
        out_dirs: list[Path] = []
        convert_pdf(
            pdf,
            pages_dir=tmp_path / "pages",
            out_dir=shared_out,
            manifest_path=tmp_path / "manifest.jsonl",
            render_fn=_fake_render(("p0001.png",)),
            ocr_fn=tracking_ocr(out_dirs),
        )
        # Each PDF must have its own OCR subdir, not the bare shared_out
        for d in out_dirs:
            assert d != shared_out, f"ocr_fn was called with the bare out_dir for {pdf_name}"
            assert pdf.stem in str(d), f"out_dir {d} does not include the PDF stem {pdf.stem!r}"


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


def test_empty_rendered_page_list_returns_none(tmp_path):
    result, _, _ = _run(tmp_path, name="Empty_Render.pdf", pages=())
    assert result is None


# ---------------------------------------------------------------------------
# AC3 — page OCR failure: skip-and-continue with a visible placeholder
#
# A single failed page must NOT abort the whole PDF (issue #67). The document
# is still saved; the bad page gets an HTML comment placeholder so the reader
# sees exactly where the gap is.
# ---------------------------------------------------------------------------


def test_ocr_failure_on_one_page_still_returns_md_path(tmp_path):
    result, pdf, _ = _run(
        tmp_path, name="GPT4_Technical_Report.pdf", none_for={"p0001.png"}
    )
    assert result == pdf.with_suffix(".md")


def test_ocr_failure_on_one_page_still_saves_md(tmp_path):
    _, pdf, _ = _run(
        tmp_path, name="GPT4_Technical_Report.pdf", none_for={"p0001.png"}
    )
    assert pdf.with_suffix(".md").exists()


def test_ocr_failure_emits_placeholder_for_the_failed_page(tmp_path):
    result, _, _ = _run(
        tmp_path, name="GPT4_Technical_Report.pdf", none_for={"p0001.png"}
    )
    assert "<!-- OCR FAILED: p0001.png -->" in result.read_text(encoding="utf-8")


def test_ocr_failure_placeholder_preserves_other_pages(tmp_path):
    content_map = {"p0002.png": "# Good page content"}
    result, _, _ = _run(
        tmp_path,
        name="GPT4_Technical_Report.pdf",
        none_for={"p0001.png"},
        content_map=content_map,
    )
    assert "# Good page content" in result.read_text(encoding="utf-8")


def test_unreadable_ocr_markdown_returns_none(tmp_path):
    pdf = tmp_path / "Unreadable_OCR_Output.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")
    bad_md = tmp_path / "out" / DEFAULT_MODEL / "p0001.md"
    bad_md.parent.mkdir(parents=True)
    bad_md.write_bytes(b"\xff\xfe\x00")

    def ocr_fn(page, model, *, out_dir, manifest_path, **kwargs):
        return bad_md

    result = convert_pdf(
        pdf,
        pages_dir=tmp_path / "pages",
        out_dir=tmp_path / "out",
        manifest_path=tmp_path / "manifest.jsonl",
        render_fn=_fake_render(("p0001.png",)),
        ocr_fn=ocr_fn,
    )

    assert result is None


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
