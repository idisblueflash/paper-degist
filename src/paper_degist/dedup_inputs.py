"""US14 — collapse inputs pointing at the same DOI down to one, before fetching.

One paper is routinely reached by several inputs: a bare DOI, its ``doi.org``
link, and a publisher URL that embeds the same DOI in its path. These are the
same paper, but nothing downstream recognizes it — each is fetched and recorded
independently. This step is a pure, offline filter that runs **before**
fetch-one: it reads a list of inputs, canonicalizes any DOI it can read out of
each one, and keeps only the first input for each distinct DOI, dropping the
rest to the manifest.

The step makes **no network call and no LLM call** (rule 02): it reads the DOI
already visible in the input string. An input with no extractable DOI passes
through unchanged — the step cannot prove it duplicates anything without a
network lookup, so it never drops it.

Runnable from the command line (rule 03):

    uv run dedup-inputs inputs.txt          # read a file
    cat inputs.txt | uv run dedup-inputs    # read stdin
"""

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke
from paper_degist.resolve_oa import doi_from


def normalize_doi(text: str) -> str | None:
    """Return the canonical dedup key for ``text`` — a normalized DOI — or None.

    Reuses ``resolve_oa.doi_from`` to *extract* the DOI (a ``doi.org`` link, a
    bare ``10.\\d+/…`` DOI, or a publisher URL that embeds one), then normalizes
    it to a case-folded key: DOIs are case-insensitive, so
    ``https://doi.org/10.X`` and ``10.x`` fold to one key. Scheme/prefix
    stripping is already implicit — ``doi_from`` captures from ``10.`` onward, so
    a ``doi.org`` prefix never enters the key. Returns ``None`` when no DOI is
    extractable (rule 02: that input cannot be deduped offline).
    """
    doi = doi_from(text)
    return doi.lower() if doi is not None else None


def dedup_inputs(
    inputs: list[str],
    *,
    manifest_path: Path = Path("manifest.jsonl"),
) -> list[str]:
    """Keep the first input per distinct normalized DOI; drop the rest.

    Classifies each input on whether a DOI is extractable, then dispatches
    (rule 02): **no key** → pass through (cannot dedup offline); **first sight of
    a key** → keep and remember which input owns it; **repeat key** → drop and
    append a ``duplicate`` record to the manifest. Survivors are returned in
    first-seen order, so the step is a drop-in filter between parse-url and
    fetch-one.
    """
    manifest_path = Path(manifest_path)
    kept: list[str] = []
    seen: dict[str, str] = {}
    for item in inputs:
        key = normalize_doi(item)
        if key is None:
            kept.append(item)
        elif key not in seen:
            seen[key] = item
            kept.append(item)
        else:
            _manifest.append(
                manifest_path,
                stage="dedup-inputs",
                input=item,
                doi=key,
                duplicate_of=seen[key],
            )
    return kept


app = typer.Typer(
    add_completion=False,
    help="Collapse inputs pointing at the same DOI down to one, before fetching (US14).",
)


@app.command()
def run(
    file: Annotated[
        Optional[Path],
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="list of inputs, one per line; reads stdin when omitted",
        ),
    ] = None,
    manifest: Annotated[
        Path,
        typer.Option(help="manifest the dropped duplicates are recorded in"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Print the surviving inputs one per line, in first-seen order."""
    text = file.read_text(encoding="utf-8") if file else sys.stdin.read()
    inputs = [line.strip() for line in text.splitlines() if line.strip()]
    for item in dedup_inputs(inputs, manifest_path=manifest):
        typer.echo(item)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run dedup-inputs`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
