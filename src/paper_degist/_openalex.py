"""Shared OpenAlex client bits — the quirks encoded once, reused by every step.

OpenAlex is queried by two steps: ``discover`` (US29, search Works by topic) and
``resolve-oa`` (US30, look a Work up by DOI as an open-access fallback). Both must
read the same open-access shape out of a Work object, so that extraction lives
here **once** (rule 02) rather than being re-derived per step.

The client is **keyless**; politeness is the *polite pool* convention — send a
contact ``mailto`` for the faster shared pool, omit it (and warn, a CLI concern)
when absent.
"""

from typing import Optional

# The Works collection. ``discover`` filters/sorts it as a search; ``resolve-oa``
# addresses a single work by DOI at ``{WORKS_ENDPOINT}/doi:<doi>``.
WORKS_ENDPOINT = "https://api.openalex.org/works"

# The contact header every OpenAlex request carries (identity, not politeness —
# the polite pool is the ``mailto`` param below).
USER_AGENT = "paper-degist/0.1 (https://github.com/idisblueflash/paper-degist)"


def _get(url: str, params: dict, email: Optional[str]) -> dict:
    """GET ``url`` from OpenAlex and return its JSON, encoding the client once.

    The shared client detail every OpenAlex call needs (rule 02): the identity
    ``User-Agent``, a 30 s timeout, redirect-following, and the *polite pool*
    ``mailto`` — appended when an ``email`` is supplied, omitted (common pool)
    when not. Raises on a network/API error so the caller quarantines it.
    """
    import httpx

    params = dict(params)
    if email:
        params["mailto"] = email
    resp = httpx.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return resp.json()


def search_works(query_params: dict, email: Optional[str]) -> dict:
    """Search the Works collection (``discover``) — filter/sort params in, JSON out."""
    return _get(WORKS_ENDPOINT, query_params, email)


def fetch_work_by_doi(doi: str, email: Optional[str]) -> dict:
    """Fetch the single Work addressed by ``doi`` (``resolve-oa`` OA fallback)."""
    return _get(f"{WORKS_ENDPOINT}/doi:{doi}", {}, email)


def pdf_url_from_work(work: dict) -> Optional[str]:
    """The directly fetchable OA PDF of a Work: ``best_oa_location`` then locations.

    OpenAlex's ``best_oa_location.pdf_url`` is the preferred open copy; when it
    has none (an OA landing page with no direct PDF, or a closed work), fall back
    to the first ``oa_locations[]`` entry that carries a ``pdf_url``. A work with
    no OA PDF anywhere yields ``None`` (closed, as far as OpenAlex knows).
    """
    best = work.get("best_oa_location") or {}
    if best.get("pdf_url"):
        return best["pdf_url"]
    for location in work.get("oa_locations") or []:
        if isinstance(location, dict) and location.get("pdf_url"):
            return location["pdf_url"]
    return None
