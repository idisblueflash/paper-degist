"""US9 — verify whether a failed fetch has an open-access copy.

When ``fetch-one`` quarantines a URL with a bare ``http 403`` (ResearchGate,
Academia.edu and other Cloudflare-gated hosts return 403 to any non-browser
client — see DEVLOG), that status alone does not say whether the paper is
reachable *somewhere* for free. This step recovers the paper's DOI and asks the
open-access indexes (Unpaywall) whether a free PDF exists, then dispatches:

- an open-access PDF URL is found  → print it (pipe it back into ``fetch-one``);
- the index reports closed access  → quarantine ``no OA copy (closed access)``
  (a precise reason, not a bare ``http 403``);
- no DOI can be recovered          → quarantine, routing to the human/browser
  lane (title→DOI resolution is a deferred branch — see DEVLOG);
- the lookup errors                → quarantine with the error, finish cleanly.

Never crash, never call an LLM in the loop (rule 02). Runnable from the command
line (rule 03):

    uv run resolve-oa <url-or-doi> --email you@example.com
"""

import re
import sys
from pathlib import Path
from typing import Annotated, Callable, Optional
from urllib.parse import unquote, urlsplit

import typer

from paper_degist import _manifest, _openalex
from paper_degist._cli import invoke

# An OA lookup maps a DOI to its open-access PDF URL, or ``None`` for closed
# access; it may raise to signal an API/network error (caller quarantines it).
OALookup = Callable[[str], Optional[str]]

# A title→DOI lookup (US10) maps a title to a confidently-matched DOI, or
# ``None`` when no confident match exists; it may raise to signal an API error.
TitleLookup = Callable[[str], Optional[str]]

# Crossref's DOI pattern: ``10.<registrant>/<suffix>`` (suffix is liberal).
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)


def doi_from(text: str) -> str | None:
    """Recover the first DOI embedded in ``text`` (a URL or raw string), or None.

    Handles a ``doi.org`` link, a publisher URL that carries the DOI in its
    path, or a bare DOI string. Returns ``None`` when no DOI is present (e.g. a
    ResearchGate slug URL) so the caller can quarantine that case.
    """
    match = _DOI_RE.search(text or "")
    return _trim_doi(match.group(0)) if match else None


def _trim_doi(doi: str) -> str:
    """Strip prose punctuation the DOI regex over-captured from surrounding text.

    A DOI ending a sentence (``…oa.``) or wrapped in parens (``(…oa)``) picks up
    a trailing ``.``/``;``/``)`` that is not part of the DOI. Drop trailing
    sentence punctuation and a single *unbalanced* closing bracket, so a DOI that
    legitimately contains balanced parens (``10.1002/(SICI)…``) survives.
    """
    doi = doi.rstrip(".,;:")
    for opener, closer in (("(", ")"), ("[", "]")):
        if doi.endswith(closer) and doi.count(opener) < doi.count(closer):
            doi = doi[:-1]
    return doi


def title_from(url: str) -> str | None:
    """Recover a paper title from a slug-only URL (US10), or ``None``.

    A ResearchGate/Academia publication link carries the title in its last path
    segment as an underscore slug prefixed by a numeric id
    (``/publication/249870239_An_investigation_…``). Strip the leading id and
    turn ``_``/``+`` separators into spaces. Returns ``None`` when the slug has
    no alphabetic content (a bare domain, a numeric-only path) so the caller
    quarantines that case rather than querying Crossref with junk.
    """
    basename = unquote(urlsplit(url or "").path.rstrip("/").rsplit("/", 1)[-1])
    slug = re.sub(r"^\d+[_-]", "", basename)  # drop a leading numeric publication id
    title = re.sub(r"[_+]+", " ", slug).strip()
    return title if re.search(r"[A-Za-z]", title) else None


