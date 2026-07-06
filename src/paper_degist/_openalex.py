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
