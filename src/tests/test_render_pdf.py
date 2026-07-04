"""Unit tests for US19 render_pdf (pytest).

One assertion per test (rule 05): each test fails for exactly one reason. The
actual Ghostscript call is injected as ``render`` so these stay fast and
isolated (rule 01) — the real gs render is exercised end-to-end (rule 06 §7),
not here. Distinct example PDFs per case (rule 08) label what each exercises.
"""

import json
from pathlib import Path

from paper_degist.render_pdf import render_pdf


def _fake_render(*names: str):
    """A stand-in renderer: write one placeholder PNG per name, return them.

    Mirrors ``_default_render``'s contract (make the out dir, produce
    ``pNNNN.png`` files, return the sorted paths) without shelling out to gs.
    """
    names = names or ("p0001.png", "p0002.png")

    def render(pdf_path: Path, out_dir: Path, dpi: int) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for name in names:
            page = out_dir / name
            page.write_bytes(b"PNG:" + name.encode())
            paths.append(page)
        return sorted(paths)

    return render


def _boom_render(pdf_path: Path, out_dir: Path, dpi: int) -> list[Path]:
    """A renderer that fails — stands in for gs choking on a corrupt PDF."""
    raise RuntimeError("gs: no pages")


def _run(tmp_path: Path, *, header=b"%PDF-1.7\n", name="WordCraft.pdf", render=None, dpi=150):
    """Arrange a PDF-like file + manifest and run render_pdf; return the trio."""
    pdf = tmp_path / name
    pdf.write_bytes(header + b"body bytes")
    manifest = tmp_path / "manifest.jsonl"
    result = render_pdf(
        pdf,
        pages_dir=tmp_path / "pages",
        manifest_path=manifest,
        dpi=dpi,
        render=render or _fake_render(),
    )
    return result, pdf, manifest


def _only_record(manifest: Path):
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


# --- render one PNG per page under pages/<stem>/ (AC1) ---


def test_returns_one_path_per_page(tmp_path: Path):
    result, _, _ = _run(tmp_path, render=_fake_render("p0001.png", "p0002.png", "p0003.png"))
    assert len(result) == 3


def test_pages_saved_under_stem_subdir(tmp_path: Path):
    result, _, _ = _run(tmp_path, name="Attention_Is_All_You_Need.pdf")
    assert result[0].parent == tmp_path / "pages" / "Attention_Is_All_You_Need"


def test_pages_are_zero_padded_and_in_order(tmp_path: Path):
    result, _, _ = _run(tmp_path, render=_fake_render("p0001.png", "p0002.png"))
    assert [p.name for p in result] == ["p0001.png", "p0002.png"]


# --- success appends a `rendered` provenance record (AC1) ---


def test_success_manifest_records_render_pdf_stage(tmp_path: Path):
    _, _, manifest = _run(tmp_path)
    assert _only_record(manifest)["stage"] == "render-pdf"


def test_success_manifest_counts_the_pages(tmp_path: Path):
    _, _, manifest = _run(tmp_path, render=_fake_render("p0001.png", "p0002.png", "p0003.png"))
    assert _only_record(manifest)["pages"] == 3


def test_success_manifest_records_the_dpi(tmp_path: Path):
    _, _, manifest = _run(tmp_path, dpi=300)
    assert _only_record(manifest)["dpi"] == 300


# --- idempotent skip: pages already rendered are left untouched (AC3) ---


def _run_with_existing(tmp_path: Path, render):
    """Run render_pdf when pages/<stem>/ already holds a rendered page."""
    pdf = tmp_path / "Deep_Residual_Learning.pdf"
    pdf.write_bytes(b"%PDF-1.7\nbody bytes")
    out_dir = tmp_path / "pages" / "Deep_Residual_Learning"
    out_dir.mkdir(parents=True)
    (out_dir / "p0001.png").write_bytes(b"already rendered")
    manifest = tmp_path / "manifest.jsonl"
    result = render_pdf(pdf, pages_dir=tmp_path / "pages", manifest_path=manifest, render=render)
    return result, out_dir, manifest


def test_idempotent_skip_returns_existing_pages(tmp_path: Path):
    result, out_dir, _ = _run_with_existing(tmp_path, render=_fake_render())
    assert result == [out_dir / "p0001.png"]


def test_idempotent_skip_does_not_rerender(tmp_path: Path):
    # _boom_render raises if called; a clean return proves render was skipped.
    result, out_dir, _ = _run_with_existing(tmp_path, render=_boom_render)
    assert result == [out_dir / "p0001.png"]


def test_idempotent_skip_writes_no_manifest_record(tmp_path: Path):
    _, _, manifest = _run_with_existing(tmp_path, render=_fake_render())
    assert not manifest.exists()


# --- quarantine a non-PDF input — never crash (AC4) ---


def test_non_pdf_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, header=b"<html>", name="Residual_Networks.html")
    assert result is None


def test_non_pdf_writes_no_pages(tmp_path: Path):
    _run(tmp_path, header=b"<html>", name="Residual_Networks.html")
    assert not (tmp_path / "pages" / "Residual_Networks").exists()


def test_non_pdf_manifest_records_render_pdf_stage(tmp_path: Path):
    _, _, manifest = _run(tmp_path, header=b"<html>", name="Residual_Networks.html")
    assert _only_record(manifest)["stage"] == "render-pdf"


def test_non_pdf_manifest_reason_names_non_pdf(tmp_path: Path):
    _, _, manifest = _run(tmp_path, header=b"<html>", name="Residual_Networks.html")
    assert "not a PDF" in _only_record(manifest)["reason"]


def test_missing_file_is_quarantined_not_crashed(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    result = render_pdf(
        tmp_path / "absent.pdf", pages_dir=tmp_path / "pages", manifest_path=manifest
    )
    assert result is None


# --- quarantine a %PDF file gs cannot render, distinctly from a non-PDF (AC4) ---


def test_unrenderable_pdf_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, name="Corrupt_Truncated.pdf", render=_boom_render)
    assert result is None


def test_unrenderable_pdf_reason_is_distinct_from_non_pdf(tmp_path: Path):
    _, _, manifest = _run(tmp_path, name="Corrupt_Truncated.pdf", render=_boom_render)
    assert _only_record(manifest)["reason"].startswith("unrenderable")


def test_failed_render_leaves_no_partial_pages(tmp_path: Path):
    # gs can write some pages before dying; a partial set must not survive to be
    # mistaken for a complete render by a re-run's idempotency skip.
    def _partial_then_boom(pdf_path: Path, out_dir: Path, dpi: int) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "p0001.png").write_bytes(b"partial page")
        raise RuntimeError("gs died mid-render")

    _run(tmp_path, name="Half_Rendered.pdf", render=_partial_then_boom)
    assert not sorted((tmp_path / "pages" / "Half_Rendered").glob("p*.png"))
