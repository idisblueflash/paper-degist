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

from paper_degist.resolve_oa import doi_from, resolve_oa

_DOI_URL = "https://doi.org/10.1191/1362168805lr151oa"
_SLUG_URL = "https://www.researchgate.net/publication/249870239_An_investigation"


def _run(tmp_path, *, url=_DOI_URL, oa_lookup):
    """Arrange a fresh manifest and run resolve_oa; return (result, manifest)."""
    manifest = tmp_path / "manifest.jsonl"
    result = resolve_oa(url, manifest_path=manifest, oa_lookup=oa_lookup)
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
