"""US34 — enrich missing abstracts for candidates by DOI via OpenAlex.

For each candidate whose ``abstract_present`` is false (or absent), fetches the
Work from OpenAlex by DOI and reconstructs the abstract from its
``abstract_inverted_index``. Candidates already carrying an abstract pass
through unchanged. Every drop is auditable in ``manifest.jsonl``; nothing crashes.

Runnable from the command line (rule 03):

    uv run enrich-abstract candidates.jsonl --email you@example.com
    uv run discover "attention mechanisms" | uv run enrich-abstract
"""

import json
import sys
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer

from paper_degist import _manifest, _openalex
from paper_degist._cli import invoke
from paper_degist.abstract_filter import load_candidates
from paper_degist.discover import _bare_doi, reconstruct_abstract


def _default_fetch_work(doi: str, email: Optional[str]) -> dict:
    """Fetch a single OpenAlex Work by bare DOI."""
    return _openalex.fetch_work_by_doi(doi, email)


def enrich_abstract(
    candidates: list[dict],
    *,
    email: Optional[str] = None,
    manifest_path: Path = Path("manifest.jsonl"),
    _fetch_work: Optional[Callable] = None,
) -> list[dict]:
    """Fill missing abstracts from OpenAlex (US34).

    Returns a list of emitted candidate dicts (enriched or passed-through).
    Every quarantined candidate leaves an auditable manifest row.
    """
    if _fetch_work is None:
        _fetch_work = _default_fetch_work
    manifest_path = Path(manifest_path)
    emitted: list[dict] = []

    for candidate in candidates:
        url = candidate.get("url") or candidate.get("doi") or ""

        # AC2: already has an abstract — pass through unchanged.
        if candidate.get("abstract_present"):
            emitted.append(candidate)
            continue

        # Extract DOI (AC3: quarantine if none).
        raw_doi = candidate.get("doi")
        doi = _bare_doi(raw_doi) if raw_doi else None
        if not doi:
            _manifest.append(
                manifest_path,
                stage="enrich-abstract",
                event="quarantined",
                url=url,
                reason="no-doi",
                title=candidate.get("title") or "",
            )
            continue

        # AC4: fetch from OpenAlex — quarantine on error.
        try:
            work = _fetch_work(doi, email)
        except Exception as exc:
            _manifest.append(
                manifest_path,
                stage="enrich-abstract",
                event="quarantined",
                url=url,
                reason="doi-not-found",
                doi=doi,
                detail=str(exc),
            )
            continue

        # AC5: no abstract on record — quarantine.
        inverted = work.get("abstract_inverted_index")
        abstract = reconstruct_abstract(inverted)
        if not abstract:
            _manifest.append(
                manifest_path,
                stage="enrich-abstract",
                event="quarantined",
                url=url,
                reason="no-abstract-on-record",
                doi=doi,
            )
            continue

        # AC1: emit enriched candidate.
        enriched = {**candidate, "abstract": abstract, "abstract_present": True}
        emitted.append(enriched)

    return emitted


app = typer.Typer(
    add_completion=False,
    help="Fill missing abstracts for candidates by DOI via OpenAlex (US34).",
)


@app.command()
def run(
    candidates_file: Annotated[
        Optional[Path],
        typer.Argument(help="Candidate JSONL file; reads stdin when omitted"),
    ] = None,
    email: Annotated[
        Optional[str],
        typer.Option("--email", envvar="OPENALEX_EMAIL",
                     help="contact email for the OpenAlex polite pool"),
    ] = None,
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of quarantined candidates"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Enrich candidates lacking abstracts by fetching them from OpenAlex."""
    if not email:
        typer.echo(_openalex.NO_EMAIL_WARNING, err=True)
    if candidates_file is not None:
        text = candidates_file.read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()

    candidates = load_candidates(text, manifest_path=manifest, stage="enrich-abstract")
    enriched = enrich_abstract(candidates, email=email, manifest_path=manifest)
    for record in enriched:
        typer.echo(json.dumps(record, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run enrich-abstract`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
