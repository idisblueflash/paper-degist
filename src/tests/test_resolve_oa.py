"""Unit tests for US9 resolve_oa (pytest).

One assertion per test: each fails for exactly one reason. Shared arrange/act
lives in the ``_run``/``_only_record`` helpers so splitting a fact into two
tests never duplicates setup.

resolve_oa is exercised offline by injecting a fake ``oa_lookup`` callable
(returning an OA PDF URL, ``None`` for closed access, or raising to model an
API error), so no test touches the network — the workflow stays runnable
offline (US2 design principle).
"""

import json
from pathlib import Path

from paper_degist.resolve_oa import (
    _doi_from_crossref,
    _pdf_url_from_unpaywall,
    doi_from,
    resolve_oa,
    title_from,
)

_DOI_URL = "https://doi.org/10.1191/1362168805lr151oa"
_SLUG_URL = "https://www.researchgate.net/publication/249870239_An_investigation"


def _run(tmp_path, *, url=_DOI_URL, oa_lookup, title_lookup=None):
    """Arrange a fresh manifest and run resolve_oa; return (result, manifest)."""
    manifest = tmp_path / "manifest.jsonl"
    result = resolve_oa(
        url, manifest_path=manifest, oa_lookup=oa_lookup, title_lookup=title_lookup
    )
    return result, manifest


def _only_record(manifest: Path):
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


def _found(pdf_url):
    return lambda doi: pdf_url


def _closed(doi):
    return None


def _boom(doi):
    raise RuntimeError("unpaywall 422")


# --- doi_from: recover a DOI from a URL or raw string ---


def test_doi_from_doi_org_url():
    assert doi_from("https://doi.org/10.1191/1362168805lr151oa") == "10.1191/1362168805lr151oa"


def test_doi_from_slug_url_without_doi_is_none():
    # A ResearchGate publication slug carries no DOI — the AC5 quarantine case.
    assert doi_from("https://www.researchgate.net/publication/249870239_An_investigation") is None


def test_doi_from_strips_trailing_sentence_punctuation():
    # A DOI pasted at the end of a sentence must not carry the period into the lookup.
    assert doi_from("see 10.1191/1362168805lr151oa.") == "10.1191/1362168805lr151oa"


def test_doi_from_strips_unbalanced_wrapper_paren():
    # A DOI wrapped in prose parens keeps a balanced one but drops the wrapper.
    assert doi_from("(10.1191/1362168805lr151oa)") == "10.1191/1362168805lr151oa"


# --- title_from: recover a title slug from a slug-only URL (US10) ---


def test_title_from_researchgate_slug_strips_id_and_underscores():
    url = "https://www.researchgate.net/publication/249870239_An_investigation_of_the_keyword_method"
    assert title_from(url) == "An investigation of the keyword method"


def test_title_from_bare_domain_without_a_slug_is_none():
    # No last-segment title to query Crossref with — the AC3 quarantine case.
    assert title_from("https://example.com/") is None


# --- _doi_from_crossref: trust the top DOI only on a confident title match (US10) ---


def _crossref(doi, title):
    """Shape one Crossref /works response with a single top item."""
    return {"message": {"items": [{"DOI": doi, "title": [title]}]}}


def test_crossref_confident_title_match_returns_the_doi():
    # The returned title equals the query (all content tokens overlap) — trusted.
    data = _crossref("10.1191/1362168805lr151oa", "An investigation of the keyword method")
    assert _doi_from_crossref(data, "An investigation of the keyword method") == "10.1191/1362168805lr151oa"


def test_crossref_weak_title_match_is_rejected():
    # A truncated 2-word slug returns an unrelated best-effort paper (real case:
    # "An investigation" → "Managing Covert Investigation", 0.33 overlap).
    data = _crossref("10.1093/law/9780198828532.003.0005", "Managing Covert Investigation")
    assert _doi_from_crossref(data, "An investigation") is None


def test_crossref_empty_result_set_is_none():
    assert _doi_from_crossref({"message": {"items": []}}, "whatever title") is None


# --- _pdf_url_from_unpaywall: only a real PDF URL counts, never a landing page ---


def test_unpaywall_closed_paper_is_none():
    assert _pdf_url_from_unpaywall({"is_oa": False}) is None


def test_unpaywall_best_location_pdf_is_returned():
    data = {"is_oa": True, "best_oa_location": {"url_for_pdf": "https://oa.org/p.pdf"}}
    assert _pdf_url_from_unpaywall(data) == "https://oa.org/p.pdf"


def test_unpaywall_landing_page_without_pdf_is_none():
    # is_oa but only a landing-page url (no url_for_pdf) must NOT be returned:
    # fetch-one cannot download an HTML landing page as the paper.
    data = {"is_oa": True, "best_oa_location": {"url": "https://oa.org/landing", "url_for_pdf": None}}
    assert _pdf_url_from_unpaywall(data) is None


def test_unpaywall_falls_back_to_a_later_location_pdf():
    # best_oa_location lacks a PDF, but another oa_locations entry has one.
    data = {
        "is_oa": True,
        "best_oa_location": {"url": "https://oa.org/landing", "url_for_pdf": None},
        "oa_locations": [{"url_for_pdf": "https://repo.org/p.pdf"}],
    }
    assert _pdf_url_from_unpaywall(data) == "https://repo.org/p.pdf"


# --- AC1/AC3: an open-access paper resolves to its PDF URL ---


