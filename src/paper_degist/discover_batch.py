"""US31 — fan a topic across queries and sources, merge the union.

`discover` (US25/27/29) does one query against one source per run; this driver
is the deferred fan-out/merge composition: call the same `discover` core once
per (query, source) pair, then merge + dedup the union into one candidate list.
Every per-pair behaviour (adapter quirks, empty-result / api-error /
missing-key quarantine, per-run manifest rows) is inherited from `discover`,
not reimplemented — a pair that quarantines takes out only itself (rule 02).

Runnable from the command line (rule 03):

    uv run discover-batch "state space models" "linear attention" --source arxiv
"""

import json
import sys
import time
from pathlib import Path
from typing import Annotated, Callable, Optional, Sequence

import typer

from paper_degist import _manifest, _openalex
from paper_degist._cli import invoke
from paper_degist.abstract_filter import candidate_doi_key
from paper_degist.discover import (
    ARXIV_MIN_INTERVAL,
    OPENALEX_MIN_INTERVAL,
    S2_MIN_INTERVAL,
    Search,
    _build_registry,
    discover,
)

# The zero-setup default: the keyless pair. Key-gated sources (s2 with a key,
# scholar/scholar-author) join via repeated --source.
DEFAULT_SOURCES = ["arxiv", "openalex"]

# Per-source politeness intervals the fan-out paces each source by (US38). The
# first call to a source never waits; every later call to *that* source pays its
# interval. The pacing is per source and deliberately conservative — it charges
# the full interval on a source's repeat even if another source ran in between,
# rather than crediting the elapsed time, so it never under-waits a real rate
# limit (precise elapsed-time pacing is a deferred refinement — US38 spec). A
# source with no configured interval (SerpAPI scholar lanes) never waits.
SOURCE_MIN_INTERVAL = {
    "arxiv": ARXIV_MIN_INTERVAL,
    "openalex": OPENALEX_MIN_INTERVAL,
    "s2": S2_MIN_INTERVAL,
}


def merge_keys(record: dict) -> list[tuple]:
    """The dedup identities of a candidate: normalized DOI and (source, id).

    Two records are the same paper when their normalized DOIs match (US14's
    `normalize_doi`, via US26's `candidate_doi_key`) or when the same source
    returned the same `source_id` twice (two overlapping queries) — the
    source-id identity never catches a cross-source match. A record is
    registered under **every** identity it carries, so a later copy that
    shares only one of them (a DOI-less repeat of a DOI-carrying hit) still
    dedups. No identity at all → not dedupable, always kept.
    """
    keys: list[tuple] = []
    doi = candidate_doi_key(record)
    if doi is not None:
        keys.append(("doi", doi))
    source_id = record.get("source_id")
    if record.get("source") and source_id:
        keys.append(("source-id", record["source"], source_id))
    return keys


def discover_batch(
    queries: Sequence[str],
    sources: Sequence[str],
    *,
    registry: dict[str, Search],
    manifest_path: Path = Path("manifest.jsonl"),
    pause: Callable[[float], None] = time.sleep,
) -> Optional[list[dict]]:
    """Fan `queries` across `sources`; return the merged candidate records."""
    manifest_path = Path(manifest_path)
    merged: list[dict] = []
    kept_at: dict[tuple, int] = {}
    called_sources: set[str] = set()
    for query in queries:
        for source in sources:
            # Politeness pacing (US31 AC7 / US38 AC5): the first call to a source
            # never waits; every later call to that source pays its interval
            # (conservatively — see SOURCE_MIN_INTERVAL). Sources with no
            # configured interval (SerpAPI lanes) never wait.
            interval = SOURCE_MIN_INTERVAL.get(source)
            if interval and source in called_sources:
                pause(interval)
            called_sources.add(source)
            records = discover(
                query, source, manifest_path=manifest_path, registry=registry
            )
            if records is None:
                continue
            for record in records:
                keys = merge_keys(record)
                match = next((key for key in keys if key in kept_at), None)
                if match is None:
                    for key in keys:
                        kept_at[key] = len(merged)
                    merged.append(record)
                    continue
                index = kept_at[match]
                kept = merged[index]
                # First-seen wins, with one deterministic upgrade (AC4): a
                # duplicate that carries an abstract replaces a kept record
                # that has none, so the merged list keeps the richest copy
                # for US26's similarity filter. The loser is the filtered one.
                if record.get("abstract_present") and not kept.get("abstract_present"):
                    merged[index] = record
                    for key in keys:
                        kept_at[key] = index
                    record, kept = kept, record
                _manifest.append(
                    manifest_path,
                    stage="discover-batch",
                    event="filtered",
                    url=record.get("url", ""),
                    source=record.get("source", ""),
                    reason="dedup-doi" if match[0] == "doi" else "dedup-source-id",
                    duplicate_of=kept.get("url", ""),
                )
    if not merged:
        # Every pair quarantined or came back empty (AC6) — the per-pair rows
        # already say why; this row says the *batch* yielded nothing.
        _manifest.append(
            manifest_path,
            stage="discover-batch",
            queries=len(queries),
            sources=list(sources),
            reason="empty-batch: no candidates from any (query, source) pair",
        )
        return None
    _manifest.append(
        manifest_path,
        stage="discover-batch",
        queries=len(queries),
        sources=list(sources),
        result_count=len(merged),
    )
    return merged


app = typer.Typer(
    add_completion=False,
    help="Fan topic queries across discover sources and merge the union (US31).",
)


@app.command()
def run(
    queries: Annotated[
        Optional[list[str]],
        typer.Argument(help="topic queries; reads one query per line from stdin when omitted"),
    ] = None,
    source: Annotated[
        Optional[list[str]],
        typer.Option(
            "--source",
            help="a discover source to fan across (repeatable); default: arxiv + openalex",
        ),
    ] = None,
    max_results: Annotated[
        int,
        typer.Option("--max-results", help="cap on candidates per (query, source) pair"),
    ] = 25,
    s2_api_key: Annotated[
        Optional[str],
        typer.Option(envvar="S2_API_KEY", help="optional Semantic Scholar API key"),
    ] = None,
    email: Annotated[
        Optional[str],
        typer.Option(
            envvar="OPENALEX_EMAIL",
            help="contact email for OpenAlex's faster polite pool (keyless without it)",
        ),
    ] = None,
    serpapi_key: Annotated[
        Optional[str],
        typer.Option(
            envvar="SERPAPI_API_KEY",
            help="SerpAPI key — required for --source scholar / scholar-author",
        ),
    ] = None,
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of per-pair discover runs and batch records"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Fan the queries across the sources; print the merged JSONL, or a note."""
    if not queries:
        queries = [line.strip() for line in sys.stdin if line.strip()]
    sources = source or list(DEFAULT_SOURCES)
    if "openalex" in sources and not email:
        # Mirrors discover's US29 AC4: a missing contact email is politeness,
        # not an access requirement — warn and use the common pool.
        typer.echo(_openalex.NO_EMAIL_WARNING, err=True)
    records = discover_batch(
        queries,
        sources,
        registry=_build_registry(max_results, s2_api_key, email, serpapi_key),
        manifest_path=manifest,
    )
    if records is None:
        typer.echo(
            f"quarantined (see {manifest}): empty batch for {len(queries)} "
            f"quer{'y' if len(queries) == 1 else 'ies'} x {sources}",
            err=True,
        )
        return
    for record in records:
        typer.echo(json.dumps(record, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run discover-batch`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
