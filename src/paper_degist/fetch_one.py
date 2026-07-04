"""US2 — fetch one paper file from a URL and save it under files/.

Classify-then-dispatch (rule 02 / US2 case handling): look at what actually
came back — HTTP status first, then Content-Type, then a byte sniff — and
dispatch to a handler that knows the file type. A response matching no known
handler (paywall, error, unrecognized type) is quarantined to
``manifest.jsonl`` and skipped: never crash, never call an LLM in the loop.
The manifest is the queue of cases the script does not yet know how to handle.

Runnable from the command line (rule 03):

    uv run fetch-one <url>                    # fetch and save under files/
    uv run fetch-one <url> --files-dir out/
"""

import re
from pathlib import Path
from typing import Annotated, Callable, Optional, Protocol
from urllib.parse import urlsplit

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke


class Response(Protocol):
    """The response surface fetch_one reads — satisfied by ``httpx.Response``."""

    status_code: int
    headers: object  # a case-insensitive mapping with .get("content-type")
    content: bytes


Fetcher = Callable[[str], Response]

# Known Content-Type → file extension. Byte-sniff fallbacks live in classify().
_HTML_TYPES = {"text/html", "application/xhtml+xml"}


def _default_fetch(url: str) -> Response:
    """Real network fetch: GET the URL, follow redirects (AC5), bounded time."""
    import httpx

    return httpx.get(url, follow_redirects=True, timeout=30.0)


def classify(content_type: str, body: bytes) -> Optional[str]:
    """Return the file extension for a response, or ``None`` if unrecognized.

    Content-Type is the cheap first signal; a ``%PDF`` byte-sniff rescues a PDF
    served under a generic type (e.g. ``application/octet-stream``).
    """
    ct = (content_type or "").split(";", 1)[0].strip().lower()
    if ct == "application/pdf" or body[:4] == b"%PDF":
        return "pdf"
    if ct in _HTML_TYPES:
        return "html"
    return None


def _slug_tokens(text: str) -> frozenset[str]:
    """Lowercase alphanumeric word tokens of ``text`` — the unit of comparison.

    Slugifying to a *set of tokens* (not a raw string) makes the match tolerant
    of punctuation, case, and word order, and of a filename that drops the
    title's stop-words (US13 AC1: ``using-keyword-method-learn-vocabulary`` vs
    "Using the Keyword Method to Learn Vocabulary").
    """
    return frozenset(re.findall(r"[a-z0-9]+", text.lower()))


def filename_reflects_title(filename: str, title: str) -> bool:
    """True when the file's basename reflects the paper's ``title`` (US13).

    The match is subset containment: every token of the basename appears in the
    title. A descriptive slug basename is a subset of the fuller title (match);
    a generic repository/CGI name (``10.pdf``, ``viewcontent.cgi.pdf``) shares
    no tokens with the title (mismatch — a rename hand-off). An empty basename
    reflects nothing.
    """
    name_tokens = _slug_tokens(Path(filename).stem)
    if not name_tokens:
        return False
    return name_tokens <= _slug_tokens(title)


def _html_title(path: Path) -> Optional[str]:
    """The text of an HTML document's ``<title>``, or ``None`` if it has none."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="ignore"), "html.parser")
    if soup.title is None:
        return None
    title = soup.title.get_text().strip()
    return title or None


def _pdf_title(path: Path) -> Optional[str]:
    """The ``/Title`` from a PDF's document metadata, or ``None`` if absent."""
    from pypdf import PdfReader

    meta = PdfReader(str(path)).metadata
    title = (meta.title if meta else None) or ""
    return title.strip() or None


# The verifier dispatches on the saved file's type (US13 case handling): an
# ``<title>`` for HTML, document metadata for PDF. Any other suffix, or an
# extractor that raises on a malformed file, yields no title (the
# ``title-unverifiable`` branch) — the check never crashes.
_TITLE_EXTRACTORS: dict[str, Callable[[Path], Optional[str]]] = {
    ".html": _html_title,
    ".htm": _html_title,
    ".pdf": _pdf_title,
}


def _extract_title(path: Path) -> Optional[str]:
    """Extract the paper's real title from the saved file, or ``None``.

    Dispatches on the file extension; returns ``None`` for an unknown type or
    when the extractor cannot read a title (missing element/metadata, or a
    malformed file that makes the parser raise) — absence of a title is the
    ``title-unverifiable`` case, never a crash.
    """
    extractor = _TITLE_EXTRACTORS.get(path.suffix.lower())
    if extractor is None:
        return None
    try:
        return extractor(path)
    except Exception:
        return None


