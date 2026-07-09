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

import pytest

from paper_degist.resolve_oa import (
    _OALanding,
    _doi_from_crossref,
    _openalex_oa_lookup,
    _pdf_url_from_unpaywall,
    doi_from,
    resolve_oa,
    title_from,
)

_DOI_URL = "https://doi.org/10.1191/1362168805lr151oa"
_SLUG_URL = "https://www.researchgate.net/publication/249870239_An_investigation"


def _run(tmp_path, *, url=_DOI_URL, oa_lookup, title_lookup=None, oa_fallback=None):
    """Arrange a fresh manifest and run resolve_oa; return (result, manifest)."""
    manifest = tmp_path / "manifest.jsonl"
    result = resolve_oa(
        url,
        manifest_path=manifest,
        oa_lookup=oa_lookup,
        title_lookup=title_lookup,
        oa_fallback=oa_fallback,
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


def test_unpaywall_open_landing_only_is_not_returned_as_str():
    # is_oa=True with only a landing page: must NOT return a str — fetch-one cannot
    # download an HTML landing page, so the caller must never treat it as a PDF URL.
    data = {"is_oa": True, "best_oa_location": {"url": "https://oa.org/landing", "url_for_pdf": None}}
    assert not isinstance(_pdf_url_from_unpaywall(data), str)


def test_unpaywall_open_landing_only_returns_oa_landing():
    # is_oa=True with only a landing URL: returned as an _OALanding, never None
    # (None would lose the "open" signal and get mislabelled "closed access").
    data = {"is_oa": True, "best_oa_location": {"url": "https://hal.science/hal-00572075", "url_for_pdf": None}}
    assert isinstance(_pdf_url_from_unpaywall(data), _OALanding)


def test_unpaywall_open_landing_only_carries_the_landing_url():
    data = {"is_oa": True, "best_oa_location": {"url": "https://hal.science/hal-00572075", "url_for_pdf": None}}
    result = _pdf_url_from_unpaywall(data)
    assert result.url == "https://hal.science/hal-00572075"


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


# --- open-access landing-only: is_oa=True but no direct PDF (the bug case) ---


def _open_landing(landing_url):
    """Mock oa_lookup: is_oa=True but only a landing page, no direct PDF."""
    return lambda doi: _OALanding(landing_url)


def test_open_landing_returns_none(tmp_path: Path):
    result, _ = _run(tmp_path, oa_lookup=_open_landing("https://hal.science/hal-00572075"))
    assert result is None


def test_open_landing_writes_a_manifest_record(tmp_path: Path):
    _, manifest = _run(tmp_path, oa_lookup=_open_landing("https://hal.science/hal-00572075"))
    assert manifest.exists()


def test_open_landing_reason_does_not_say_closed_access(tmp_path: Path):
    # Unpaywall says is_oa=True: the quarantine reason must never claim "closed access".
    _, manifest = _run(tmp_path, oa_lookup=_open_landing("https://hal.science/hal-00572075"))
    assert "closed access" not in _only_record(manifest)["reason"]


def test_open_landing_reason_surfaces_the_landing_url(tmp_path: Path):
    _, manifest = _run(tmp_path, oa_lookup=_open_landing("https://cogentoa.com/article/10.1080/2331186x.2017.1287391"))
    assert "https://cogentoa.com/article/10.1080/2331186x.2017.1287391" in _only_record(manifest)["reason"]


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


# --- US30 AC1: OpenAlex fallback finds a PDF that Unpaywall (closed) missed ---


def test_openalex_fallback_returns_the_pdf_when_unpaywall_closed(tmp_path: Path):
    result, _ = _run(
        tmp_path,
        oa_lookup=_closed,
        oa_fallback=_found("https://repo.example.org/openalex.pdf"),
    )
    assert result == "https://repo.example.org/openalex.pdf"


def test_openalex_fallback_hit_writes_no_manifest_record(tmp_path: Path):
    _, manifest = _run(
        tmp_path,
        oa_lookup=_closed,
        oa_fallback=_found("https://repo.example.org/openalex.pdf"),
    )
    assert not manifest.exists()


# --- US30 AC3: Unpaywall's own PDF short-circuits — OpenAlex is never called ---


def test_unpaywall_pdf_does_not_call_openalex_fallback(tmp_path: Path):
    # Unpaywall already resolved a PDF, so the fallback must never run
    # (_must_not_call raising would surface the extra call as a failure).
    result, _ = _run(
        tmp_path,
        oa_lookup=_found("https://oa.example.org/unpaywall.pdf"),
        oa_fallback=_must_not_call,
    )
    assert result == "https://oa.example.org/unpaywall.pdf"


# --- US30 AC2: both indexes closed → quarantine names both were checked ---


def test_both_indexes_closed_returns_none(tmp_path: Path):
    result, _ = _run(tmp_path, oa_lookup=_closed, oa_fallback=_closed)
    assert result is None


def test_both_indexes_closed_reason_names_both_sources(tmp_path: Path):
    _, manifest = _run(tmp_path, oa_lookup=_closed, oa_fallback=_closed)
    assert _only_record(manifest)["reason"] == (
        "no OA copy (closed access) — checked Unpaywall and OpenAlex"
    )


# --- US30 AC4: an OpenAlex fallback error is quarantined, naming OpenAlex ---


def _openalex_boom(doi):
    raise RuntimeError("openalex 503")


def test_openalex_fallback_error_returns_none(tmp_path: Path):
    result, _ = _run(tmp_path, oa_lookup=_closed, oa_fallback=_openalex_boom)
    assert result is None


def test_openalex_fallback_error_reason_names_openalex(tmp_path: Path):
    _, manifest = _run(tmp_path, oa_lookup=_closed, oa_fallback=_openalex_boom)
    reason = _only_record(manifest)["reason"]
    assert reason == "OpenAlex OA lookup error: openalex 503"


# --- US30: the real _openalex_oa_lookup builder (works-by-DOI + polite pool) ---


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _capture_openalex(monkeypatch, payload):
    """Patch httpx.get to record the request and return ``payload`` as JSON."""
    import httpx

    calls: dict = {}

    def fake_get(url, **kwargs):
        calls["url"] = url
        calls["params"] = kwargs.get("params")
        return _FakeResp(payload)

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


_OPENALEX_WORK_WITH_PDF = {"best_oa_location": {"pdf_url": "https://repo.example/oa/42.pdf"}}


def test_openalex_lookup_extracts_pdf_from_work(monkeypatch):
    _capture_openalex(monkeypatch, _OPENALEX_WORK_WITH_PDF)
    lookup = _openalex_oa_lookup("me@example.com")
    assert lookup("10.1145/3292500.3330701") == "https://repo.example/oa/42.pdf"


def test_openalex_lookup_addresses_the_work_by_doi(monkeypatch):
    calls = _capture_openalex(monkeypatch, _OPENALEX_WORK_WITH_PDF)
    _openalex_oa_lookup("me@example.com")("10.1145/3292500.3330701")
    assert calls["url"].endswith("/works/doi:10.1145/3292500.3330701")


def test_openalex_lookup_with_email_sends_the_mailto(monkeypatch):
    calls = _capture_openalex(monkeypatch, _OPENALEX_WORK_WITH_PDF)
    _openalex_oa_lookup("me@example.com")("10.1145/3292500.3330701")
    assert calls["params"]["mailto"] == "me@example.com"


def test_openalex_lookup_without_email_omits_the_mailto(monkeypatch):
    # AC5: keyless is allowed — the request runs on the common pool, no mailto.
    calls = _capture_openalex(monkeypatch, _OPENALEX_WORK_WITH_PDF)
    _openalex_oa_lookup(None)("10.1145/3292500.3330701")
    assert "mailto" not in calls["params"]


def test_openalex_lookup_without_email_warns_about_the_polite_pool(monkeypatch, capsys):
    # AC5: a missing email downgrades politeness (warn), it does not skip the check.
    _openalex_oa_lookup(None)
    assert "polite pool" in capsys.readouterr().err


class _ErrResp:
    """A fake httpx response whose raise_for_status raises an HTTP status error."""

    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        import httpx

        raise httpx.HTTPStatusError(
            str(self.status_code), request=httpx.Request("GET", "http://x"), response=self
        )

    def json(self):
        return {}


def _openalex_http_status(monkeypatch, status):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda url, **kw: _ErrResp(status))