def resolve_oa(
    url: str,
    *,
    manifest_path: Path = Path("manifest.jsonl"),
    oa_lookup: OALookup,
    title_lookup: Optional[TitleLookup] = None,
    oa_fallback: Optional[OALookup] = None,
) -> Optional[str]:
    """Resolve an open-access PDF URL for ``url``, or quarantine and return None.

    Classify-then-dispatch (rule 02): recover a DOI, ask ``oa_lookup`` (Unpaywall)
    for the open-access verdict, and dispatch — an OA URL is returned; closed
    access, a missing DOI, and a lookup error each quarantine to ``manifest_path``
    with a precise reason and return ``None`` so the batch finishes.

    When ``oa_lookup`` yields no PDF and an ``oa_fallback`` (OpenAlex, US30) is
    supplied, the verdict is the **union of two indexes**: the fallback is asked
    only then (a paper Unpaywall already resolves never triggers it), and open if
    *either* index has an OA PDF. Closed only when **both** agree — quarantined
    with a reason recording both were checked; a fallback transport error
    quarantines naming OpenAlex as the failed source (distinct from Unpaywall's).

    When no DOI is embedded and a ``title_lookup`` is supplied (US10), recover a
    title from the URL slug and resolve it to a DOI via Crossref before the OA
    dispatch; a recovered DOI rejoins the same OA path. Without a ``title_lookup``
    the missing-DOI case quarantines to the human/browser lane (US9 AC5).
    """
    manifest_path = Path(manifest_path)
    doi = doi_from(url)
    if doi is None:
        doi = _recover_doi_via_title(url, manifest_path, title_lookup)
        if doi is None:
            return None  # already quarantined with a precise reason

    try:
        pdf_url = oa_lookup(doi)
    except Exception as exc:  # API/network error — quarantine, do not crash
        _quarantine(manifest_path, url=url, doi=doi, reason=f"OA lookup error: {exc}")
        return None
    if pdf_url is not None:
        return pdf_url  # Unpaywall resolved it — the fallback is never called.

    return _resolve_via_openalex(url, doi, manifest_path, oa_fallback)


def _resolve_via_openalex(
    url: str, doi: str, manifest_path: Path, oa_fallback: Optional[OALookup]
) -> Optional[str]:
    """Cross-check the closed Unpaywall verdict against OpenAlex (US30).

    The union's second index: with no ``oa_fallback`` wired, keep US9's single-
    source verdict (``closed access``). With one, ask OpenAlex by DOI — a PDF is
    returned (open after all); both indexes agreeing on no PDF quarantines with a
    both-checked reason; an OpenAlex transport error quarantines naming OpenAlex.
    Never crashes, never calls an LLM.
    """
    if oa_fallback is None:
        _quarantine(manifest_path, url=url, doi=doi, reason="no OA copy (closed access)")
        return None

    try:
        pdf_url = oa_fallback(doi)
    except Exception as exc:  # OpenAlex API/network error — quarantine, do not crash
        _quarantine(
            manifest_path, url=url, doi=doi, reason=f"OpenAlex OA lookup error: {exc}"
        )
        return None
    if pdf_url is None:
        _quarantine(
            manifest_path,
            url=url,
            doi=doi,
            reason="no OA copy (closed access) — checked Unpaywall and OpenAlex",
        )
        return None
    return pdf_url


def _recover_doi_via_title(
    url: str, manifest_path: Path, title_lookup: Optional[TitleLookup]
) -> Optional[str]:
    """Recover a DOI from the URL's title slug via ``title_lookup`` (US10).

    Classify-then-dispatch the missing-DOI case: no ``title_lookup`` routes to
    the human/browser lane (US9 AC5); with one, an unextractable title, a
    lookup error, and no confident Crossref match each quarantine with a precise
    reason and return ``None``. Returns the recovered DOI so ``resolve_oa`` can
    rejoin the OA dispatch.
    """
    if title_lookup is None:
        # Title→DOI resolution not wired in — route to the human/browser lane.
        _quarantine(
            manifest_path,
            url=url,
            doi=None,
            reason="no DOI in input; title→DOI lookup not built (route to human/browser)",
        )
        return None

    title = title_from(url)
    if title is None:
        _quarantine(
            manifest_path,
            url=url,
            doi=None,
            reason="no DOI and no title to resolve (route to human/browser)",
        )
        return None

    try:
        doi = title_lookup(title)
    except Exception as exc:  # Crossref API/network error — quarantine, don't crash
        _quarantine(manifest_path, url=url, doi=None, reason=f"title→DOI lookup error: {exc}")
        return None
    if doi is None:
        _quarantine(
            manifest_path,
            url=url,
            doi=None,
            reason="title→DOI: no confident Crossref match (route to human/browser)",
        )
        return None
    return doi