def _target_path(url: str, ext: str, files_dir: Path) -> Path:
    """Derive ``files/<basename>.<ext>`` from the URL path basename."""
    basename = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1] or "index"
    if basename.lower().endswith(f".{ext}"):
        return files_dir / basename
    return files_dir / f"{basename}.{ext}"


def _verify_save(target: Path, manifest_path: Path) -> None:
    """After a fresh save, check the filename reflects the paper's title (US13).

    Additive read-side check on the successful-save path: extract the title from
    the saved file itself and compare its slug tokens to the basename. A match
    writes nothing. A mismatch, or a title that cannot be extracted, appends a
    note to the manifest — a human rename hand-off, never an automatic rename,
    never a crash, never an LLM. The file stays saved either way.
    """
    title = _extract_title(target)
    if title is None:
        _manifest.append(
            manifest_path,
            stage="fetch-one",
            file=str(target),
            reason=f"title-unverifiable: no extractable title in {target.name}",
        )
        return
    if filename_reflects_title(target.name, title):
        return
    _manifest.append(
        manifest_path,
        stage="fetch-one",
        file=str(target),
        title=title,
        reason="mismatch: filename does not reflect the paper's title (rename hand-off)",
    )


def _quarantine(
    manifest_path: Path,
    *,
    url: str,
    status: Optional[int],
    content_type: Optional[str],
    reason: str,
) -> None:
    """Append one unhandled-case record to the manifest, so the batch finishes."""
    _manifest.append(
        manifest_path,
        stage="fetch-one",
        url=url,
        status=status,
        content_type=content_type,
        reason=reason,
    )


def fetch_one(
    url: str,
    *,
    files_dir: Path = Path("files"),
    manifest_path: Path = Path("manifest.jsonl"),
    fetch: Fetcher = _default_fetch,
) -> Optional[Path]:
    """Fetch ``url``, save the file under ``files_dir``, return its path.

    Returns the saved (or already-present) path on success, or ``None`` when the
    response is quarantined. A pre-existing target is left untouched so re-runs
    are idempotent (US 7 can detect what is genuinely new).
    """
    files_dir = Path(files_dir)
    manifest_path = Path(manifest_path)

    try:
        resp = fetch(url)
    except Exception as exc:  # network/timeout — quarantine, do not crash
        _quarantine(
            manifest_path,
            url=url,
            status=None,
            content_type=None,
            reason=f"fetch error: {exc}",
        )
        return None

    content_type = resp.headers.get("content-type", "")
    if resp.status_code >= 400:
        _quarantine(
            manifest_path,
            url=url,
            status=resp.status_code,
            content_type=content_type,
            reason=f"http {resp.status_code}",
        )
        return None

    ext = classify(content_type, resp.content)
    if ext is None:
        _quarantine(
            manifest_path,
            url=url,
            status=resp.status_code,
            content_type=content_type,
            reason="unrecognized content-type/body",
        )
        return None

    target = _target_path(url, ext, files_dir)
    if target.exists():
        return target  # idempotent skip — never overwrite

    files_dir.mkdir(parents=True, exist_ok=True)
    target.write_bytes(resp.content)
    _verify_save(target, manifest_path)  # US13: flag a name that misfits the title
    return target


app = typer.Typer(
    add_completion=False,
    help="Fetch one paper file from a URL and save it under files/ (US2 AC2).",
)


@app.command()
def run(
    url: Annotated[str, typer.Argument(help="the URL to fetch")],
    files_dir: Annotated[
        Path,
        typer.Option(help="directory to save fetched files into"),
    ] = Path("files"),
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of quarantined, unhandled responses"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Fetch the URL; print the saved path, or a quarantine note on stderr."""
    target = fetch_one(url, files_dir=files_dir, manifest_path=manifest, fetch=_default_fetch)
    if target is None:
        # Quarantine is an expected outcome, not a crash: the batch still
        # finishes. Note it on stderr and exit cleanly.
        typer.echo(f"quarantined (see {manifest}): {url}", err=True)
        return
    typer.echo(str(target))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run fetch-one`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
