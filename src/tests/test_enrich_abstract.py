"""Unit tests for US34 enrich-abstract (pytest).

One assertion per test (rule 05). All OpenAlex HTTP calls are replaced with
injected callables so tests run offline (rule 01).
"""

import json
from pathlib import Path

from paper_degist.enrich_abstract import enrich_abstract


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _candidate(
    *,
    title: str = "Test Paper",
    doi: str | None = None,
    abstract: str | None = None,
    abstract_present: bool | None = None,
    url: str = "https://doi.org/10.9/test",
) -> dict:
    c: dict = {"title": title, "url": url}
    if doi is not None:
        c["doi"] = doi
    if abstract is not None:
        c["abstract"] = abstract
    if abstract_present is not None:
        c["abstract_present"] = abstract_present
    return c


def _work(*, abstract_inverted_index=None) -> dict:
    return {
        "id": "https://openalex.org/W1",
        "abstract_inverted_index": abstract_inverted_index,
    }


def _run(
    tmp_path: Path,
    candidates: list[dict],
    *,
    fetch_work=None,
    email: str | None = None,
) -> tuple[list[dict], Path]:
    manifest = tmp_path / "manifest.jsonl"
    result = enrich_abstract(
        candidates,
        manifest_path=manifest,
        email=email,
        _fetch_work=fetch_work or (lambda doi, email: _work()),
    )
    return result, manifest


def _manifest_rows(manifest: Path) -> list[dict]:
    if not manifest.exists():
        return []
    return [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# AC2: abstract_present: true → pass through unchanged
# ---------------------------------------------------------------------------


def test_candidate_with_abstract_passes_through(tmp_path: Path):
    c = _candidate(doi="10.5555/has-abstract", abstract="Full text here.",
                   abstract_present=True)
    result, _ = _run(tmp_path, [c])
    assert len(result) == 1


def test_candidate_with_abstract_is_unchanged(tmp_path: Path):
    c = _candidate(doi="10.5555/has-abstract", abstract="Full text here.",
                   abstract_present=True)
    result, _ = _run(tmp_path, [c])
    assert result[0]["abstract"] == "Full text here."


def test_candidate_with_abstract_makes_no_api_call(tmp_path: Path):
    called = []
    c = _candidate(doi="10.5555/has-abstract", abstract="Full text here.",
                   abstract_present=True)
    _run(tmp_path, [c], fetch_work=lambda doi, email: called.append(doi) or _work())
    assert called == []


# ---------------------------------------------------------------------------
# AC1: abstract_present: false + doi → enrich and emit
# ---------------------------------------------------------------------------


def test_missing_abstract_is_enriched(tmp_path: Path):
    inverted = {"Attention": [0], "is": [1], "all": [2], "you": [3], "need": [4]}
    c = _candidate(doi="10.5555/enrich-me", abstract_present=False)
    fetch = lambda doi, email: _work(abstract_inverted_index=inverted)
    result, _ = _run(tmp_path, [c], fetch_work=fetch)
    assert result[0]["abstract"] == "Attention is all you need"


def test_enriched_candidate_has_abstract_present_true(tmp_path: Path):
    inverted = {"Hello": [0], "world": [1]}
    c = _candidate(doi="10.5555/enrich-me-2", abstract_present=False)
    fetch = lambda doi, email: _work(abstract_inverted_index=inverted)
    result, _ = _run(tmp_path, [c], fetch_work=fetch)
    assert result[0]["abstract_present"] is True


def test_enriched_candidate_other_fields_unchanged(tmp_path: Path):
    inverted = {"Test": [0]}
    c = _candidate(doi="10.5555/enrich-me-3", title="My Paper", abstract_present=False)
    fetch = lambda doi, email: _work(abstract_inverted_index=inverted)
    result, _ = _run(tmp_path, [c], fetch_work=fetch)
    assert result[0]["title"] == "My Paper"


# ---------------------------------------------------------------------------
# AC3: no doi → quarantine no-doi
# ---------------------------------------------------------------------------


def test_no_doi_candidate_quarantines(tmp_path: Path):
    c = _candidate(abstract_present=False)  # no doi key
    result, _ = _run(tmp_path, [c])
    assert result == []


def test_no_doi_manifest_row_has_no_doi_reason(tmp_path: Path):
    c = _candidate(abstract_present=False)
    _, manifest = _run(tmp_path, [c])
    rows = _manifest_rows(manifest)
    assert any(r.get("reason") == "no-doi" for r in rows)


def test_no_doi_manifest_row_stage_is_enrich_abstract(tmp_path: Path):
    c = _candidate(abstract_present=False)
    _, manifest = _run(tmp_path, [c])
    rows = _manifest_rows(manifest)
    assert any(r.get("stage") == "enrich-abstract" for r in rows)


# ---------------------------------------------------------------------------
# AC4: DOI not found on OpenAlex → quarantine doi-not-found
# ---------------------------------------------------------------------------


def test_doi_not_found_quarantines(tmp_path: Path):
    c = _candidate(doi="10.5555/missing-doi", abstract_present=False)
    fetch = lambda doi, email: (_ for _ in ()).throw(RuntimeError("404 Not Found"))
    result, _ = _run(tmp_path, [c], fetch_work=fetch)
    assert result == []


def test_doi_not_found_manifest_row_reason(tmp_path: Path):
    c = _candidate(doi="10.5555/missing-doi-2", abstract_present=False)
    fetch = lambda doi, email: (_ for _ in ()).throw(RuntimeError("404 Not Found"))
    _, manifest = _run(tmp_path, [c], fetch_work=fetch)
    rows = _manifest_rows(manifest)
    assert any(r.get("reason") == "doi-not-found" for r in rows)


# ---------------------------------------------------------------------------
# AC5: Work has no abstract_inverted_index → quarantine no-abstract-on-record
# ---------------------------------------------------------------------------


def test_no_abstract_on_record_quarantines(tmp_path: Path):
    c = _candidate(doi="10.5555/no-abstract-record", abstract_present=False)
    fetch = lambda doi, email: _work(abstract_inverted_index=None)
    result, _ = _run(tmp_path, [c], fetch_work=fetch)
    assert result == []


def test_no_abstract_on_record_manifest_row_reason(tmp_path: Path):
    c = _candidate(doi="10.5555/no-abstract-record-2", abstract_present=False)
    fetch = lambda doi, email: _work(abstract_inverted_index=None)
    _, manifest = _run(tmp_path, [c], fetch_work=fetch)
    rows = _manifest_rows(manifest)
    assert any(r.get("reason") == "no-abstract-on-record" for r in rows)


# ---------------------------------------------------------------------------
# Batch: rest continue when one quarantines
# ---------------------------------------------------------------------------


def test_rest_continue_when_one_quarantines(tmp_path: Path):
    no_doi = _candidate(title="No DOI Paper", abstract_present=False)
    good = _candidate(doi="10.5555/good-paper", title="Good Paper", abstract_present=False)
    inverted = {"A": [0]}
    fetch = lambda doi, email: _work(abstract_inverted_index=inverted)
    result, _ = _run(tmp_path, [no_doi, good], fetch_work=fetch)
    titles = [r["title"] for r in result]
    assert "Good Paper" in titles