def _quarantine(manifest_path: Path, *, url: str, doi: Optional[str], reason: str) -> None:
    """Append one unresolved-case record to the manifest, so the batch finishes.

    Classify on whether a DOI was recovered (US11): a present DOI also emits a
    clickable ``https://doi.org/<doi>`` link, so the manifest hand-off to the
    human/browser lane is directly actionable; a ``None`` DOI adds nothing (there
    is no DOI to link). Pure string transform — no extra network call.
    """
    fields: dict[str, object] = {"url": url, "doi": doi}
    if doi is not None:
        fields["doi_url"] = f"https://doi.org/{doi}"
    fields["reason"] = reason
    _manifest.append(manifest_path, stage="resolve-oa", **fields)


def _pdf_url_from_unpaywall(data: dict) -> Optional[str]:
    """Return the first open-access *PDF* URL in an Unpaywall response, or None.

    Only ``url_for_pdf`` counts: a bare ``url`` is a landing page, not a file
    ``fetch-one`` can download, so we never return it (else a non-PDF would be
    printed as if it were the paper). Scans ``best_oa_location`` first, then
    every ``oa_locations`` entry. Returns None when the paper is closed *or*
    open with no direct PDF link.
    """
    if not data.get("is_oa"):
        return None
    locations = [data.get("best_oa_location") or {}, *(data.get("oa_locations") or [])]
    for loc in locations:
        pdf = (loc or {}).get("url_for_pdf")
        if pdf:
            return pdf
    return None


# Crossref's bibliographic query always returns a best-effort top match, even
# for a wrong or truncated title. Trust its DOI only when the returned title
# and the query share enough content tokens. The threshold is calibrated on
# three real Crossref responses (see DEVLOG): a correct full-title match scored
# 1.0 symmetric Jaccard, while two best-effort wrong matches scored 0.50 and
# 0.33 — so 0.6 accepts the real match and rejects both wrong ones.
_MIN_TITLE_OVERLAP = 0.6

# Dropped before overlap so common function words don't inflate a weak match.
_TITLE_STOPWORDS = frozenset("a an and for in of on the to".split())


def _content_tokens(text: str) -> set[str]:
    """Lower-cased alphanumeric word tokens of ``text``, minus stopwords."""
    return {t for t in re.findall(r"[a-z0-9]+", text.lower())} - _TITLE_STOPWORDS


def _title_overlap(a: str, b: str) -> float:
    """Symmetric content-token overlap (Jaccard) of two titles, in ``[0, 1]``.

    Symmetric on purpose: a short query trivially covers a long title's tokens
    one-directionally (and vice versa), which is exactly how a truncated slug
    scores a false 1.0. Jaccard penalizes tokens present on *either* side, so a
    partial slug or an unrelated best-effort match falls below the threshold.
    """
    ta, tb = _content_tokens(a), _content_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _doi_from_crossref(data: dict, query: str) -> Optional[str]:
    """Return the top Crossref item's DOI, but only on a confident title match.

    Guards against Crossref's best-effort ranking (US10 AC2): the top item's
    title must clear ``_MIN_TITLE_OVERLAP`` against ``query``, else return
    ``None`` so a wrong/truncated match is quarantined rather than fed into the
    OA lookup as if it were the paper. Returns ``None`` for an empty result set.
    """
    items = (data.get("message") or {}).get("items") or []
    if not items:
        return None
    top = items[0] or {}
    title = " ".join(top.get("title") or [])
    if _title_overlap(query, title) < _MIN_TITLE_OVERLAP:
        return None
    return top.get("DOI") or None


