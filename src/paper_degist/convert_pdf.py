"""US3 — convert a PDF paper into a Markdown file via per-page OCR.

Wires render-pdf (US19) + ocr-page (US20) into the pipeline's .pdf branch.
The default OCR model is deepseek-ocr-2, chosen by the US19–23/28 bench:
best accuracy (text edit distance 0.117, table TEDS 0.727) at ~19 s/page.

Each page is rendered to a PNG, OCR'd to Markdown, and the pages are stitched
in page order and saved as ``files/<name>.md``. A pre-existing ``.md`` is left
untouched (re-runs stay safe). An unknown model, a render failure, or any page
OCR failure quarantines the PDF to ``manifest.jsonl`` and skips it — the batch
never crashes, never calls an LLM to rescue (rule 02).

Runnable from the command line (rule 03):

    uv run convert-pdf files/paper.pdf
    uv run convert-pdf files/paper.pdf --model deepseek-ocr-2
"""

import time
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer

from paper_degist import _frontmatter, _manifest
from paper_degist._cli import invoke
from paper_degist.ocr_page import REGISTRY, ocr_page
from paper_degist.render_pdf import render_pdf

# The bench winner: best text edit distance (0.117) and table TEDS (0.727)
# at ~19 s/page, with clean grounding output after _decode_grounding_layout.
DEFAULT_MODEL = "deepseek-ocr-2"

# Page separator in the stitched Markdown. A horizontal rule marks the
# boundary so a reader sees where one scanned page ends and the next begins.
_PAGE_SEP = "\n\n---\n\n"

RenderFn = Callable[..., Optional[list[Path]]]
OcrFn = Callable[..., Optional[Path]]


def _quarantine(manifest_path: Path, *, pdf: str, reason: str) -> None:
    """Append one unhandled-case record to the manifest, so the batch finishes."""
    _manifest.append(manifest_path, stage="convert-pdf", pdf=pdf, reason=reason)


def convert_pdf(
    pdf_path: Path,
    *,
    model_id: str = DEFAULT_MODEL,
    pages_dir: Path = Path("pages"),
    out_dir: Path = Path("out"),
    manifest_path: Path = Path("manifest.jsonl"),
    render_fn: RenderFn = render_pdf,
    ocr_fn: OcrFn = ocr_page,
    registry: dict = REGISTRY,
    page_gap: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Optional[Path]:
    """Convert ``files/<name>.pdf`` to ``files/<name>.md`` via page-by-page OCR.

    Returns the saved (or already-present) ``.md`` path on success, or ``None``
    when quarantined — an unknown model, a render failure, or any page OCR
    failure. In all quarantine cases the manifest records the reason and the
    function returns without writing the ``.md``.
    """
    pdf_path = Path(pdf_path)
    pages_dir = Path(pages_dir)
    out_dir = Path(out_dir)
    manifest_path = Path(manifest_path)

    # Classify on the model id first (cheap, no I/O) — fail fast before any
    # rendering if the model is not registered (rule 02: classify-then-dispatch).
    if model_id not in registry:
        _quarantine(
            manifest_path,
            pdf=str(pdf_path),
            reason=f"unknown model: {model_id!r} not in registry",
        )
        return None

    # US37: the source's sidecar (if any) carries the paper's provenance; it is
    # stamped as frontmatter on the stitched Markdown below. No sidecar → none.
    meta = _frontmatter.load_sidecar(pdf_path)
    target = pdf_path.with_suffix(".md")
    if target.exists():
        # Leave an existing .md untouched — unless it predates the sidecar and
        # carries no frontmatter yet, in which case backfill it in place (US37 AC6).
        existing = target.read_text(encoding="utf-8")
        stamped = _frontmatter.apply(existing, meta)
        if stamped != existing:
            staging = target.with_name(target.name + ".writing")
            staging.write_text(stamped, encoding="utf-8")
            staging.rename(target)
        return target

    pages = render_fn(pdf_path, pages_dir=pages_dir, manifest_path=manifest_path)
    if pages is None:
        # render_pdf already wrote the quarantine record; nothing more to do.
        return None
    if not pages:
        _quarantine(
            manifest_path,
            pdf=str(pdf_path),
            reason="render produced no pages",
        )
        return None

    # Scope the OCR output dir to the PDF stem so pages from different PDFs
    # never collide on p0001.md / p0002.md in the flat out/<model>/ directory.
    pdf_out_dir = out_dir / pdf_path.stem
    page_markdowns: list[str] = []
    for i, page in enumerate(pages):
        if i > 0 and page_gap > 0:
            sleep(page_gap)
        md_path = ocr_fn(page, model_id, out_dir=pdf_out_dir, manifest_path=manifest_path)
        if md_path is None:
            # This page's OCR failed; ocr_page already wrote its quarantine record.
            # Emit a visible placeholder so the document is not lost for one bad
            # page (issue #67: a single transient 400 was killing whole PDFs).
            page_markdowns.append(f"<!-- OCR FAILED: {page.name} -->")
            continue
        try:
            page_markdowns.append(Path(md_path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            _quarantine(
                manifest_path,
                pdf=str(pdf_path),
                reason=f"unreadable OCR output for page {page.name}: {exc}",
            )
            return None

    stitched = _frontmatter.apply(_PAGE_SEP.join(page_markdowns), meta)
    # Atomic write: stage under a sibling so a killed write never leaves a
    # partial file the idempotency skip would accept as a complete convert.
    staging = target.with_name(target.name + ".writing")
    staging.write_text(stitched, encoding="utf-8")
    staging.rename(target)
    return target


app = typer.Typer(
    add_completion=False,
    help="Convert a PDF paper into Markdown via page-by-page OCR (US3).",
)


@app.command()
def run(
    pdf: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="the PDF to convert"),
    ],
    model: Annotated[
        str,
        typer.Option(help="registered OCR model id"),
    ] = DEFAULT_MODEL,
    pages_dir: Annotated[
        Path,
        typer.Option(help="directory to render pages under (pages/<stem>/)"),
    ] = Path("pages"),
    out_dir: Annotated[
        Path,
        typer.Option(help="directory for per-page OCR output (out/<model>/)"),
    ] = Path("out"),
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of quarantined inputs"),
    ] = Path("manifest.jsonl"),
    page_gap: Annotated[
        float,
        typer.Option(help="seconds to wait between page OCR calls (0 = no gap)"),
    ] = 0.0,
) -> None:
    """Convert the PDF to Markdown; print the saved .md path, or a quarantine note on stderr."""
    target = convert_pdf(
        pdf,
        model_id=model,
        pages_dir=pages_dir,
        out_dir=out_dir,
        manifest_path=manifest,
        page_gap=page_gap,
    )
    if target is None:
        typer.echo(f"quarantined (see {manifest}): {pdf}", err=True)
        return
    typer.echo(str(target))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run convert-pdf`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
