"""Unit tests for US31 discover-batch (pytest).

One assertion per test (rule 05). The batch driver composes `discover` (US25),
so these tests inject the same fake-`Search` registry style as test_discover —
fast and offline (rule 01); the live fan-out is the real E2E run (rule 06 §7).
Distinct example queries/papers per case (rule 08) label what each exercises.
"""

import json
from pathlib import Path

from paper_degist.discover import Candidate
from paper_degist.discover_batch import discover_batch


def _candidate(
    *,
    title="Mamba: Linear-Time Sequence Modeling",
    url="http://arxiv.org/abs/2312.00752v1",
    source="arxiv",
    source_id="2312.00752v1",
    abstract="Selective state space models match Transformers.",
    doi=None,
) -> Candidate:
    return Candidate(
        title=title,
        authors=["Albert Gu", "Tri Dao"],
        abstract=abstract,
        url=url,
        published="2023-12-01T00:00:00Z",
        source=source,
        source_id=source_id,
        doi=doi,
    )


def _recording_search(candidates):
    """A Search returning the given candidates, recording each query it saw."""

    def search(query):
        search.queries.append(query)
        return list(candidates)

    search.queries = []
    return search


def _run(tmp_path: Path, queries, registry, sources=None, pause=None):
    manifest = tmp_path / "manifest.jsonl"
    result = discover_batch(
        queries,
        sources or list(registry),
        registry=registry,
        manifest_path=manifest,
        pause=pause or (lambda seconds: None),
    )
    return result, manifest


def _records(manifest: Path, stage: str) -> list[dict]:
    lines = manifest.read_text(encoding="utf-8").splitlines()
    return [r for line in lines if (r := json.loads(line)).get("stage") == stage]


# --- AC1: fan out over the queries x sources cross product ---


def test_each_source_sees_every_query(tmp_path: Path):
    arxiv = _recording_search([_candidate()])
    openalex = _recording_search([])
    _run(
        tmp_path,
        ["state space models for long sequences", "linear attention transformers"],
        {"arxiv": arxiv, "openalex": openalex},
    )
    assert arxiv.queries == openalex.queries == [
        "state space models for long sequences",
        "linear attention transformers",
    ]


def test_merged_output_carries_every_pairs_candidates(tmp_path: Path):
    # Two distinct papers from two sources, one query — both survive the merge.
    arxiv = _recording_search([_candidate()])
    openalex = _recording_search(
        [
            _candidate(
                title="Efficiently Modeling Long Sequences with S4",
                url="https://doi.org/10.48550/arxiv.2111.00396",
                source="openalex",
                source_id="W3212345678",
                doi="10.48550/arxiv.2111.00396",
            )
        ]
    )
    result, _ = _run(
        tmp_path,
        ["structured state space sequence models"],
        {"arxiv": arxiv, "openalex": openalex},
    )
    assert [r["title"] for r in result] == [
        "Mamba: Linear-Time Sequence Modeling",
        "Efficiently Modeling Long Sequences with S4",
    ]


def test_batch_summary_record_carries_the_run_shape(tmp_path: Path):
    # AC1: one discover-batch summary row — queries, sources, merged count.
    _, manifest = _run(
        tmp_path,
        ["gated linear recurrent units"],
        {"arxiv": _recording_search([_candidate()]), "openalex": _recording_search([])},
        sources=["arxiv", "openalex"],
    )
    (summary,) = _records(manifest, "discover-batch")
    assert summary == {
        "stage": "discover-batch",
        "queries": 1,
        "sources": ["arxiv", "openalex"],
        "result_count": 1,
    }


# --- AC2/AC3: merge dedups the union (normalized DOI, then source_id) ---


def _liquid_openalex() -> Candidate:
    return _candidate(
        title="Liquid Time-constant Networks",
        url="https://doi.org/10.1016/j.neunet.2024.106789",
        source="openalex",
        source_id="W4402112233",
        doi="10.1016/j.neunet.2024.106789",
    )


def _liquid_s2() -> Candidate:
    # The same paper as _liquid_openalex, DOI spelled with resolver + case noise.
    return _candidate(
        title="Liquid Time-constant Networks",
        url="https://www.semanticscholar.org/paper/ltc99",
        source="s2",
        source_id="ltc99",
        doi="https://doi.org/10.1016/J.NEUNET.2024.106789",
    )


def test_same_normalized_doi_keeps_only_the_first_seen(tmp_path: Path):
    result, _ = _run(
        tmp_path,
        ["liquid time-constant networks"],
        {"openalex": _recording_search([_liquid_openalex()]), "s2": _recording_search([_liquid_s2()])},
        sources=["openalex", "s2"],
    )
    assert [r["source"] for r in result] == ["openalex"]


