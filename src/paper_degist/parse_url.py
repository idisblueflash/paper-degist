"""US1 AC1 — extract URLs from a text blob.

Parses a free-text blob (e.g. a markdown notes file) into a de-duplicated
list of http(s) URLs, preserving first-seen order.

Runnable from the command line:

    uv run parse-url <file>      # read a file
    cat file | uv run parse-url  # read stdin

Prints one URL per line.
"""

import argparse
import re
import sys

# http(s) URL up to the first whitespace or markdown-link closing paren.
_URL_RE = re.compile(r"https?://[^\s)]+")


def parse_url(text: str) -> list[str]:
    """Return the http(s) URLs found in ``text``, de-duplicated, in order."""
    seen: set[str] = set()
    urls: list[str] = []
    for match in _URL_RE.findall(text):
        url = match.rstrip(".,;")  # strip trailing sentence punctuation
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract http(s) URLs from a text blob (US1 AC1)."
    )
    parser.add_argument(
        "file",
        nargs="?",
        help="text file to parse; reads stdin when omitted",
    )
    args = parser.parse_args(argv)

    text = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
    for url in parse_url(text):
        print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
