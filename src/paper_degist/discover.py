"""US25 — discover candidate papers by topic from a scholarly API.

The pipeline used to *start* at ``parse-url``/``fetch-one`` — it assumed you
already had the URLs. This step adds the upstream front: given a topic query,
search a free scholarly API and emit each candidate paper (with its abstract) as
one JSONL record, drop-in to the filter → fetch chain. It is deliberately
**coarse and high-recall** — cast a wide net and over-return; narrowing is
US26's job.

Two sources are in scope, chosen by ``--source`` (rule 02: a **registry**, not a
per-source branch): **arxiv** (no key, an Atom feed) and **s2** (Semantic
Scholar, a JSON API with an optional ``tldr`` one-line summary US26 can use as a
cheap pre-filter signal). Each is an *adapter* that issues the search and maps
the API's response into one **common schema** — ``title``, ``authors``,
``abstract``, ``url``, ``published``, ``source``, ``source_id``, plus ``doi`` and
``tldr`` when the record carries them — encoding each API's fixed quirks once.

Classify-then-dispatch (rule 02) runs in two layers. First on ``--source``: a
known adapter → use it; anything else → quarantine (unknown source) **without
touching the network**. Then on the transport result: hits → emit JSONL; an
empty result → quarantine (empty-result); an HTTP error / rate-limit →
quarantine (api-error) — with **distinct** reasons. Never crash, never call an
LLM to classify or rescue a record.

Runnable from the command line (rule 03):

    uv run discover "sparse mixture-of-experts routing" --source arxiv
    uv run discover "CRISPR base editing off-target effects" --source s2
"""

import json
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke

# arXiv asks for a ~3 s delay between calls (its published rate-limit etiquette).
# discover issues one query per run, so a single call needs no wait; the constant
# is encoded once here for the deferred batch driver (see DEVLOG / "Later stages")
# that walks several queries and must space its hits.
ARXIV_MIN_INTERVAL = 3.0

ARXIV_ENDPOINT = "https://export.arxiv.org/api/query"
S2_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
# The Semantic Scholar fields we ask for — the common-schema inputs plus tldr.
S2_FIELDS = "title,abstract,authors,externalIds,url,publicationDate,tldr"

# The Atom namespace every arXiv feed element lives under.
_ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass(frozen=True)
class Candidate:
    """One discovered paper in the common schema, source-agnostic.

    ``abstract`` may be ``None`` (some records carry no abstract); the emitted
    record still carries it with an ``abstract_present`` flag so US26 can drop it
    cheaply rather than discovery dropping it (AC3 — discovery casts wide).
    ``doi`` and ``tldr`` are emitted only when the record actually has them.
    """

    title: str
    authors: list[str]
    abstract: Optional[str]
    url: str
    published: Optional[str]
    source: str
    source_id: str
    doi: Optional[str] = None
    tldr: Optional[str] = None

    def to_record(self) -> dict:
        """The JSONL record: always-present fields, plus doi/tldr when carried."""
        record: dict = {
            "title": self.title,
            "authors": list(self.authors),
            "abstract": self.abstract,
            "abstract_present": bool(self.abstract and self.abstract.strip()),
            "url": self.url,
            "published": self.published,
            "source": self.source,
            "source_id": self.source_id,
        }
        if self.doi:
            record["doi"] = self.doi
        if self.tldr:
            record["tldr"] = self.tldr
        return record


# A Search issues the query and maps the response into Candidates. It raises to
# signal an API/network error (the caller quarantines it); an empty list is a
# clean "no hits". Injected in tests; the defaults are the real HTTP adapters.
Search = Callable[[str], list[Candidate]]


def _clean(text: Optional[str]) -> Optional[str]:
    """Collapse arXiv's newline-wrapped whitespace; ``None`` stays ``None``."""
    if text is None:
        return None
    return " ".join(text.split())


def parse_arxiv_atom(xml_text: str) -> list[Candidate]:
    """Map an arXiv Atom feed into Candidates (rule 02: the quirk encoded once).

    arXiv wraps ``title``/``summary`` across newlines (collapsed here), always
    carries a ``summary`` (abstract), and puts the paper's id in ``<id>`` as an
    ``…/abs/<id>`` URL. The alternate ``text/html`` link is the landing URL. A
    feed with no ``<entry>`` (a zero-result query) yields an empty list.
    """
    root = ET.fromstring(xml_text)
    candidates: list[Candidate] = []
    for entry in root.findall(f"{_ATOM}entry"):
        entry_id = (entry.findtext(f"{_ATOM}id") or "").strip()
        source_id = entry_id.rsplit("/abs/", 1)[-1] if "/abs/" in entry_id else entry_id
        url = entry_id
        for link in entry.findall(f"{_ATOM}link"):
            if link.get("rel") == "alternate":
                url = link.get("href") or url
        authors = [
            name.strip()
            for author in entry.findall(f"{_ATOM}author")
            if (name := author.findtext(f"{_ATOM}name") or "").strip()
        ]
        candidates.append(
            Candidate(
                title=_clean(entry.findtext(f"{_ATOM}title")) or "",
                authors=authors,
                abstract=_clean(entry.findtext(f"{_ATOM}summary")),
                url=url,
                published=(entry.findtext(f"{_ATOM}published") or "").strip() or None,
                source="arxiv",
                source_id=source_id,
            )
        )
    return candidates


