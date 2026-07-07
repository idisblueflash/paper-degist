"""Unit tests for US33 snowball (pytest).

One assertion per test (rule 05). The step is offline when injected — all
real HTTP calls are replaced with callable fixtures that return canned
OpenAlex shapes; distinct real papers label each scenario (rule 08).
"""

import json
from pathlib import Path

from paper_degist.snowball import snowball


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _work(
    openalex_id: str,
    *,
    doi: str | None = None,
    title: str = "Test Paper",
    cited_by: int | None = None,
    referenced_works: list[str] | None = None,
    abstract_inverted_index: dict | None = None,
    authorships: list | None = None,
) -> dict:
    """Minimal OpenAlex Work dict (search-result or single-record shape)."""
    w: dict = {
        "id": f"https://openalex.org/{openalex_id}",
        "title": title,
        "publication_date": "2023-01-01",
        "authorships": authorships or [],
        "referenced_works": [f"https://openalex.org/{r}" for r in (referenced_works or [])],
        "abstract_inverted_index": abstract_inverted_index,
        "best_oa_location": None,
        "oa_locations": [],
        "locations": [],
    }
    if doi:
        w["doi"] = f"https://doi.org/{doi}"
    if cited_by is not None:
        w["cited_by_count"] = cited_by
    return w


def _results_page(works: list[dict], *, total: int | None = None) -> dict:
    """Wrap works in OpenAlex paginated-results shape."""
    return {
        "meta": {"count": total or len(works), "per_page": 200, "page": 1},
        "results": works,
    }


def _run(
    tmp_path: Path,
    seed_doi: str,
    *,
    fetch_seed,
    fetch_refs=None,
    fetch_citers=None,
    direction="both",
    max_refs: int = 200,
    max_citers: int = 200,
):
    manifest = tmp_path / "manifest.jsonl"
    result = snowball(
        seed_doi,
        direction=direction,
        max_refs=max_refs,
        max_citers=max_citers,
        manifest_path=manifest,
        _fetch_seed=fetch_seed,
        _fetch_refs=fetch_refs or (lambda *a, **kw: _results_page([])),
        _fetch_citers=fetch_citers or (lambda *a, **kw: _results_page([])),
    )
    return result, manifest


