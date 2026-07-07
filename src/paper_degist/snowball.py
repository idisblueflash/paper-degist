"""US33 — snowball a seed paper's references and citers via OpenAlex.

Given a seed DOI (or OpenAlex URL), emits the papers it cites (refs) and/or
the papers that cite it (citers) as discover-shaped candidate JSONL — the
same format as ``discover --source openalex``, ready for ``abstract-filter``,
``rank-cited``, or ``fetch-one``.

Runnable from the command line (rule 03):

    uv run snowball 10.48550/arxiv.1706.03762 --direction refs --max-refs 50
    uv run snowball 10.48550/arxiv.1706.03762 --email you@example.com
"""

import json
import sys
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer

from paper_degist import _manifest, _openalex
from paper_degist._cli import invoke
from paper_degist.discover import (
    Candidate,
    _bare_doi,
    _bare_openalex_id,
    reconstruct_abstract,
)

DEFAULT_MAX = 200


def _work_to_candidate(work: dict) -> Optional[Candidate]:
    """Map one OpenAlex Work dict to a Candidate; None when no usable URL (AC6)."""
    source_id = _bare_openalex_id(work.get("id"))
    doi = _bare_doi(work.get("doi"))
    url = work.get("doi") or work.get("id") or ""
    if not url:
        return None
    authors = [
        name
        for authorship in (work.get("authorships") or [])
        if isinstance(authorship, dict)
        and (name := (authorship.get("author") or {}).get("display_name"))
    ]
    cited_by_raw = work.get("cited_by_count")
    cited_by = int(cited_by_raw) if isinstance(cited_by_raw, int) and not isinstance(cited_by_raw, bool) else None
    return Candidate(
        title=work.get("title") or "",
        authors=authors,
        abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
        url=url,
        published=work.get("publication_date"),
        source="openalex",
        source_id=source_id,
        doi=doi,
        pdf_url=_openalex.pdf_url_from_work(work),
        cited_by=cited_by,
    )


def _candidates_from_page(page: dict, manifest_path: Path) -> list[dict]:
    """Convert one page of OpenAlex results, filtering no-url works."""
    records = []
    for work in page.get("results") or []:
        candidate = _work_to_candidate(work)
        if candidate is None:
            _manifest.append(
                manifest_path,
                stage="snowball",
                event="filtered",
                url="",
                reason="no-url",
                title=work.get("title") or "",
            )
        else:
            records.append(candidate.to_record())
    return records


def _default_fetch_seed(doi: str, email: Optional[str]) -> dict:
    return _openalex.fetch_work_by_doi(doi, email)


def _default_fetch_refs(ref_ids: list[str], email: Optional[str]) -> dict:
    """Batch-fetch the works a seed cites by their OpenAlex IDs.

    The seed's ``referenced_works`` field carries the IDs; this fetches them
    using the ``openalex_ids`` filter (pipe-separated, up to 200 per request).
    An empty list returns an empty page without hitting the network.
    """
    if not ref_ids:
        return {"meta": {}, "results": []}
    ids_str = "|".join(ref_ids[:200])
    return _openalex.search_works({"filter": f"ids.openalex:{ids_str}", "per_page": 200}, email)


def _default_fetch_citers(openalex_id: str, max_citers: int, email: Optional[str]) -> dict:
    """Fetch papers that cite the seed via the ``cites:`` filter."""
    return _openalex.search_works(
        {
            "filter": f"cites:{openalex_id}",
            "per_page": min(max_citers, 200),
            "sort": "cited_by_count:desc",
        },
        email,
    )


def snowball(
    seed: str,
    *,
    direction: str = "both",
    max_refs: int = DEFAULT_MAX,
    max_citers: int = DEFAULT_MAX,
    email: Optional[str] = None,
    manifest_path: Path = Path("manifest.jsonl"),
    _fetch_seed: Callable = _default_fetch_seed,
    _fetch_refs: Callable = _default_fetch_refs,
    _fetch_citers: Callable = _default_fetch_citers,
) -> Optional[list[dict]]:
    """Expand a seed DOI into its reference/citer candidates (US33)."""
    manifest_path = Path(manifest_path)

    # Resolve the seed (AC5).
    try:
        seed_work = _fetch_seed(seed, email)
    except Exception as exc:
        reason = "seed-not-found" if "404" in str(exc) or "not found" in str(exc).lower() else "api-error"
        _manifest.append(
            manifest_path,
            stage="snowball",
            event="quarantined",
            url=seed,
            reason=f"{reason}: {exc}",
        )
        return None

    seed_id = _bare_openalex_id(seed_work.get("id"))
    # Extract the seed's reference IDs for the refs lane (AC1).
    raw_ref_ids = [
        _bare_openalex_id(url)
        for url in (seed_work.get("referenced_works") or [])
        if url
    ]

    seen: set[str] = set()  # deduplicate by source_id (AC3)
    records: list[dict] = []

    def _add(batch: list[dict]) -> None:
        for r in batch:
            sid = r.get("source_id", "")
            if sid and sid in seen:
                continue
            seen.add(sid)
            records.append(r)

    # AC1: references the seed cites (fetch by IDs from referenced_works).
    if direction in ("refs", "both"):
        ref_ids = raw_ref_ids[:max_refs]
        try:
            refs_page = _fetch_refs(ref_ids, email)
        except Exception as exc:
            _manifest.append(
                manifest_path,
                stage="snowball",
                event="quarantined",
                url=seed,
                reason=f"api-error fetching refs: {exc}",
            )
        else:
            ref_records = _candidates_from_page(refs_page, manifest_path)
            _add(ref_records[:max_refs])

    # AC2: papers that cite the seed.
    if direction in ("citers", "both"):
        try:
            citers_page = _fetch_citers(seed_id, max_citers, email)
        except Exception as exc:
            _manifest.append(
                manifest_path,
                stage="snowball",
                event="quarantined",
                url=seed,
                reason=f"api-error fetching citers: {exc}",
            )
        else:
            citer_records = _candidates_from_page(citers_page, manifest_path)
            _add(citer_records[:max_citers])

    return records


app = typer.Typer(
    add_completion=False,
    help="Expand a seed paper into its references and/or citers via OpenAlex (US33).",
)


@app.command()
def run(
    seed: Annotated[
        str,
        typer.Argument(help="Seed paper DOI (bare or URL form) or OpenAlex Work URL"),
    ],
    direction: Annotated[
        str,
        typer.Option("--direction", help="refs, citers, or both (default)"),
    ] = "both",
    max_refs: Annotated[
        int,
        typer.Option("--max-refs", help="maximum reference candidates to emit"),
    ] = DEFAULT_MAX,
    max_citers: Annotated[
        int,
        typer.Option("--max-citers", help="maximum citer candidates to emit"),
    ] = DEFAULT_MAX,
    email: Annotated[
        Optional[str],
        typer.Option("--email", envvar="OPENALEX_EMAIL",
                     help="contact email for the OpenAlex polite pool"),
    ] = None,
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of filtered/quarantined candidates"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Print the seed's references and/or citers as JSONL candidates."""
    if not email:
        typer.echo(_openalex.NO_EMAIL_WARNING, err=True)
    candidates = snowball(
        seed,
        direction=direction,
        max_refs=max_refs,
        max_citers=max_citers,
        email=email,
        manifest_path=manifest,
    )
    if candidates is None:
        typer.echo(f"quarantined (see {manifest}): seed could not be resolved", err=True)
        return
    for record in candidates:
        typer.echo(json.dumps(record, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run snowball`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