def test_openalex_lookup_404_is_treated_as_no_oa_copy(monkeypatch):
    # A DOI OpenAlex does not index answers 404 — a definitive "no record here",
    # not a transport failure: it feeds the union as no-OA (→ both-checked closed),
    # not the AC4 error path with a scary "lookup error" reason.
    _openalex_http_status(monkeypatch, 404)
    assert _openalex_oa_lookup("me@example.com")("10.9999/not.indexed") is None


def test_openalex_lookup_503_propagates_as_an_error(monkeypatch):
    # A real transport failure (5xx/429/network) still raises, so resolve_oa
    # quarantines it as an OpenAlex lookup error (AC4), distinct from no-OA.
    import httpx

    _openalex_http_status(monkeypatch, 503)
    lookup = _openalex_oa_lookup("me@example.com")
    with pytest.raises(httpx.HTTPStatusError):
        lookup("10.1145/3292500.3330701")


# --- US11 AC1/AC2: a resolve-oa quarantine carries a clickable doi.org link ---


def test_closed_access_manifest_adds_clickable_doi_url(tmp_path: Path):
    # AC1: a quarantine that recovered a DOI also carries https://doi.org/<doi>,
    # so a manifest reader can click straight through instead of copy-pasting.
    _, manifest = _run(tmp_path, oa_lookup=_closed)
    assert _only_record(manifest)["doi_url"] == "https://doi.org/10.1191/1362168805lr151oa"


def test_no_doi_manifest_adds_no_doi_url(tmp_path: Path):
    # AC2: no DOI recovered (title dead-ends) → no doi_url; nothing to link.
    _, manifest = _run(tmp_path, url=_SLUG_URL, oa_lookup=_must_not_call)
    assert "doi_url" not in _only_record(manifest)