def test_doi_duplicate_leaves_a_dedup_doi_filtered_record(tmp_path: Path):
    _, manifest = _run(
        tmp_path,
        ["liquid time-constant networks"],
        {"openalex": _recording_search([_liquid_openalex()]), "s2": _recording_search([_liquid_s2()])},
        sources=["openalex", "s2"],
    )
    (dropped,) = [r for r in _records(manifest, "discover-batch") if r.get("event") == "filtered"]
    assert dropped == {
        "stage": "discover-batch",
        "event": "filtered",
        "url": "https://www.semanticscholar.org/paper/ltc99",
        "source": "s2",
        "reason": "dedup-doi",
        "duplicate_of": "https://doi.org/10.1016/j.neunet.2024.106789",
    }


def test_doiless_same_source_repeat_is_emitted_once(tmp_path: Path):
    # One DOI-less arXiv paper hit by both overlapping queries (AC3).
    arxiv = _recording_search(
        [_candidate(title="RWKV: Reinventing RNNs for the Transformer Era",
                    url="http://arxiv.org/abs/2305.13048v2", source_id="2305.13048v2")]
    )
    result, _ = _run(
        tmp_path,
        ["recurrent transformer language models", "linear attention RNN hybrids"],
        {"arxiv": arxiv},
    )
    assert len(result) == 1


def test_doiless_same_source_repeat_reason_is_dedup_source_id(tmp_path: Path):
    arxiv = _recording_search(
        [_candidate(title="RWKV: Reinventing RNNs for the Transformer Era",
                    url="http://arxiv.org/abs/2305.13048v2", source_id="2305.13048v2")]
    )
    _, manifest = _run(
        tmp_path,
        ["recurrent transformer language models", "linear attention RNN hybrids"],
        {"arxiv": arxiv},
    )
    (dropped,) = [r for r in _records(manifest, "discover-batch") if r.get("event") == "filtered"]
    assert dropped["reason"] == "dedup-source-id"


def _sequenced_search(batches):
    """A Search returning the next batch per call — per-query answers differ."""
    remaining = list(batches)

    def search(query):
        return list(remaining.pop(0))

    return search


def test_doi_flipping_same_source_repeat_is_still_emitted_once(tmp_path: Path):
    # The same s2 paper answers the first query with its DOI but the second
    # without it (Codex review): the merge must match on the (source,
    # source_id) identity registered alongside the DOI, not just the DOI.
    hyena_with_doi = _candidate(
        title="Hyena Hierarchy: Towards Larger Convolutional Language Models",
        url="https://www.semanticscholar.org/paper/hyena77",
        source="s2",
        source_id="hyena77",
        doi="10.48550/arxiv.2302.10866",
    )
    hyena_doiless = _candidate(
        title="Hyena Hierarchy: Towards Larger Convolutional Language Models",
        url="https://www.semanticscholar.org/paper/hyena77",
        source="s2",
        source_id="hyena77",
        doi=None,
    )
    result, _ = _run(
        tmp_path,
        ["implicit convolution language models", "subquadratic attention replacements"],
        {"s2": _sequenced_search([[hyena_with_doi], [hyena_doiless]])},
    )
    assert len(result) == 1


# --- AC4: a duplicate that carries an abstract replaces an abstract-less stub ---


def _flashattention_stub() -> Candidate:
    # A bibliographic scholar-author stub: same DOI, no abstract (US27 AC3 shape).
    return _candidate(
        title="FlashAttention: Fast and Memory-Efficient Exact Attention",
        url="https://scholar.google.com/citations?view_op=view_citation&citation_for_view=fa1",
        source="scholar-author",
        source_id="TriDaoAAAJ:fa1",
        abstract=None,
        doi="10.48550/arxiv.2205.14135",
    )


def _flashattention_full() -> Candidate:
    return _candidate(
        title="FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness",
        url="https://doi.org/10.48550/arxiv.2205.14135",
        source="openalex",
        source_id="W4281694645",
        abstract="We propose FlashAttention, an IO-aware exact attention algorithm.",
        doi="10.48550/arxiv.2205.14135",
    )


def _run_upgrade(tmp_path: Path):
    return _run(
        tmp_path,
        ["IO-aware exact attention kernels"],
        {
            "scholar-author": _recording_search([_flashattention_stub()]),
            "openalex": _recording_search([_flashattention_full()]),
        },
        sources=["scholar-author", "openalex"],
    )


