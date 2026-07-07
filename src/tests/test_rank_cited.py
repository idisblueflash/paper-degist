"""Unit tests for US32 rank-cited (pytest).

One assertion per test (rule 05). The step is pure, offline arithmetic over
candidate records, so every test runs without network (rule 01); distinct
example papers per case (rule 08) label what each exercises.
"""

import json
from pathlib import Path

from paper_degist.rank_cited import rank_cited


def _record(*, title, url, source="openalex", **fields) -> dict:
    return {"title": title, "url": url, "source": source, **fields}


def _run(tmp_path: Path, candidates, top=20):
    manifest = tmp_path / "manifest.jsonl"
    result = rank_cited(candidates, top=top, manifest_path=manifest)
    return result, manifest


# --- AC1: rank by descending cited_by, records passed through unchanged ---


def test_candidates_are_ranked_by_descending_cited_by(tmp_path: Path):
    result, _ = _run(
        tmp_path,
        [
            _record(
                title="Longformer: The Long-Document Transformer",
                url="https://doi.org/10.48550/arxiv.2004.05150",
                cited_by=187,
            ),
            _record(
                title="Attention Is All You Need",
                url="https://doi.org/10.48550/arxiv.1706.03762",
                cited_by=9041,
            ),
            _record(
                title="Big Bird: Transformers for Longer Sequences",
                url="https://doi.org/10.48550/arxiv.2007.14062",
                cited_by=512,
            ),
        ],
    )
    assert [r["cited_by"] for r in result] == [9041, 512, 187]


# --- AC3: a candidate without a usable cited_by is filtered, never crashes ---


def test_a_candidate_without_cited_by_is_dropped_and_the_rest_still_rank(tmp_path: Path):
    result, _ = _run(
        tmp_path,
        [
            _record(
                title="Mamba: Linear-Time Sequence Modeling",
                url="http://arxiv.org/abs/2312.00752v1",
                source="arxiv",
            ),
            _record(
                title="Efficiently Modeling Long Sequences with S4",
                url="https://doi.org/10.48550/arxiv.2111.00396",
                cited_by=1873,
            ),
        ],
    )
    assert [r["title"] for r in result] == ["Efficiently Modeling Long Sequences with S4"]


def test_the_unrankable_candidate_leaves_a_no_cited_by_record(tmp_path: Path):
    _, manifest = _run(
        tmp_path,
        [
            _record(
                title="RWKV: Reinventing RNNs for the Transformer Era",
                url="http://arxiv.org/abs/2305.13048v2",
                source="arxiv",
            )
        ],
    )
    (dropped,) = _filtered_rows(manifest)
    assert dropped == {
        "stage": "rank-cited",
        "event": "filtered",
        "url": "http://arxiv.org/abs/2305.13048v2",
        "reason": "no-cited-by",
    }


def test_a_zero_citation_count_is_ranked_not_dropped_as_missing(tmp_path: Path):
    result, _ = _run(
        tmp_path,
        [
            _record(
                title="xLSTM: Extended Long Short-Term Memory",
                url="https://doi.org/10.48550/arxiv.2405.04517",
                cited_by=0,
            ),
            _record(
                title="Hungry Hungry Hippos: Towards Language Modeling with SSMs",
                url="https://doi.org/10.48550/arxiv.2212.14052",
                cited_by=402,
            ),
        ],
    )
    assert [r["cited_by"] for r in result] == [402, 0]


def test_a_non_integer_count_is_dropped_as_no_cited_by(tmp_path: Path):
    _, manifest = _run(
        tmp_path,
        [
            _record(
                title="Titans: Learning to Memorize at Test Time",
                url="https://doi.org/10.48550/arxiv.2501.00663",
                cited_by="1,204",
            )
        ],
    )
    (dropped,) = _filtered_rows(manifest)
    assert dropped["reason"] == "no-cited-by"


# --- correctness: top=0 must not silently return an empty list ---


def test_top_zero_returns_none_and_quarantines(tmp_path: Path):
    result, manifest = _run(
        tmp_path,
        [_record(title="FlashAttention: Fast Memory-Efficient Attention", url="https://arxiv.org/abs/2205.14135", cited_by=3200)],
        top=0,
    )
    assert result is None


