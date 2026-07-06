"""Unit tests for US14 dedup_inputs (pytest).

One assertion per test (rule 05): each test fails for exactly one reason. The
normalization primitive is tested apart from the list-level dedup dispatch, and
each dispatch branch (pass-through / first-sight / repeat) is its own fact.
"""

import json
from pathlib import Path

from paper_degist.dedup_inputs import dedup_inputs, normalize_doi


def _run(tmp_path: Path, inputs):
    """Arrange a manifest and run dedup_inputs; return (kept, manifest)."""
    manifest = tmp_path / "manifest.jsonl"
    kept = dedup_inputs(inputs, manifest_path=manifest)
    return kept, manifest


def _only_record(manifest: Path):
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


# --- normalize_doi (pure): the canonical dedup key ---


def test_normalize_bare_doi_lowercases():
    assert normalize_doi("10.1177/002221949002300203") == "10.1177/002221949002300203"


def test_normalize_folds_case_since_dois_are_case_insensitive():
    assert normalize_doi("10.1109/CVPR.2016.90") == "10.1109/cvpr.2016.90"


def test_normalize_strips_doi_org_prefix_to_the_bare_key():
    link = "https://doi.org/10.1016/j.learninstruc.2007.02.008"
    assert normalize_doi(link) == "10.1016/j.learninstruc.2007.02.008"


def test_normalize_reads_doi_embedded_in_a_publisher_url_path():
    url = "https://journals.sagepub.com/doi/10.1177/002221949002300203"
    assert normalize_doi(url) == "10.1177/002221949002300203"


def test_normalize_returns_none_when_no_doi_is_extractable():
    assert normalize_doi("https://pubmed.ncbi.nlm.nih.gov/2303742/") is None


# --- dedup_inputs (list-level dispatch): pass-through / first-sight / repeat ---


def test_input_without_a_doi_passes_through(tmp_path):
    url = "https://pubmed.ncbi.nlm.nih.gov/2303742/"
    kept, _ = _run(tmp_path, [url])
    assert kept == [url]


def test_doi_org_link_then_bare_doi_keeps_only_the_first(tmp_path):
    link = "https://doi.org/10.1016/j.learninstruc.2007.02.008"
    bare = "10.1016/j.learninstruc.2007.02.008"
    kept, _ = _run(tmp_path, [link, bare])
    assert kept == [link]


def test_publisher_url_then_bare_doi_keeps_only_the_first(tmp_path):
    url = "https://journals.sagepub.com/doi/10.1177/002221949002300203"
    bare = "10.1177/002221949002300203"
    kept, _ = _run(tmp_path, [url, bare])
    assert kept == [url]


def test_survivors_are_returned_in_first_seen_order(tmp_path):
    first = "https://doi.org/10.1016/j.learninstruc.2007.02.008"
    second = "10.1177/002221949002300203"
    kept, _ = _run(tmp_path, [first, "10.1016/j.learninstruc.2007.02.008", second])
    assert kept == [first, second]


def test_no_doi_inputs_are_never_dropped_as_duplicates(tmp_path):
    url = "https://pubmed.ncbi.nlm.nih.gov/2303742/"
    kept, _ = _run(tmp_path, [url, url])
    assert kept == [url, url]


# --- AC4: the drop is auditable — a duplicate record lands in the manifest ---


def test_dropped_duplicate_appends_one_manifest_record(tmp_path):
    link = "https://doi.org/10.1016/j.learninstruc.2007.02.008"
    bare = "10.1016/j.learninstruc.2007.02.008"
    _, manifest = _run(tmp_path, [link, bare])
    assert _only_record(manifest) == {
        "stage": "dedup-inputs",
        "input": bare,
        "doi": "10.1016/j.learninstruc.2007.02.008",
        "duplicate_of": link,
    }