def test_abstract_carrying_duplicate_replaces_the_kept_stub(tmp_path: Path):
    result, _ = _run_upgrade(tmp_path)
    (kept,) = result
    assert kept["source"] == "openalex"


def test_upgrade_records_the_replaced_stub_as_filtered(tmp_path: Path):
    _, manifest = _run_upgrade(tmp_path)
    (dropped,) = [r for r in _records(manifest, "discover-batch") if r.get("event") == "filtered"]
    assert dropped["url"] == (
        "https://scholar.google.com/citations?view_op=view_citation&citation_for_view=fa1"
    )


# --- AC5/AC6: a failing pair takes out only itself; an all-empty batch quarantines ---


def _rate_limited_search():
    def search(query):
        raise RuntimeError("HTTP 429 Too Many Requests")

    return search


def test_a_failing_pair_does_not_kill_the_batch(tmp_path: Path):
    result, _ = _run(
        tmp_path,
        ["test-time training layers"],
        {"s2": _rate_limited_search(), "arxiv": _recording_search([_candidate()])},
        sources=["s2", "arxiv"],
    )
    assert [r["title"] for r in result] == ["Mamba: Linear-Time Sequence Modeling"]


def test_the_failing_pairs_quarantine_row_lands_in_the_batch_manifest(tmp_path: Path):
    # AC5's other half (Codex review): the batch survives *and* the failing
    # pair's own quarantine row — written by the inherited discover core —
    # is in the same manifest, so the leg's failure is never silent.
    _, manifest = _run(
        tmp_path,
        ["test-time training layers"],
        {"s2": _rate_limited_search(), "arxiv": _recording_search([_candidate()])},
        sources=["s2", "arxiv"],
    )
    (row,) = [r for r in _records(manifest, "discover") if "api-error" in r.get("reason", "")]
    assert row["source"] == "s2"


def test_all_empty_batch_returns_none(tmp_path: Path):
    result, _ = _run(
        tmp_path,
        ["qwertyuiop nonexistent retrieval zzzz"],
        {"arxiv": _recording_search([]), "openalex": _rate_limited_search()},
        sources=["arxiv", "openalex"],
    )
    assert result is None


def test_all_empty_batch_quarantines_with_an_empty_batch_reason(tmp_path: Path):
    _, manifest = _run(
        tmp_path,
        ["qwertyuiop nonexistent retrieval zzzz"],
        {"arxiv": _recording_search([]), "openalex": _rate_limited_search()},
        sources=["arxiv", "openalex"],
    )
    (batch_row,) = _records(manifest, "discover-batch")
    assert "empty-batch" in batch_row["reason"]


# --- AC7: consecutive arXiv calls honor the ~3 s etiquette; nothing else waits ---


def test_consecutive_arxiv_calls_are_spaced_by_the_etiquette_interval(tmp_path: Path):
    from paper_degist.discover import ARXIV_MIN_INTERVAL

    waits: list[float] = []
    _run(
        tmp_path,
        ["hardware-aware attention kernels", "fused softmax implementations"],
        {"arxiv": _recording_search([_candidate()])},
        pause=waits.append,
    )
    assert waits == [ARXIV_MIN_INTERVAL]


def test_first_call_to_a_source_never_waits(tmp_path: Path):
    # US38 AC5: no wait before the *first* call to a source (openalex, one query).
    waits: list[float] = []
    _run(
        tmp_path,
        ["sparse autoencoder interpretability"],
        {"openalex": _recording_search([_candidate(source="openalex")])},
        pause=waits.append,
    )
    assert waits == []


# --- US38 AC5: every keyless source is paced, not only arXiv ---


def test_consecutive_openalex_calls_are_spaced_by_its_interval(tmp_path: Path):
    from paper_degist.discover import OPENALEX_MIN_INTERVAL

    waits: list[float] = []
    _run(
        tmp_path,
        ["dictionary learning features", "monosemantic neuron probes"],
        {"openalex": _recording_search([_candidate(source="openalex")])},
        pause=waits.append,
    )
    assert waits == [OPENALEX_MIN_INTERVAL]


def test_consecutive_s2_calls_are_spaced_by_its_interval(tmp_path: Path):
    from paper_degist.discover import S2_MIN_INTERVAL

    waits: list[float] = []
    _run(
        tmp_path,
        ["chain of thought faithfulness", "process reward models"],
        {"s2": _recording_search([_candidate(source="s2")])},
        pause=waits.append,
    )
    assert waits == [S2_MIN_INTERVAL]