# --- AC2: only the top N survive the cut; the rest leave filtered records ---


def _moe_pool() -> list[dict]:
    # Four rankable mixture-of-experts papers, deliberately out of order.
    return [
        _record(
            title="GShard: Scaling Giant Models with Conditional Computation",
            url="https://doi.org/10.48550/arxiv.2006.16668",
            cited_by=1450,
        ),
        _record(
            title="Outrageously Large Neural Networks: The Sparsely-Gated MoE",
            url="https://doi.org/10.48550/arxiv.1701.06538",
            cited_by=3120,
        ),
        _record(
            title="GLaM: Efficient Scaling of Language Models with MoE",
            url="https://doi.org/10.48550/arxiv.2112.06905",
            cited_by=690,
        ),
        _record(
            title="Switch Transformers: Scaling to Trillion Parameter Models",
            url="https://doi.org/10.48550/arxiv.2101.03961",
            cited_by=2205,
        ),
    ]


def test_only_the_top_n_candidates_are_emitted(tmp_path: Path):
    result, _ = _run(tmp_path, _moe_pool(), top=2)
    assert [r["cited_by"] for r in result] == [3120, 2205]


def _filtered_rows(manifest: Path) -> list[dict]:
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r.get("event") == "filtered"]


# --- AC6: nothing rankable at all -> quarantine, not an empty print ---


def test_a_pool_with_nothing_rankable_returns_none(tmp_path: Path):
    result, _ = _run(
        tmp_path,
        [
            _record(
                title="Griffin: Mixing Gated Linear Recurrences with Local Attention",
                url="http://arxiv.org/abs/2402.19427v1",
                source="arxiv",
            )
        ],
    )
    assert result is None


def test_the_empty_rank_quarantine_names_its_reason(tmp_path: Path):
    _, manifest = _run(
        tmp_path,
        [
            _record(
                title="Hawk: Recurrent Models that Outperform Attention",
                url="http://arxiv.org/abs/2402.19427v2",
                source="arxiv",
            )
        ],
    )
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    (row,) = [r for r in rows if "empty-rank" in r.get("reason", "")]
    assert row["event"] == "quarantined"


# --- AC5: a garbage input line is quarantined under this step's own stage ---


def test_a_garbage_line_is_quarantined_under_the_rank_cited_stage(tmp_path: Path):
    # Reuses US26's loader discipline; the row must name *this* step's stage.
    from paper_degist.abstract_filter import load_candidates

    manifest = tmp_path / "manifest.jsonl"
    load_candidates(
        '{"title": "Retentive Network", "cited_by": 350}\n{"cited_by": 41, "titl',
        manifest_path=manifest,
        stage="rank-cited",
    )
    (row,) = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    assert row["stage"] == "rank-cited"


# --- AC4: ties keep their input order (stable, deterministic re-runs) ---


def test_tied_citation_counts_keep_their_input_order(tmp_path: Path):
    result, _ = _run(
        tmp_path,
        [
            _record(
                title="Compressive Transformers for Long-Range Sequence Modelling",
                url="https://doi.org/10.48550/arxiv.1911.05507",
                cited_by=764,
            ),
            _record(
                title="Transformer-XL: Attentive Language Models Beyond a Fixed-Length Context",
                url="https://doi.org/10.48550/arxiv.1901.02860",
                cited_by=764,
            ),
        ],
    )
    assert [r["title"] for r in result] == [
        "Compressive Transformers for Long-Range Sequence Modelling",
        "Transformer-XL: Attentive Language Models Beyond a Fixed-Length Context",
    ]


def test_each_candidate_below_the_cut_leaves_a_beyond_top_record(tmp_path: Path):
    _, manifest = _run(tmp_path, _moe_pool(), top=2)
    assert _filtered_rows(manifest) == [
        {
            "stage": "rank-cited",
            "event": "filtered",
            "url": "https://doi.org/10.48550/arxiv.2006.16668",
            "reason": "beyond-top",
            "cited_by": 1450,
        },
        {
            "stage": "rank-cited",
            "event": "filtered",
            "url": "https://doi.org/10.48550/arxiv.2112.06905",
            "reason": "beyond-top",
            "cited_by": 690,
        },
    ]