def _manifest_rows(manifest: Path) -> list[dict]:
    if not manifest.exists():
        return []
    return [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# AC5: seed not found → quarantine, nothing emitted
# ---------------------------------------------------------------------------


def test_seed_not_found_quarantines(tmp_path: Path):
    def fetch_seed(doi, email):
        raise RuntimeError("404 not found")

    result, _ = _run(tmp_path, "10.9999/not-real", fetch_seed=fetch_seed)
    assert result is None


def test_seed_not_found_leaves_manifest_row(tmp_path: Path):
    def fetch_seed(doi, email):
        raise RuntimeError("404 not found")

    _, manifest = _run(tmp_path, "10.9999/not-real-doi", fetch_seed=fetch_seed)
    rows = _manifest_rows(manifest)
    assert any(r.get("stage") == "snowball" and r.get("event") == "quarantined" for r in rows)


# ---------------------------------------------------------------------------
# AC1: refs direction — referenced works emitted as candidates
# ---------------------------------------------------------------------------


def test_refs_direction_emits_first_referenced_work(tmp_path: Path):
    seed = _work("W100", doi="10.48550/arxiv.1706.03762", title="Attention Is All You Need",
                 referenced_works=["W200", "W300"])
    ref1 = _work("W200", doi="10.5555/lstm", title="Long Short-Term Memory", cited_by=2800)
    ref2 = _work("W300", doi="10.5555/seq2seq", title="Sequence to Sequence Learning", cited_by=5100)

    result, _ = _run(tmp_path, "10.48550/arxiv.1706.03762",
                     fetch_seed=lambda *a, **kw: seed,
                     fetch_refs=lambda *a, **kw: _results_page([ref1, ref2]),
                     direction="refs")
    titles = [r["title"] for r in result]
    assert "Long Short-Term Memory" in titles


def test_refs_direction_emits_second_referenced_work(tmp_path: Path):
    seed = _work("W100", doi="10.48550/arxiv.1706.03762", title="Attention Is All You Need",
                 referenced_works=["W200", "W300"])
    ref1 = _work("W200", doi="10.5555/lstm", title="Long Short-Term Memory", cited_by=2800)
    ref2 = _work("W300", doi="10.5555/seq2seq", title="Sequence to Sequence Learning", cited_by=5100)

    result, _ = _run(tmp_path, "10.48550/arxiv.1706.03762",
                     fetch_seed=lambda *a, **kw: seed,
                     fetch_refs=lambda *a, **kw: _results_page([ref1, ref2]),
                     direction="refs")
    titles = [r["title"] for r in result]
    assert "Sequence to Sequence Learning" in titles


def test_refs_direction_records_cited_by(tmp_path: Path):
    seed = _work("W100", doi="10.48550/arxiv.1706.03762", title="Attention Is All You Need",
                 referenced_works=["W200"])
    ref = _work("W200", doi="10.5555/lstm", title="Long Short-Term Memory", cited_by=2800)

    result, _ = _run(tmp_path, "10.48550/arxiv.1706.03762",
                     fetch_seed=lambda *a, **kw: seed,
                     fetch_refs=lambda *a, **kw: _results_page([ref]),
                     direction="refs")
    assert result[0]["cited_by"] == 2800


# ---------------------------------------------------------------------------
# AC2: citers direction — papers citing the seed are emitted
# ---------------------------------------------------------------------------


def test_citers_direction_emits_citing_papers(tmp_path: Path):
    seed = _work("W100", doi="10.48550/arxiv.1706.03762", title="Attention Is All You Need")
    citer = _work("W400", doi="10.5555/bert", title="BERT: Pre-training of Deep Bidirectional Transformers",
                  cited_by=42000)

    result, _ = _run(tmp_path, "10.48550/arxiv.1706.03762",
                     fetch_seed=lambda *a, **kw: seed,
                     fetch_citers=lambda *a, **kw: _results_page([citer]),
                     direction="citers")
    titles = [r["title"] for r in result]
    assert "BERT: Pre-training of Deep Bidirectional Transformers" in titles


# ---------------------------------------------------------------------------
# AC3: both directions — refs first, then citers, no duplicates
# ---------------------------------------------------------------------------


def test_both_direction_emits_refs_then_citers(tmp_path: Path):
    seed = _work("W100", doi="10.48550/arxiv.1706.03762", title="Attention Is All You Need",
                 referenced_works=["W200"])
    ref = _work("W200", doi="10.5555/lstm", title="Long Short-Term Memory", cited_by=2800)
    citer = _work("W400", doi="10.5555/bert", title="BERT: Pre-training of Deep Bidirectional Transformers",
                  cited_by=42000)

    result, _ = _run(tmp_path, "10.48550/arxiv.1706.03762",
                     fetch_seed=lambda *a, **kw: seed,
                     fetch_refs=lambda *a, **kw: _results_page([ref]),
                     fetch_citers=lambda *a, **kw: _results_page([citer]),
                     direction="both")
    titles = [r["title"] for r in result]
    assert titles == ["Long Short-Term Memory",
                      "BERT: Pre-training of Deep Bidirectional Transformers"]


def test_both_direction_deduplicates_same_openalex_id(tmp_path: Path):
    seed = _work("W100", doi="10.48550/arxiv.1706.03762", title="Attention Is All You Need",
                 referenced_works=["W200"])
    # W200 appears both as a reference and a citer (unusual but possible)
    w200 = _work("W200", doi="10.5555/lstm", title="Long Short-Term Memory", cited_by=2800)

    result, _ = _run(tmp_path, "10.48550/arxiv.1706.03762",
                     fetch_seed=lambda *a, **kw: seed,
                     fetch_refs=lambda *a, **kw: _results_page([w200]),
                     fetch_citers=lambda *a, **kw: _results_page([w200]),
                     direction="both")
    assert len(result) == 1


# ---------------------------------------------------------------------------
# AC4: max-refs cap silently limits the reference count
# ---------------------------------------------------------------------------


def test_max_refs_caps_the_reference_list(tmp_path: Path):
    seed = _work("W100", doi="10.48550/arxiv.2205.14135", title="FlashAttention",
                 referenced_works=["W201", "W202", "W203"])
    refs = [
        _work("W201", doi="10.5555/paper1", title="Flash Ref 1", cited_by=100),
        _work("W202", doi="10.5555/paper2", title="Flash Ref 2", cited_by=200),
        _work("W203", doi="10.5555/paper3", title="Flash Ref 3", cited_by=300),
    ]

    # fetch_refs receives max_refs; the stub returns all 3 but caller cuts to max
    result, manifest = _run(tmp_path, "10.48550/arxiv.2205.14135",
                            fetch_seed=lambda *a, **kw: seed,
                            fetch_refs=lambda *a, **kw: _results_page(refs),
                            direction="refs",
                            max_refs=2)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# AC6: work with no URL → filtered manifest row, rest continue
# ---------------------------------------------------------------------------


def test_good_work_passes_through_when_another_has_no_url(tmp_path: Path):
    seed = _work("W100", doi="10.48550/arxiv.2112.10741", title="Gato",
                 referenced_works=["W_nouri", "W_good"])
    no_url_work = {"id": None, "doi": None, "title": "Opaque Work", "authorships": [],
                   "abstract_inverted_index": None, "best_oa_location": None,
                   "oa_locations": [], "locations": [], "referenced_works": []}
    good_work = _work("W_good", doi="10.5555/good", title="Perceiver IO", cited_by=500)

    result, _ = _run(tmp_path, "10.48550/arxiv.2112.10741",
                     fetch_seed=lambda *a, **kw: seed,
                     fetch_refs=lambda *a, **kw: _results_page([no_url_work, good_work]),
                     direction="refs")
    titles = [r["title"] for r in result]
    assert "Perceiver IO" in titles


def test_no_url_work_is_excluded_from_output(tmp_path: Path):
    seed = _work("W100", doi="10.48550/arxiv.2112.10741", title="Gato",
                 referenced_works=["W_nouri", "W_good"])
    no_url_work = {"id": None, "doi": None, "title": "Opaque Work", "authorships": [],
                   "abstract_inverted_index": None, "best_oa_location": None,
                   "oa_locations": [], "locations": [], "referenced_works": []}
    good_work = _work("W_good", doi="10.5555/good", title="Perceiver IO", cited_by=500)

    result, _ = _run(tmp_path, "10.48550/arxiv.2112.10741",
                     fetch_seed=lambda *a, **kw: seed,
                     fetch_refs=lambda *a, **kw: _results_page([no_url_work, good_work]),
                     direction="refs")
    titles = [r["title"] for r in result]
    assert "Opaque Work" not in titles


def test_seed_with_no_openalex_id_quarantines_citers_lane(tmp_path: Path):
    """Seed whose 'id' is None → citers lane quarantines; refs can still run."""
    seed_no_id = {
        "id": None,
        "doi": "https://doi.org/10.1234/no-id",
        "referenced_works": [],
        "authorships": [],
        "abstract_inverted_index": None,
        "best_oa_location": None,
        "oa_locations": [],
        "locations": [],
    }
    _, manifest = _run(
        tmp_path,
        "10.1234/no-id",
        fetch_seed=lambda *a, **kw: seed_no_id,
        direction="both",
    )
    rows = _manifest_rows(manifest)
    assert any(
        r.get("event") == "quarantined" and "seed-missing-id" in r.get("reason", "")
        for r in rows
    )


def test_no_url_work_leaves_filtered_manifest_row(tmp_path: Path):
    seed = _work("W100", doi="10.48550/arxiv.2112.10741", title="Gato",
                 referenced_works=["W_nouri"])
    no_url_work = {"id": None, "doi": None, "title": "Opaque Work", "authorships": [],
                   "abstract_inverted_index": None, "best_oa_location": None,
                   "oa_locations": [], "locations": [], "referenced_works": []}

    _, manifest = _run(tmp_path, "10.48550/arxiv.2112.10741",
                       fetch_seed=lambda *a, **kw: seed,
                       fetch_refs=lambda *a, **kw: _results_page([no_url_work]),
                       direction="refs")
    rows = _manifest_rows(manifest)
    assert any(r.get("event") == "filtered" and r.get("reason") == "no-url" for r in rows)