def test_open_access_returns_the_pdf_url(tmp_path: Path):
    result, _ = _run(tmp_path, oa_lookup=_found("https://oa.example.org/paper.pdf"))
    assert result == "https://oa.example.org/paper.pdf"


def test_open_access_writes_no_manifest_record(tmp_path: Path):
    _, manifest = _run(tmp_path, oa_lookup=_found("https://oa.example.org/paper.pdf"))
    assert not manifest.exists()


# --- AC2/AC4: closed access is quarantined with a precise reason ---


def test_closed_access_returns_none(tmp_path: Path):
    result, _ = _run(tmp_path, oa_lookup=_closed)
    assert result is None


def test_closed_access_manifest_reason_is_precise(tmp_path: Path):
    _, manifest = _run(tmp_path, oa_lookup=_closed)
    assert _only_record(manifest)["reason"] == "no OA copy (closed access)"


def test_closed_access_manifest_records_the_doi(tmp_path: Path):
    _, manifest = _run(tmp_path, oa_lookup=_closed)
    assert _only_record(manifest)["doi"] == "10.1191/1362168805lr151oa"


def test_closed_access_manifest_records_resolve_oa_stage(tmp_path: Path):
    _, manifest = _run(tmp_path, oa_lookup=_closed)
    assert _only_record(manifest)["stage"] == "resolve-oa"


# --- AC5: no recoverable DOI is quarantined without an OA lookup ---


def _must_not_call(doi):
    raise AssertionError("oa_lookup must not run without a DOI")


def test_no_doi_returns_none(tmp_path: Path):
    result, _ = _run(tmp_path, url=_SLUG_URL, oa_lookup=_must_not_call)
    assert result is None


def test_no_doi_does_not_call_the_oa_lookup(tmp_path: Path):
    # No DOI → the lookup cannot run; _must_not_call raising would surface here.
    _, manifest = _run(tmp_path, url=_SLUG_URL, oa_lookup=_must_not_call)
    assert manifest.exists()


def test_no_doi_manifest_reason_names_the_missing_doi(tmp_path: Path):
    _, manifest = _run(tmp_path, url=_SLUG_URL, oa_lookup=_must_not_call)
    assert "no DOI" in _only_record(manifest)["reason"]


# --- AC6: a lookup error is quarantined, never raised ---


def test_lookup_error_returns_none(tmp_path: Path):
    result, _ = _run(tmp_path, oa_lookup=_boom)
    assert result is None


def test_lookup_error_manifest_reason_mentions_the_error(tmp_path: Path):
    _, manifest = _run(tmp_path, oa_lookup=_boom)
    assert "unpaywall 422" in _only_record(manifest)["reason"]


# --- US10 AC1: a title-recovered DOI feeds the OA dispatch ---


def _title_doi(doi):
    """A title_lookup fake that recovers ``doi`` from any title."""
    return lambda title: doi


def test_title_recovered_doi_resolves_to_the_oa_pdf(tmp_path: Path):
    # Slug URL (no embedded DOI) → title→DOI recovers one → OA lookup finds a PDF.
    result, _ = _run(
        tmp_path,
        url=_SLUG_URL,
        oa_lookup=_found("https://oa.example.org/paper.pdf"),
        title_lookup=_title_doi("10.1191/1362168805lr151oa"),
    )
    assert result == "https://oa.example.org/paper.pdf"


def test_title_recovered_doi_closed_access_records_the_doi(tmp_path: Path):
    # The recovered DOI rejoins the OA dispatch, so a closed verdict records it.
    _, manifest = _run(
        tmp_path,
        url=_SLUG_URL,
        oa_lookup=_closed,
        title_lookup=_title_doi("10.1191/1362168805lr151oa"),
    )
    assert _only_record(manifest)["doi"] == "10.1191/1362168805lr151oa"


# --- US10 AC2: a weak/no Crossref match is quarantined, not trusted ---


def test_title_no_confident_match_returns_none(tmp_path: Path):
    result, _ = _run(
        tmp_path, url=_SLUG_URL, oa_lookup=_must_not_call, title_lookup=lambda t: None
    )
    assert result is None


def test_title_no_confident_match_reason_routes_to_human(tmp_path: Path):
    _, manifest = _run(
        tmp_path, url=_SLUG_URL, oa_lookup=_must_not_call, title_lookup=lambda t: None
    )
    assert _only_record(manifest)["reason"] == (
        "title→DOI: no confident Crossref match (route to human/browser)"
    )


# --- US10 AC3: a URL with no extractable title is quarantined ---


def test_no_title_slug_reason_names_the_missing_title(tmp_path: Path):
    _, manifest = _run(
        tmp_path, url="https://example.com/", oa_lookup=_must_not_call, title_lookup=_boom
    )
    assert _only_record(manifest)["reason"] == (
        "no DOI and no title to resolve (route to human/browser)"
    )


# --- US10 AC4: a title→DOI lookup error is quarantined, never raised ---


def test_title_lookup_error_returns_none(tmp_path: Path):
    result, _ = _run(tmp_path, url=_SLUG_URL, oa_lookup=_must_not_call, title_lookup=_boom)
    assert result is None


def test_title_lookup_error_reason_mentions_the_error(tmp_path: Path):
    _, manifest = _run(tmp_path, url=_SLUG_URL, oa_lookup=_must_not_call, title_lookup=_boom)
    assert "unpaywall 422" in _only_record(manifest)["reason"]
