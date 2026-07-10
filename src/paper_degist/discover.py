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
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer

from paper_degist import _manifest, _openalex
from paper_degist._cli import invoke

# Per-source politeness intervals the batch driver (US31/US38) paces each source
# by. discover issues one query per run, so a single call never waits; these are
# encoded here for discover-batch, which walks several queries and paces every
# later call to a source by its interval. arXiv's ~3 s is its published
# rate-limit etiquette; OpenAlex and Semantic Scholar are keyless free tiers
# paced more lightly so a wide fan-out does not trip their limits by cumulative
# volume (US38).
ARXIV_MIN_INTERVAL = 3.0
OPENALEX_MIN_INTERVAL = 1.0
S2_MIN_INTERVAL = 1.0

ARXIV_ENDPOINT = "https://export.arxiv.org/api/query"
S2_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
# The Semantic Scholar fields we ask for — the common-schema inputs plus tldr.
S2_FIELDS = "title,abstract,authors,externalIds,url,publicationDate,tldr"

OPENALEX_ENDPOINT = _openalex.WORKS_ENDPOINT

# The Atom namespace every arXiv feed element lives under.
_ATOM = "{http://www.w3.org/2005/Atom}"


class MissingKeyError(Exception):
    """A source needs an API key that was not supplied (US27 AC4).

    Raised by a key-gated adapter (SerpAPI's ``scholar`` / ``scholar-author``)
    **before it touches the network**, so ``discover`` can quarantine it with a
    distinct ``missing-key`` reason — classified offline like the source name,
    never confused with a live ``api-error``.
    """


