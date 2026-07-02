"""US1 AC1 — extract URLs from a text blob.

Parses a free-text blob (e.g. a markdown notes file) into a de-duplicated
list of http(s) URLs, preserving first-seen order.

Runnable from the command line:

    uv run parse-url <file>      # read a file
    cat file | uv run parse-url  # read stdin

Prints one URL per line.
"""

import re
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from paper_degist._cli import invoke

# http(s) URL grabbed generously up to whitespace/angle-bracket. The left
# lookbehind rejects a scheme embedded in a larger token (``abchttps://``);
# IGNORECASE accepts mixed-case schemes while ``findall`` preserves the
# original matched text. Wrapper/prose punctuation is trimmed afterwards so a
# legitimate ``)`` inside the path (``paper_(v2).pdf``) survives.
_URL_RE = re.compile(r"(?<![A-Za-z0-9+.\-])https?://[^\s<>]+", re.IGNORECASE)

# Prose punctuation that is never part of a URL when it sits at the very end.
_TRAILING_PUNCT = ".,;:!?\"'"


def _trim_trailing(url: str) -> str:
    """Strip trailing prose punctuation and *unbalanced* wrapper parens.

    A ``)`` is only stripped when the match holds more ``)`` than ``(`` — i.e.
    it closes a wrapper the match never opened (Markdown ``[t](url)``), never a
    balanced pair that belongs to the URL (Wikipedia ``paper_(v2)``).
    """
    while url:
        last = url[-1]
        if last in _TRAILING_PUNCT:
            url = url[:-1]
        elif last == ")" and url.count(")") > url.count("("):
            url = url[:-1]
        else:
            break
    return url


def parse_url(text: str) -> list[str]:
    """Return the http(s) URLs found in ``text``, de-duplicated, in order.

    De-duplication is by exact post-cleanup string with no normalization, so
    scheme case, a trailing slash, query strings, and fragments are all treated
    as distinct URLs.
    """
    seen: set[str] = set()
    urls: list[str] = []
    for match in _URL_RE.findall(text):
        url = _trim_trailing(match)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


app = typer.Typer(
    add_completion=False,
    help="Extract http(s) URLs from a text blob (US1 AC1).",
)


@app.command()
def run(
    file: Annotated[
        Optional[Path],
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="text file to parse; reads stdin when omitted",
        ),
    ] = None,
) -> None:
    """Print one http(s) URL per line, de-duplicated in first-seen order."""
    # The ``exists``/``readable`` constraints on ``file`` let Typer reject a
    # missing or unreadable path up front with a clean stderr message and a
    # non-zero exit code, instead of an ``open()`` traceback.
    text = file.read_text(encoding="utf-8") if file else sys.stdin.read()
    for url in parse_url(text):
        typer.echo(url)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run parse-url`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