def parse_s2_json(data: dict) -> list[Candidate]:
    """Map a Semantic Scholar search response into Candidates (rule 02).

    S2 records commonly lack an abstract (kept as ``None`` — AC3), carry the DOI
    under ``externalIds.DOI``, and carry an optional ``tldr`` one-line summary
    (``tldr.text``) US26 can use as a cheap pre-filter signal (AC2).
    """
    candidates: list[Candidate] = []
    for item in data.get("data") or []:
        authors = [a["name"] for a in (item.get("authors") or []) if a.get("name")]
        doi = (item.get("externalIds") or {}).get("DOI")
        tldr_obj = item.get("tldr") or {}
        candidates.append(
            Candidate(
                title=item.get("title") or "",
                authors=authors,
                abstract=item.get("abstract"),
                url=item.get("url") or "",
                published=item.get("publicationDate"),
                source="s2",
                source_id=item.get("paperId") or "",
                doi=doi,
                tldr=tldr_obj.get("text"),
            )
        )
    return candidates


def _arxiv_search(max_results: int) -> Search:
    """Build the real arXiv adapter: query the Atom API, parse into Candidates."""

    def search(query: str) -> list[Candidate]:
        import httpx

        resp = httpx.get(
            ARXIV_ENDPOINT,
            params={"search_query": f"all:{query}", "start": 0, "max_results": max_results},
            headers={"User-Agent": "paper-degist/0.1 (https://github.com/idisblueflash/paper-degist)"},
            timeout=30.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return parse_arxiv_atom(resp.text)

    return search


def _s2_search(max_results: int, api_key: Optional[str]) -> Search:
    """Build the real Semantic Scholar adapter: query the JSON API, parse it.

    An optional API key raises the rate limit; without one S2 still answers
    (subject to a shared free-tier limit — a 429 raises and is quarantined as an
    api-error, distinct from an empty result).
    """

    def search(query: str) -> list[Candidate]:
        import httpx

        headers = {"User-Agent": "paper-degist/0.1"}
        if api_key:
            headers["x-api-key"] = api_key
        resp = httpx.get(
            S2_ENDPOINT,
            params={"query": query, "limit": max_results, "fields": S2_FIELDS},
            headers=headers,
            timeout=30.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return parse_s2_json(resp.json())

    return search


def _quarantine(manifest_path: Path, *, source: str, query: str, reason: str) -> None:
    """Append one unhandled-case record to the manifest, so the run finishes."""
    _manifest.append(
        manifest_path,
        stage="discover",
        source=source,
        query=query,
        reason=reason,
    )


def discover(
    query: str,
    source: str,
    *,
    manifest_path: Path = Path("manifest.jsonl"),
    registry: dict[str, Search],
) -> Optional[list[dict]]:
    """Search ``source`` for ``query``; return the candidate records, or None.

    Classify-then-dispatch (rule 02). Layer 1 — on the source: not a known
    adapter → quarantine (unknown source) **without touching the network** and
    return ``None`` (AC5). Layer 2 — on the transport result: an API/network
    error → quarantine (api-error); an empty result → quarantine (empty-result,
    a **distinct** reason); hits → append a ``discover`` success record with the
    result count and return one record dict per hit (AC1–AC4). Never crashes,
    never calls an LLM.
    """
    manifest_path = Path(manifest_path)

    search = registry.get(source)
    if search is None:
        _quarantine(
            manifest_path,
            source=source,
            query=query,
            reason=f"unknown source: {source!r} not in registry",
        )
        return None

    try:
        candidates = search(query)
    except Exception as exc:  # API error / rate-limit — quarantine, do not crash
        _quarantine(
            manifest_path,
            source=source,
            query=query,
            reason=f"api-error: {type(exc).__name__}: {exc}",
        )
        return None

    if not candidates:
        _quarantine(
            manifest_path,
            source=source,
            query=query,
            reason="empty-result: the search returned no candidates",
        )
        return None

    _manifest.append(
        manifest_path,
        stage="discover",
        source=source,
        query=query,
        result_count=len(candidates),
    )
    return [c.to_record() for c in candidates]


app = typer.Typer(
    add_completion=False,
    help="Discover candidate papers by topic from a scholarly API (US25).",
)


def _build_registry(max_results: int, s2_api_key: Optional[str]) -> dict[str, Search]:
    """The source registry (rule 02: a new source is one entry, not a branch)."""
    return {
        "arxiv": _arxiv_search(max_results),
        "s2": _s2_search(max_results, s2_api_key),
    }


@app.command()
def run(
    query: Annotated[str, typer.Argument(help="the topic query to search for")],
    source: Annotated[
        str,
        typer.Option(help="which scholarly API to search: arxiv or s2"),
    ] = "arxiv",
    max_results: Annotated[
        int,
        typer.Option("--max-results", help="cap on candidates to request (first page)"),
    ] = 25,
    s2_api_key: Annotated[
        Optional[str],
        typer.Option(envvar="S2_API_KEY", help="optional Semantic Scholar API key"),
    ] = None,
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of discover runs and quarantined queries"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Search the source; print each candidate as one JSONL line, or a note."""
    records = discover(
        query,
        source,
        manifest_path=manifest,
        registry=_build_registry(max_results, s2_api_key),
    )
    if records is None:
        # Quarantine is an expected outcome, not a crash: note it and exit clean.
        typer.echo(f"quarantined (see {manifest}): {source} + {query!r}", err=True)
        return
    for record in records:
        typer.echo(json.dumps(record, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run discover`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
