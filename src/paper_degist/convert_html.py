"""US5 — convert a saved HTML paper into a structure-preserving Markdown file.

An HTML paper is already structured markup, so headings, lists, tables, and
code blocks map near-directly to Markdown (unlike the lossy PDF path, US3+US4).
This is the ``.html`` branch of the convert stage's extension dispatch.

Runnable from the command line (rule 03):

    uv run convert-html files/paper.html          # write files/paper.md
    uv run convert-html files/paper.html --manifest manifest.jsonl
"""

from pathlib import Path
from typing import Annotated, Optional

import typer

from markdownify import markdownify

from paper_degist import _manifest
from paper_degist._cli import invoke

# Below this many non-whitespace characters, the extracted Markdown is treated
# as a hollow SPA shell rather than a real paper (AC2). A live arxiv-style HTML
# paper yields thousands of non-ws chars; a `<div id="__next"></div>` yields 0.
_MIN_CONTENT_CHARS = 200

# The convert stage dispatches by file extension; this is the `.html` handler,
# so it classifies its own input first (rule 02) and quarantines anything else
# rather than markdownifying, e.g., PDF bytes into a garbage `.md`.
_HTML_SUFFIXES = {".html", ".htm"}


def html_to_markdown(html: str) -> str:
    """Convert an HTML document to Markdown, preserving structure."""
    return markdownify(html, heading_style="ATX")


def _content_chars(markdown: str) -> int:
    """Count non-whitespace characters — the content-density signal (AC2)."""
    return len("".join(markdown.split()))


def _quarantine(manifest_path: Path, *, path: str, reason: str) -> None:
    """Append one unhandled-case record to the manifest, so the batch finishes."""
    _manifest.append(manifest_path, stage="convert-html", path=path, reason=reason)


def convert_html(
    path: Path,
    *,
    manifest_path: Path = Path("manifest.jsonl"),
    min_content_chars: int = _MIN_CONTENT_CHARS,
) -> Optional[Path]:
    """Convert ``files/<name>.html`` to ``files/<name>.md``; return its path.

    Returns the saved (or already-present) ``.md`` path on success, or ``None``
    when the input is quarantined — a non-``.html`` extension, an undecodable
    (non-UTF-8) file, or Markdown below the content-density threshold (AC2). A
    pre-existing ``.md`` is left untouched so re-runs are idempotent.
    """
    path = Path(path)
    manifest_path = Path(manifest_path)

    if path.suffix.lower() not in _HTML_SUFFIXES:
        # Not this handler's input type — quarantine rather than convert (the
        # `.pdf` path is US3+US4; the top-level dispatcher lands with it).
        _quarantine(
            manifest_path,
            path=str(path),
            reason=f"not an HTML file (unexpected extension {path.suffix!r})",
        )
        return None

    try:
        html = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # A non-UTF-8 file is an unhandled case, not a crash (rule 02): quarantine
        # it so the batch finishes. A future branch can sniff/transcode encodings.
        _quarantine(manifest_path, path=str(path), reason="undecodable HTML (not UTF-8)")
        return None

    markdown = html_to_markdown(html)
    if _content_chars(markdown) < min_content_chars:
        _quarantine(manifest_path, path=str(path), reason="HTML too thin")
        return None

    target = path.with_suffix(".md")
    if target.exists():
        return target  # idempotent skip — never overwrite
    target.write_text(markdown, encoding="utf-8")
    return target


app = typer.Typer(
    add_completion=False,
    help="Convert a saved HTML paper into a structure-preserving Markdown file (US5).",
)


@app.command()
def run(
    file: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="the .html file to convert",
        ),
    ],
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of quarantined, too-thin HTML"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Convert the HTML; print the saved .md path, or a quarantine note on stderr."""
    target = convert_html(file, manifest_path=manifest)
    if target is None:
        # Quarantine (HTML too thin) is an expected outcome, not a crash: the
        # batch still finishes. Note it on stderr and exit cleanly.
        typer.echo(f"quarantined (see {manifest}): {file}", err=True)
        return
    typer.echo(str(target))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run convert-html`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