def _crossref_title_lookup(email: str) -> TitleLookup:
    """Build the real title→DOI lookup: ask Crossref for a title's DOI (US10).

    Queries Crossref's bibliographic endpoint for the single best match and
    gates it through ``_doi_from_crossref`` — returning the DOI only on a
    confident title match, else ``None``. Raises on a network/API error so
    ``resolve_oa`` quarantines it (US10 AC4). The contact email joins the
    ``User-Agent`` mailto so Crossref routes the request through its polite pool.
    """

    def lookup(title: str) -> Optional[str]:
        import httpx

        resp = httpx.get(
            "https://api.crossref.org/works",
            params={"query.bibliographic": title, "rows": 1},
            headers={"User-Agent": f"paper-degist/0.1 (mailto:{email})"},
            timeout=30.0,
        )
        resp.raise_for_status()
        return _doi_from_crossref(resp.json(), title)

    return lookup


def _unpaywall_lookup(email: str) -> OALookup:
    """Build the real OA lookup: ask Unpaywall for a DOI's open-access PDF URL.

    Returns the open-access PDF URL, or ``None`` when Unpaywall reports the paper
    closed (or open with no direct PDF link). Raises on a network/API error so
    ``resolve_oa`` quarantines it (AC6) rather than crashing. Unpaywall requires
    a contact email per request.
    """

    def lookup(doi: str) -> Optional[str]:
        import httpx

        resp = httpx.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": email},
            timeout=30.0,
        )
        resp.raise_for_status()
        return _pdf_url_from_unpaywall(resp.json())

    return lookup


_OPENALEX_NO_EMAIL_WARNING = (
    "warning: no OpenAlex contact email (--email / OPENALEX_EMAIL); the OA "
    "cross-check uses the slower common pool — set one for the polite pool."
)


def _openalex_oa_lookup(email: Optional[str]) -> OALookup:
    """Build the OpenAlex OA fallback lookup: find a DOI's OA PDF in OpenAlex (US30).

    Addresses the single work at ``{WORKS_ENDPOINT}/doi:<doi>`` and reads its
    ``best_oa_location``/``oa_locations`` for a fetchable ``pdf_url`` via the
    shared ``_openalex`` extractor (rule 02 — the quirk encoded once). Returns the
    PDF URL, or ``None`` when OpenAlex knows no OA copy either; raises on a
    network/API error so ``resolve_oa`` quarantines it naming OpenAlex (AC4).

    OpenAlex is **keyless**; a contact ``mailto`` earns the faster polite pool.
    With no email the cross-check still runs on the common pool (AC5) — ``mailto``
    is omitted and a politeness warning is emitted; a missing email downgrades
    politeness, it does not skip the cross-check.
    """
    if not email:
        print(_OPENALEX_NO_EMAIL_WARNING, file=sys.stderr)

    def lookup(doi: str) -> Optional[str]:
        import httpx

        resp = httpx.get(
            f"{_openalex.WORKS_ENDPOINT}/doi:{doi}",
            params={"mailto": email} if email else {},
            headers={"User-Agent": "paper-degist/0.1 (https://github.com/idisblueflash/paper-degist)"},
            timeout=30.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return _openalex.pdf_url_from_work(resp.json())

    return lookup


app = typer.Typer(
    add_completion=False,
    help="Verify whether a failed fetch has an open-access copy (US9/US10/US30).",
)


@app.command()
def run(
    url: Annotated[str, typer.Argument(help="the failed URL or a DOI to resolve")],
    email: Annotated[
        str,
        typer.Option(envvar="UNPAYWALL_EMAIL", help="contact email Unpaywall requires"),
    ],
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of quarantined, unresolved inputs"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Resolve the URL; print the OA PDF URL, or a quarantine note on stderr."""
    pdf_url = resolve_oa(
        url,
        manifest_path=manifest,
        oa_lookup=_unpaywall_lookup(email),
        title_lookup=_crossref_title_lookup(email),
        oa_fallback=_openalex_oa_lookup(email),
    )
    if pdf_url is None:
        # Quarantine is an expected outcome, not a crash: the batch still
        # finishes. Note it on stderr and exit cleanly.
        typer.echo(f"quarantined (see {manifest}): {url}", err=True)
        return
    typer.echo(pdf_url)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run resolve-oa`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
