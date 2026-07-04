"""US19 — render a PDF into one deterministic PNG per page for the OCR bench.

The OCR bench (US 20–23) scores vision models by feeding each the *same* page
bitmaps, so rendering must be reproducible: same PDF + same dpi → byte-stable
PNGs. Ghostscript is the renderer of record (poppler/PyMuPDF were not
installable in the report's env), at 150 dpi → 1275×1650 px for a US-Letter
page — the quality/speed sweet spot the investigation report settled on.

Classify-then-dispatch (rule 02): sniff the ``%PDF`` magic bytes first; a file
that is not a PDF — or a PDF Ghostscript cannot render — is quarantined to
``manifest.jsonl`` and skipped, never crashed over, never handed to an LLM. On
success a ``rendered`` provenance record is appended too, so the bench has a
machine-readable log of what page set each PDF produced (the manifest is both
the quarantine queue and the bench's artifact ledger).

Runnable from the command line (rule 03):

    uv run render-pdf files/paper.pdf                 # -> pages/paper/pNNNN.png
    uv run render-pdf files/paper.pdf --dpi 300 --pages-dir out/
"""

import shutil
import subprocess
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke

# 150 dpi → 1275×1650 px for US-Letter: the report's quality/speed balance for
# the local vision models. A different dpi is a `--dpi` option, not a new path.
DEFAULT_DPI = 150

# render(pdf_path, out_dir, dpi) -> the produced PNG paths, sorted in page order.
Renderer = Callable[[Path, Path, int], list[Path]]


def _default_render(pdf_path: Path, out_dir: Path, dpi: int) -> list[Path]:
    """Render every page to ``out_dir/pNNNN.png`` via Ghostscript (png16m).

    Deterministic: fixed device and dpi, no timestamped output. Raises on a gs
    failure so the caller can quarantine a corrupt PDF rather than crash.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "gs",
            "-dNOPAUSE",
            "-dBATCH",
            "-dSAFER",
            "-sDEVICE=png16m",
            f"-r{dpi}",
            "-sOutputFile=" + str(out_dir / "p%04d.png"),
            str(pdf_path),
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        # Surface gs's own diagnostic (bounded) so the quarantine reason is
        # debuggable without re-running the render.
        tail = proc.stderr.decode("utf-8", "replace").strip()[-300:]
        raise RuntimeError(f"gs exited {proc.returncode}: {tail}")
    return sorted(out_dir.glob("p*.png"))


def _is_pdf(path: Path) -> bool:
    """True when ``path`` opens and begins with the ``%PDF`` magic bytes.

    The cheap first signal (rule 02). A missing/unreadable file, or one without
    the header, is not a PDF — it will be quarantined, not crashed over.
    """
    try:
        with path.open("rb") as fh:
            return fh.read(5).startswith(b"%PDF")
    except OSError:
        return False


def _quarantine(manifest_path: Path, *, pdf: str, reason: str) -> None:
    """Append one unhandled-case record to the manifest, so the batch finishes."""
    _manifest.append(manifest_path, stage="render-pdf", pdf=pdf, reason=reason)


def render_pdf(
    pdf_path: Path,
    *,
    pages_dir: Path = Path("pages"),
    manifest_path: Path = Path("manifest.jsonl"),
    dpi: int = DEFAULT_DPI,
    render: Renderer = _default_render,
) -> Optional[list[Path]]:
    """Render ``pdf_path`` to ``pages_dir/<stem>/pNNNN.png``; return the pages.

    Returns the list of page PNG paths on success (or the already-rendered pages
    on a re-run), or ``None`` when the input is quarantined — not a PDF, or a
    PDF Ghostscript cannot render. A pre-existing page set is left untouched so
    re-runs are idempotent and never re-hit the renderer.
    """
    pdf_path = Path(pdf_path)
    pages_dir = Path(pages_dir)
    manifest_path = Path(manifest_path)

    if not _is_pdf(pdf_path):
        _quarantine(manifest_path, pdf=str(pdf_path), reason="not a PDF (no %PDF header)")
        return None

    out_dir = pages_dir / pdf_path.stem
    existing = sorted(out_dir.glob("p*.png"))
    if existing:
        return existing  # idempotent skip — never re-render or overwrite

    # Render into a staging sibling and publish with one atomic rename, so a
    # partial set from a failed *or* killed render is never left at the final
    # path where the idempotency skip would mistake it for a complete render.
    # Clear any staging leftover from a prior crash first.
    staging = out_dir.with_name(out_dir.name + ".rendering")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        pages = render(pdf_path, staging, dpi)
    except Exception as exc:  # a %PDF file gs still cannot render — quarantine
        shutil.rmtree(staging, ignore_errors=True)
        _quarantine(manifest_path, pdf=str(pdf_path), reason=f"unrenderable PDF: {exc}")
        return None
    if not pages:
        shutil.rmtree(staging, ignore_errors=True)
        _quarantine(manifest_path, pdf=str(pdf_path), reason="unrenderable PDF: no pages produced")
        return None

    out_dir.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(out_dir)
    pages = sorted(out_dir.glob("p*.png"))  # repoint from staging to the published dir
    _manifest.append(
        manifest_path, stage="render-pdf", pdf=str(pdf_path), pages=len(pages), dpi=dpi
    )
    return pages


app = typer.Typer(
    add_completion=False,
    help="Render a PDF into one PNG per page for the OCR bench (US19).",
)


@app.command()
def run(
    pdf: Annotated[
        Path,
        typer.Argument(exists=True, dir_okay=False, readable=True, help="the PDF to render"),
    ],
    pages_dir: Annotated[
        Path,
        typer.Option(help="directory to render pages under (pages/<stem>/)"),
    ] = Path("pages"),
    dpi: Annotated[int, typer.Option(help="render resolution")] = DEFAULT_DPI,
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of quarantined, unrenderable inputs"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Render the PDF; print each page path, or a quarantine note on stderr."""
    pages = render_pdf(pdf, pages_dir=pages_dir, manifest_path=manifest, dpi=dpi)
    if pages is None:
        # Quarantine is an expected outcome, not a crash: the batch still
        # finishes. Note it on stderr and exit cleanly.
        typer.echo(f"quarantined (see {manifest}): {pdf}", err=True)
        return
    for page in pages:
        typer.echo(str(page))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run render-pdf`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