class RateLimited(Exception):
    """A source answered with an HTTP 429 rate-limit (US38).

    A *typed* signal, raised by an adapter that translates a 429 (see
    ``_raise_for_status``), so ``discover`` can tell a **transient** rate-limit
    apart from a hard ``api-error`` and retry it with backoff rather than
    quarantine on the first hit. ``retry_after`` carries the server's
    ``Retry-After`` interval in seconds when it sent one, else ``None`` (fall
    back to the exponential schedule).
    """

    def __init__(self, message: str = "HTTP 429 Too Many Requests", *, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


# US38 backoff policy. A 429 is retried up to MAX_RETRIES times; each wait is the
# server's Retry-After when present, else an exponential schedule
# (RETRY_BASE_DELAY * 2**attempt), both capped at RETRY_MAX_DELAY so a hostile or
# malformed Retry-After can never stall the run. Waits go through an injected
# pause so tests never really sleep (AC6).
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0
RETRY_MAX_DELAY = 60.0


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse a ``Retry-After`` header into seconds, or ``None`` if absent/odd.

    Honors the numeric-seconds form (the common case); the HTTP-date form is
    ignored (falls back to the exponential schedule) rather than mis-parsed.
    """
    if value is None:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def _backoff_delay(attempt: int, retry_after: Optional[float]) -> float:
    """The wait before the next retry: Retry-After if given, else exponential.

    Both are capped at ``RETRY_MAX_DELAY`` (``attempt`` is 0-based).
    """
    if retry_after is not None:
        return min(retry_after, RETRY_MAX_DELAY)
    return min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)


def _rate_limited_for(resp) -> Optional[RateLimited]:
    """A ``RateLimited`` (carrying any ``Retry-After``) if ``resp`` is a 429, else None.

    The single 429 classifier both adapter shapes share: the direct-httpx
    adapters check the response *before* raising (``_raise_for_status``), and the
    OpenAlex adapter — whose raise is buried in ``_openalex._get`` — checks the
    response hung off the caught ``HTTPStatusError``.
    """
    if resp is not None and resp.status_code == 429:
        return RateLimited(retry_after=_parse_retry_after(resp.headers.get("Retry-After")))
    return None


def _raise_for_status(resp) -> None:
    """Raise on an error response, translating a 429 into ``RateLimited``.

    Where the direct-httpx adapters (arXiv, S2) route their status check, so a
    real rate-limit becomes the typed signal ``discover`` retries on (US38),
    while every other 4xx/5xx keeps raising ``httpx.HTTPStatusError`` (→
    ``api-error``, unchanged).
    """
    rate_limited = _rate_limited_for(resp)
    if rate_limited is not None:
        raise rate_limited
    resp.raise_for_status()


@dataclass(frozen=True)
class Candidate:
    """One discovered paper in the common schema, source-agnostic.

    ``abstract`` may be ``None`` (some records carry no abstract); the emitted
    record still carries it with an ``abstract_present`` flag so US26 can drop it
    cheaply rather than discovery dropping it (AC3 — discovery casts wide).
    ``doi``, ``tldr``, ``pdf_url`` and ``cited_by`` are emitted only when the
    record actually carries them — ``pdf_url`` is OpenAlex's up-front open-access
    copy (directly fetchable by ``fetch-one``, US29 AC3) and ``cited_by`` its
    citation count.
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
    pdf_url: Optional[str] = None
    cited_by: Optional[int] = None
    venue: Optional[str] = None

    def to_record(self) -> dict:
        """The JSONL record: always-present fields, plus the optional ones."""
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
        if self.pdf_url:
            record["pdf_url"] = self.pdf_url
        if self.cited_by is not None:
            record["cited_by"] = self.cited_by
        if self.venue:
            record["venue"] = self.venue
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


def reconstruct_abstract(inverted_index: Optional[dict]) -> Optional[str]:
    """Rebuild plain-text abstract from OpenAlex's inverted index (rule 02).

    OpenAlex ships the abstract as ``abstract_inverted_index`` — a
    ``{token: [positions]}`` map — never plain text. Placing each token at each
    of its positions and reading them in position order reconstructs the
    original abstract. A null / empty index means the work carries no abstract
    (US29 AC5) → ``None``, so the record is flagged ``abstract_present: false``
    rather than dropped.
    """
    if not inverted_index:
        return None
    positioned: dict[int, str] = {}
    for token, positions in inverted_index.items():
        for position in positions:
            positioned[position] = token
    return " ".join(positioned[i] for i in sorted(positioned)) or None


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
        if not entry_id:
            # An arXiv paper without its <id> (its primary key) is a malformed
            # feed entry — no url, no source_id — so it is unfetchable junk, not
            # a candidate. Skip it rather than emit an empty-identity record.
            continue
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
        # Tolerate a partial response: a null / non-object author item must not
        # crash the parser (rule 02) — keep only the well-formed named authors.
        authors = [
            a["name"]
            for a in (item.get("authors") or [])
            if isinstance(a, dict) and a.get("name")
        ]
        doi = (item.get("externalIds") or {}).get("DOI")
        tldr_obj = item.get("tldr") or {}
        paper_id = item.get("paperId") or ""
        # S2's paper URL is deterministic from the paperId, so repair a missing
        # url rather than emit an empty, unfetchable one.
        url = item.get("url") or (
            f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else ""
        )
        if not (url or paper_id or doi):
            # No url, no paperId, no DOI — the record cannot be fetched or
            # deduped. It is structurally unidentifiable junk, not a candidate
            # (dropping it here is a parser-quality concern, not the relevance
            # filtering that is US26's job). Skip it.
            continue
        candidates.append(
            Candidate(
                title=item.get("title") or "",
                authors=authors,
                abstract=item.get("abstract"),
                url=url,
                published=item.get("publicationDate"),
                source="s2",
                source_id=paper_id,
                doi=doi,
                tldr=tldr_obj.get("text"),
            )
        )
    return candidates


def _bare_openalex_id(entity_url: Optional[str]) -> str:
    """``https://openalex.org/W2606780347`` → ``W2606780347`` (the bare key)."""
    return (entity_url or "").rsplit("/", 1)[-1]


def _bare_doi(doi_url: Optional[str]) -> Optional[str]:
    """``https://doi.org/10.1038/nature24644`` → the bare DOI (common schema).

    OpenAlex reports the DOI as a resolver URL; the common schema (like S2's
    ``externalIds.DOI``) carries the bare DOI, so strip the resolver prefix.
    """
    if not doi_url:
        return None
    lowered = doi_url.lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/"):
        if lowered.startswith(prefix):
            return doi_url[len(prefix):]
    return doi_url


def parse_openalex_json(data: dict) -> list[Candidate]:
    """Map an OpenAlex Works response into Candidates (rule 02 — quirks once).

    OpenAlex's fixed quirks, encoded here so no other stage repeats them: the
    abstract arrives as ``abstract_inverted_index`` (reconstructed to plain text,
    ``None`` when absent — AC2/AC5); the DOI and the work id arrive as resolver
    URLs (reduced to the bare DOI / bare ``W…`` id); and the open-access PDF lives
    under ``best_oa_location``/``oa_locations`` (extracted as ``pdf_url`` — AC3).
    ``cited_by_count`` carries the citation count. A result with no identity at
    all (no id, url, or DOI) is unfetchable junk and skipped, mirroring the
    arXiv/S2 parsers.
    """
    candidates: list[Candidate] = []
    for work in data.get("results") or []:
        source_id = _bare_openalex_id(work.get("id"))
        doi = _bare_doi(work.get("doi"))
        # url is the canonical human landing page: the DOI resolver when the work
        # has a DOI, else the OpenAlex entity page — always something fetchable.
        url = work.get("doi") or work.get("id") or ""
        if not (url or doi):
            continue
        authors = [
            name
            for authorship in (work.get("authorships") or [])
            if isinstance(authorship, dict)
            and (name := (authorship.get("author") or {}).get("display_name"))
        ]
        candidates.append(
            Candidate(
                title=work.get("title") or "",
                authors=authors,
                abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
                url=url,
                published=work.get("publication_date"),
                source="openalex",
                source_id=source_id,
                doi=doi,
                pdf_url=_openalex.pdf_url_from_work(work),
                cited_by=work.get("cited_by_count"),
                venue=_openalex.venue_from_work(work),
            )
        )
    return candidates


def _scholar_pdf_url(item: dict) -> Optional[str]:
    """The directly fetchable open PDF from a Scholar organic hit (US27 AC2).

    Scholar lists open copies under ``resources[]``, each with a ``file_format``
    (``PDF``/``HTML``) and a ``link``. Return the first ``PDF`` resource's link —
    directly fetchable by ``fetch-one`` — or ``None`` when the hit has no open PDF
    (still emitted, just without a ``pdf_url``).
    """
    for resource in item.get("resources") or []:
        if isinstance(resource, dict) and resource.get("file_format") == "PDF" and resource.get("link"):
            return resource["link"]
    return None


def parse_serpapi_scholar(data: dict) -> list[Candidate]:
    """Map a SerpAPI ``google_scholar`` (organic) response into Candidates (rule 02).

    Scholar's fixed quirks, encoded here once: each ``organic_results`` item
    carries a ``snippet`` (an abstract **fragment** with ``…`` ellipses, kept as
    the ``abstract`` — US27 AC1), its stable ``result_id`` (the ``source_id``), a
    ``link`` (the landing ``url``), an ``inline_links.cited_by.total`` count, and —
    when Scholar has an open copy — a ``resources[]`` PDF whose ``link`` becomes
    ``pdf_url`` (AC2). Author names come from ``publication_info.authors[]`` when
    present (Scholar often gives only a summary string, so an empty list is fine).
    A response with no ``organic_results`` (a zero-result query) yields ``[]``.
    """
    candidates: list[Candidate] = []
    for item in data.get("organic_results") or []:
        if not isinstance(item, dict):
            # A null / non-object hit is a malformed record, not a candidate —
            # skip it rather than crash (rule 02), like the arXiv/S2 parsers.
            continue
        authors = [
            a["name"]
            for a in ((item.get("publication_info") or {}).get("authors") or [])
            if isinstance(a, dict) and a.get("name")
        ]
        cited_by = ((item.get("inline_links") or {}).get("cited_by") or {}).get("total")
        candidates.append(
            Candidate(
                title=item.get("title") or "",
                authors=authors,
                abstract=item.get("snippet"),
                url=item.get("link") or "",
                published=None,
                source="scholar",
                source_id=item.get("result_id") or "",
                pdf_url=_scholar_pdf_url(item),
                cited_by=cited_by,
            )
        )
    return candidates


def parse_serpapi_scholar_author(data: dict) -> list[Candidate]:
    """Map a SerpAPI ``google_scholar_author`` response into Candidates (rule 02).

    The author engine is **bibliographic only** (US27 AC3): each ``articles`` item
    carries a ``title``, a citation ``link`` (the ``url``), a ``citation_id`` (the
    ``source_id``), a comma-separated ``authors`` string (split into names), a
    ``year`` (the ``published``), and a ``cited_by.value`` count — but **no
    abstract and no PDF** (confirmed live). So ``abstract`` stays ``None`` (flagged
    ``abstract_present: false``) and ``pdf_url`` is never set. An author with no
    ``articles`` yields ``[]``.
    """
    candidates: list[Candidate] = []
    for item in data.get("articles") or []:
        if not isinstance(item, dict):
            # A null / non-object article is malformed — skip it (rule 02).
            continue
        authors = [name.strip() for name in (item.get("authors") or "").split(",") if name.strip()]
        cited_by = (item.get("cited_by") or {}).get("value")
        candidates.append(
            Candidate(
                title=item.get("title") or "",
                authors=authors,
                abstract=None,
                url=item.get("link") or "",
                published=item.get("year") or None,
                source="scholar-author",
                source_id=item.get("citation_id") or "",
                cited_by=cited_by,
            )
        )
    return candidates


# SerpAPI signals "no hits" not with an empty body but with a 200 whose ``error``
# field carries this phrase (US27 AC5) — routed to an empty result, distinct from a
# real API error (a bad key / other ``error``, which raises → api-error).
SERPAPI_NO_RESULTS = "hasn't returned any results"

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"


def route_serpapi_response(data: dict, parser: Callable[[dict], list[Candidate]]) -> list[Candidate]:
    """Route a SerpAPI 200 body to the parser, an empty result, or an error (AC5).

    SerpAPI answers a zero-result query with HTTP 200 whose body carries an
    ``error`` field (not an empty result set), and reports a bad key / other
    failure the same way. Classify on that field (rule 02): a *no-results* error →
    ``[]`` (quarantined as empty-result upstream); any other ``error`` → raise (so
    ``discover`` quarantines it as a **distinct** api-error); no ``error`` → parse.
    """
    error = data.get("error")
    if error:
        # Coerce to str first: SerpAPI's error is normally a string, but a
        # structured/non-string body must route as an api-error (raise), never
        # crash on ``.lower()`` (rule 02 — tolerate a malformed response).
        if SERPAPI_NO_RESULTS in str(error).lower():
            return []
        raise RuntimeError(f"SerpAPI error: {error}")
    return parser(data)


def _serpapi_search(
    engine: str,
    query_param: str,
    parser: Callable[[dict], list[Candidate]],
    *,
    max_results: int,
    api_key: Optional[str],
) -> Search:
    """Build a SerpAPI adapter (``scholar`` organic / ``scholar-author``), US27.

    Both engines are one endpoint (``engine=…``) and **require an API key**
    (US27 AC4): with none, raise ``MissingKeyError`` **before any network call**,
    so ``discover`` quarantines it offline (missing-key), classified like the
    source name. With a key, issue the search and route the 200 body through
    ``route_serpapi_response`` (AC5). ``query_param`` is the engine's query key
    (``q`` for organic, ``author_id`` for the author engine).
    """

    def search(query: str) -> list[Candidate]:
        if not api_key:
            raise MissingKeyError(
                "no SerpAPI key (--serpapi-key / SERPAPI_API_KEY) for source "
                f"{engine!r}"
            )
        import httpx

        resp = httpx.get(
            SERPAPI_ENDPOINT,
            params={"engine": engine, query_param: query, "num": max_results, "api_key": api_key},
            headers={"User-Agent": "paper-degist/0.1 (https://github.com/idisblueflash/paper-degist)"},
            timeout=30.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return route_serpapi_response(resp.json(), parser)

    return search


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
        _raise_for_status(resp)
        return parse_arxiv_atom(resp.text)

    return search


def _openalex_search(max_results: int, email: Optional[str]) -> Search:
    """Build the real OpenAlex adapter: query the Works API, parse into Candidates.

    OpenAlex is **keyless** (like arXiv). Politeness is the *polite pool*
    convention — send a contact ``mailto=`` for the faster shared pool. Absent,
    the query still runs on the common pool (US29 AC4 — the missing-email warning
    is the CLI's job); the ``mailto`` param is simply omitted. The query filters
    ``title_and_abstract.search`` and sorts ``cited_by_count:desc`` so the wide
    net surfaces the most-cited first.
    """

    def search(query: str) -> list[Candidate]:
        import httpx

        try:
            data = _openalex.search_works(
                {
                    "filter": f"title_and_abstract.search:{query}",
                    "sort": "cited_by_count:desc",
                    "per-page": max_results,
                },
                email,
            )
        except httpx.HTTPStatusError as exc:  # translate a 429 into the retry signal (US38)
            rate_limited = _rate_limited_for(exc.response)
            if rate_limited is not None:
                raise rate_limited from exc
            raise
        return parse_openalex_json(data)

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
        _raise_for_status(resp)
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
    pause: Callable[[float], None] = time.sleep,
    max_retries: int = MAX_RETRIES,
) -> Optional[list[dict]]:
    """Search ``source`` for ``query``; return the candidate records, or None.

    Classify-then-dispatch (rule 02). Layer 1 — on the source: not a known
    adapter → quarantine (unknown source) **without touching the network** and
    return ``None`` (AC5). A key-gated adapter with no key raises
    ``MissingKeyError`` before the network → quarantine (missing-key, a distinct
    reason — US27 AC4). Layer 2 — on the transport result: an API/network
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

    # Layer 2 classifies the *transport outcome* (rule 02). A typed 429
    # (RateLimited) is a transient case: back off and retry up to max_retries
    # before quarantining with a DISTINCT reason (US38) — never confused with a
    # hard api-error, which quarantines immediately with no retry.
    attempt = 0
    while True:
        try:
            candidates = search(query)
            break
        except MissingKeyError as exc:  # key-gated source, no key — offline, distinct
            _quarantine(
                manifest_path,
                source=source,
                query=query,
                reason=f"missing-key: {exc}",
            )
            return None
        except RateLimited as exc:  # transient 429 — back off and retry (US38)
            if attempt >= max_retries:
                _quarantine(
                    manifest_path,
                    source=source,
                    query=query,
                    reason=f"rate-limited-exhausted: 429 after {max_retries} retries",
                )
                return None
            pause(_backoff_delay(attempt, exc.retry_after))
            attempt += 1
            continue
        except Exception as exc:  # hard API/network error — quarantine, do not crash
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

    # Build the emitted records *before* writing the success record, so a
    # success row is never written for a run that then failed to serialize its
    # candidates (rule 02 — the manifest reflects only what actually succeeded).
    records = [c.to_record() for c in candidates]
    _manifest.append(
        manifest_path,
        stage="discover",
        source=source,
        query=query,
        result_count=len(records),
    )
    return records


app = typer.Typer(
    add_completion=False,
    help="Discover candidate papers by topic from a scholarly API (US25).",
)


def _build_registry(
    max_results: int,
    s2_api_key: Optional[str],
    email: Optional[str],
    serpapi_api_key: Optional[str],
) -> dict[str, Search]:
    """The source registry (rule 02: a new source is one entry, not a branch)."""
    return {
        "arxiv": _arxiv_search(max_results),
        "s2": _s2_search(max_results, s2_api_key),
        "openalex": _openalex_search(max_results, email),
        "scholar": _serpapi_search(
            "google_scholar", "q", parse_serpapi_scholar,
            max_results=max_results, api_key=serpapi_api_key,
        ),
        "scholar-author": _serpapi_search(
            "google_scholar_author", "author_id", parse_serpapi_scholar_author,
            max_results=max_results, api_key=serpapi_api_key,
        ),
    }


@app.command()
def run(
    query: Annotated[str, typer.Argument(help="the topic query to search for")],
    source: Annotated[
        str,
        typer.Option(
            help="which scholarly API to search: arxiv, s2, openalex, scholar, or scholar-author"
        ),
    ] = "arxiv",
    max_results: Annotated[
        int,
        typer.Option("--max-results", help="cap on candidates to request (first page)"),
    ] = 25,
    max_retries: Annotated[
        int,
        typer.Option(
            "--max-retries",
            help="how many times to retry a rate-limited (HTTP 429) source with backoff",
        ),
    ] = MAX_RETRIES,
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
        typer.Option(help="manifest of discover runs and quarantined queries"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Search the source; print each candidate as one JSONL line, or a note."""
    if source == "openalex" and not email:
        # AC4: OpenAlex serves keyless traffic, so a missing contact email is
        # *politeness*, not an access requirement — warn and downgrade to the
        # common pool rather than quarantine (contrast US27's hard SerpAPI key).
        typer.echo(_openalex.NO_EMAIL_WARNING, err=True)
    records = discover(
        query,
        source,
        manifest_path=manifest,
        registry=_build_registry(max_results, s2_api_key, email, serpapi_key),
        max_retries=max_retries,
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
