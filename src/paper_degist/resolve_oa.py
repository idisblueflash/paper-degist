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
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke

# An OA lookup maps a DOI to its open-access PDF URL, or ``None`` for closed
# access; it may raise to signal an API/network error (caller quarantines it).
OALookup = Callable[[str], Optional[str]]

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


def resolve_oa(
    url: str,
    *,
    manifest_path: Path = Path("manifest.jsonl"),
    oa_lookup: OALookup,
) -> Optional[str]:
    """Resolve an open-access PDF URL for ``url``, or quarantine and return None.

    Classify-then-dispatch (rule 02): recover a DOI, ask ``oa_lookup`` for the
    open-access verdict, and dispatch — an OA URL is returned; closed access, a
    missing DOI, and a lookup error each quarantine to ``manifest_path`` with a
    precise reason and return ``None`` so the batch finishes.
    """
    manifest_path = Path(manifest_path)
    doi = doi_from(url)
    if doi is None:
        # No DOI to look up: route to the human / browser dev-mode lane.
        # Title→DOI resolution (Crossref) is a deferred branch — see DEVLOG.
        _quarantine(
            manifest_path,
            url=url,
            doi=None,
            reason="no DOI in input; title→DOI lookup not built (route to human/browser)",
        )
        return None

    try:
        pdf_url = oa_lookup(doi)
    except Exception as exc:  # API/network error — quarantine, do not crash
        _quarantine(manifest_path, url=url, doi=doi, reason=f"OA lookup error: {exc}")
        return None
    if pdf_url is None:
        _quarantine(manifest_path, url=url, doi=doi, reason="no OA copy (closed access)")
        return None
    return pdf_url


def _quarantine(manifest_path: Path, *, url: str, doi: Optional[str], reason: str) -> None:
    """Append one unresolved-case record to the manifest, so the batch finishes."""
    _manifest.append(
        manifest_path,
        stage="resolve-oa",
        url=url,
        doi=doi,
        reason=reason,
    )


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


app = typer.Typer(
    add_completion=False,
    help="Verify whether a failed fetch has an open-access copy (US9).",
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
    pdf_url = resolve_oa(url, manifest_path=manifest, oa_lookup=_unpaywall_lookup(email))
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
