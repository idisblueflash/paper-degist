"""Unit tests for US26 abstract_filter (pytest).

One assertion per test (rule 05): each test fails for exactly one reason. The
flaky embedding transport is injected as ``embed`` (a ``(text, role) -> vector``
callable) so these stay fast and offline (rule 01) — the real curl-to-LM-Studio
transport is exercised end-to-end (rule 06 §7), not here. The two passes are
tested apart: the deterministic dedup/no-abstract dispatch, then the
embedding-similarity keep/drop/rank, then the per-candidate quarantine.
Distinct example titles/DOIs/abstracts per case (rule 08) label what each covers.
"""

import json
from pathlib import Path

from paper_degist.abstract_filter import (
    DEFAULT_THRESHOLD,
    abstract_filter,
    candidate_doi_key,
    cosine,
    load_candidates,
    make_embedder,
)

TOPIC = "contrastive learning for speech representations"


# --- fixtures: a candidate record and an injected embedder -------------------


def _cand(url, *, abstract="on-topic speech abstract", abstract_present=True, doi=None, title="A paper"):
    """One discover-schema candidate record (rule 08 — vary url/title per case)."""
    record = {
        "title": title,
        "authors": [],
        "abstract": abstract,
        "abstract_present": abstract_present,
        "url": url,
        "published": None,
        "source": "arxiv",
        "source_id": url,
    }
    if doi is not None:
        record["doi"] = doi
    return record


def _embed(doc_vectors=None, *, query=(1.0, 0.0)):
    """An injected embedder: topic → ``query``; each abstract → its mapped vector.

    ``doc_vectors`` maps an abstract string to a 2-D vector (or ``None`` to
    simulate an embed-text quarantine). An unmapped abstract defaults to the
    query direction (cosine 1.0 — clearly on-topic). Records its calls so a test
    can assert the query is embedded once and dropped candidates never reach it.
    """
    doc_vectors = doc_vectors or {}

    def embed(text, role):
        embed.calls.append((text, role))
        if role == "query":
            return list(query)
        vec = doc_vectors.get(text, (1.0, 0.0))
        return list(vec) if vec is not None else None

    embed.calls = []
    return embed


def _run(tmp_path, candidates, *, embed=None, threshold=0.65):
    manifest = tmp_path / "manifest.jsonl"
    embed = embed if embed is not None else _embed()
    kept = abstract_filter(candidates, TOPIC, embed=embed, threshold=threshold, manifest_path=manifest)
    return kept, manifest


def _records(manifest: Path):
    if not manifest.exists():
        return []
    return [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]


def _record_with(manifest: Path, reason: str) -> dict:
    (record,) = [r for r in _records(manifest) if r.get("reason", "").startswith(reason)]
    return record


# --- cosine (pure) -----------------------------------------------------------


def test_cosine_of_identical_directions_is_one():
    assert cosine([2.0, 0.0], [5.0, 0.0]) == 1.0


def test_cosine_of_orthogonal_vectors_is_zero():
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_of_a_zero_vector_is_zero_not_a_crash():
    # A zero vector has no direction; guard the div-by-zero rather than crash.
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_of_mismatched_lengths_is_zero():
    # Different dimensions are not comparable; return 0 rather than let zip()
    # truncate the dot product and score a false near-match (Codex finding).
    assert cosine([1.0, 0.0], [1.0, 0.0, 0.0]) == 0.0


def test_cosine_of_a_non_finite_component_is_zero():
    # A NaN in a vector must not yield similarity NaN (invalid JSON downstream);
    # a non-finite result folds to 0.0 → dropped as off-topic (Codex finding).
    assert cosine([float("nan"), 0.0], [1.0, 0.0]) == 0.0


# --- candidate_doi_key (pure): the normalized dedup key ----------------------


def test_key_reads_the_explicit_doi_field_lowercased():
    assert candidate_doi_key({"doi": "10.1109/CVPR.2016.90"}) == "10.1109/cvpr.2016.90"


def test_key_falls_back_to_a_doi_embedded_in_the_url():
    record = {"url": "https://doi.org/10.1016/j.learninstruc.2007.02.008"}
    assert candidate_doi_key(record) == "10.1016/j.learninstruc.2007.02.008"


def test_key_is_none_when_no_doi_anywhere():
    assert candidate_doi_key({"url": "http://arxiv.org/abs/2101.03961v1"}) is None


# --- pass 1 (deterministic): no-abstract drop, before any embedding (AC1) ----


def test_no_abstract_candidate_is_not_in_the_output(tmp_path):
    kept, _ = _run(tmp_path, [_cand("u/no-abs", abstract=None, abstract_present=False)])
    assert kept == []


def test_no_abstract_drop_records_reason_no_abstract(tmp_path):
    _, manifest = _run(tmp_path, [_cand("u/no-abs", abstract=None, abstract_present=False)])
    assert _record_with(manifest, "no-abstract")["stage"] == "abstract-filter"


def test_present_flag_true_but_empty_abstract_is_treated_as_no_abstract(tmp_path):
    # A record whose flag lies (present=true, abstract empty) must be dropped as
    # no-abstract, never reach embed(None) and crash (rule 02: never crash).
    kept, _ = _run(tmp_path, [_cand("u/liar", abstract="   ", abstract_present=True)])
    assert kept == []


def test_non_string_abstract_is_treated_as_no_abstract(tmp_path):
    # A malformed source could carry abstract as a list/number; it must drop as
    # no-abstract, never pass a non-str into embed() and crash (Codex finding).
    weird = _cand("u/weird", abstract=["not", "a", "string"], abstract_present=True)
    kept, _ = _run(tmp_path, [weird])
    assert kept == []


def test_no_abstract_candidate_never_reaches_the_embedder(tmp_path):
    # AC1: the abstract-less candidate is dropped *before any embedding call*.
    embed = _embed()
    _run(tmp_path, [_cand("u/no-abs", abstract=None, abstract_present=False)], embed=embed)
    assert all(role != "document" for _, role in embed.calls)


# --- pass 1 (deterministic): dedup by normalized DOI, before embedding (AC1) -


def test_duplicate_doi_candidate_is_not_in_the_output(tmp_path):
    doi = "10.1038/nature24644"
    first = _cand("u/first", doi=doi, title="First sight")
    dup = _cand("u/dup", doi="https://doi.org/10.1038/NATURE24644", title="Same DOI, different link")
    kept, _ = _run(tmp_path, [first, dup])
    assert [k["url"] for k in kept] == ["u/first"]


def test_duplicate_doi_drop_records_reason_dedup_doi(tmp_path):
    doi = "10.1038/nature24644"
    _, manifest = _run(tmp_path, [_cand("u/first", doi=doi), _cand("u/dup", doi=doi)])
    assert _record_with(manifest, "dedup-doi")["url"] == "u/dup"


def test_duplicate_doi_drop_records_the_kept_original(tmp_path):
    doi = "10.1038/nature24644"
    _, manifest = _run(tmp_path, [_cand("u/first", doi=doi), _cand("u/dup", doi=doi)])
    assert _record_with(manifest, "dedup-doi")["duplicate_of"] == "u/first"


def test_duplicate_doi_candidate_never_reaches_the_embedder(tmp_path):
    doi = "10.1038/nature24644"
    embed = _embed()
    _run(tmp_path, [_cand("u/first", doi=doi), _cand("u/dup", doi=doi)], embed=embed)
    # Only the surviving original's abstract is embedded, not the duplicate's.
    assert sum(1 for _, role in embed.calls if role == "document") == 1


def test_doi_less_candidates_are_never_deduped(tmp_path):
    # arXiv candidates carry no DOI, so they cannot be deduped offline (like US14).
    a = _cand("http://arxiv.org/abs/2101.03961v1")
    b = _cand("http://arxiv.org/abs/2202.02222v1")
    kept, _ = _run(tmp_path, [a, b])
    assert len(kept) == 2


# --- pass 2 (embedding): keep on-topic with its similarity attached (AC2) ----


def test_on_topic_candidate_is_kept(tmp_path):
    kept, _ = _run(tmp_path, [_cand("u/on", abstract="speech contrastive")])
    assert [k["url"] for k in kept] == ["u/on"]


def test_kept_candidate_carries_its_similarity_score(tmp_path):
    kept, _ = _run(tmp_path, [_cand("u/on", abstract="speech contrastive")])
    assert kept[0]["similarity"] == 1.0


def test_the_topic_query_is_embedded_exactly_once(tmp_path):
    embed = _embed()
    _run(tmp_path, [_cand("u/a"), _cand("u/b", abstract="another on-topic abstract")], embed=embed)
    assert sum(1 for _, role in embed.calls if role == "query") == 1


def test_the_topic_is_embedded_with_the_query_role(tmp_path):
    embed = _embed()
    _run(tmp_path, [_cand("u/a")], embed=embed)
    assert (TOPIC, "query") in embed.calls


# --- pass 2 (embedding): drop below-threshold, auditable (AC3) ---------------


def test_below_threshold_candidate_is_not_in_the_output(tmp_path):
    off = _cand("u/off", abstract="unrelated crispr abstract")
    kept, _ = _run(tmp_path, [off], embed=_embed({"unrelated crispr abstract": (0.0, 1.0)}))
    assert kept == []


def test_below_threshold_drop_records_reason_below_threshold(tmp_path):
    off = _cand("u/off", abstract="unrelated crispr abstract")
    _, manifest = _run(tmp_path, [off], embed=_embed({"unrelated crispr abstract": (0.0, 1.0)}))
    assert _record_with(manifest, "below-threshold")["url"] == "u/off"


def test_below_threshold_drop_records_the_similarity_score(tmp_path):
    off = _cand("u/off", abstract="unrelated crispr abstract")
    _, manifest = _run(tmp_path, [off], embed=_embed({"unrelated crispr abstract": (0.0, 1.0)}))
    assert _record_with(manifest, "below-threshold")["similarity"] == 0.0


def test_at_the_threshold_the_candidate_is_kept(tmp_path):
    # AC2/AC3 boundary: cosine == threshold is a keep (≥), not a drop (<).
    edge = _cand("u/edge", abstract="edge abstract")
    kept, _ = _run(tmp_path, [edge], embed=_embed({"edge abstract": (0.65, 0.7599)}), threshold=0.65)
    # (0.65, 0.7599) · (1,0) / |v| ≈ 0.650 — right at the cut.
    assert kept and kept[0]["url"] == "u/edge"


# --- ranking: descending similarity (AC4) ------------------------------------


def test_output_is_ranked_by_descending_similarity(tmp_path):
    near = _cand("u/near", abstract="near abstract")   # cosine ~0.9965
    far = _cand("u/far", abstract="far abstract")      # cosine ~0.7071
    embed = _embed({"near abstract": (10.0, 0.837), "far abstract": (1.0, 1.0)})
    kept, _ = _run(tmp_path, [far, near], embed=embed)
    assert [k["url"] for k in kept] == ["u/near", "u/far"]


# --- resilience: one embed quarantine does not sink the batch (AC5) ----------


def test_embed_unavailable_candidate_is_not_in_the_output(tmp_path):
    down = _cand("u/down", abstract="server-down abstract")
    ok = _cand("u/ok", abstract="reachable abstract")
    embed = _embed({"server-down abstract": None})
    kept, _ = _run(tmp_path, [down, ok], embed=embed)
    assert [k["url"] for k in kept] == ["u/ok"]


def test_embed_unavailable_candidate_is_quarantined_with_a_naming_reason(tmp_path):
    down = _cand("u/down", abstract="server-down abstract")
    _, manifest = _run(tmp_path, [down], embed=_embed({"server-down abstract": None}))
    assert "embed-unavailable" in _record_with(manifest, "embed-unavailable")["reason"]


def test_embed_unavailable_does_not_abort_the_batch(tmp_path):
    # AC5: the reachable candidate after the failed one is still scored and kept.
    down = _cand("u/down", abstract="server-down abstract")
    ok = _cand("u/ok", abstract="reachable abstract")
    kept, _ = _run(tmp_path, [down, ok], embed=_embed({"server-down abstract": None}))
    assert kept[0]["similarity"] == 1.0


# --- manifest discriminator: a deliberate drop vs a failure ------------------


def test_a_filtered_drop_is_marked_event_filtered(tmp_path):
    _, manifest = _run(tmp_path, [_cand("u/no-abs", abstract=None, abstract_present=False)])
    assert _record_with(manifest, "no-abstract")["event"] == "filtered"


def test_an_embed_failure_is_marked_event_quarantined(tmp_path):
    down = _cand("u/down", abstract="server-down abstract")
    _, manifest = _run(tmp_path, [down], embed=_embed({"server-down abstract": None}))
    assert _record_with(manifest, "embed-unavailable")["event"] == "quarantined"


# --- topic-embed failure: no shortlist, recorded, never crash ----------------


def test_topic_embed_failure_returns_an_empty_shortlist(tmp_path):
    def embed(text, role):
        return None  # the server is down even for the one-off query embed

    kept, _ = _run(tmp_path, [_cand("u/a")], embed=embed)
    assert kept == []


def test_topic_embed_failure_is_recorded(tmp_path):
    def embed(text, role):
        return None

    _, manifest = _run(tmp_path, [_cand("u/a")], embed=embed)
    assert "embed-unavailable" in _record_with(manifest, "embed-unavailable")["reason"]


# --- load_candidates: a malformed pipe line quarantines, never crashes (rule 02) ---


def test_load_candidates_parses_object_lines(tmp_path):
    text = '{"url": "u/a"}\n{"url": "u/b"}\n'
    cands = load_candidates(text, manifest_path=tmp_path / "m.jsonl")
    assert [c["url"] for c in cands] == ["u/a", "u/b"]


def test_load_candidates_skips_a_truncated_line(tmp_path):
    # An interrupted `discover` can leave a truncated final line; keep the rest.
    text = '{"url": "u/ok"}\n{"url": "u/trunc", "abst'
    cands = load_candidates(text, manifest_path=tmp_path / "m.jsonl")
    assert [c["url"] for c in cands] == ["u/ok"]


def test_load_candidates_quarantines_a_truncated_line(tmp_path):
    manifest = tmp_path / "m.jsonl"
    load_candidates('{"url": "u/trunc", "abst', manifest_path=manifest)
    assert "unparseable candidate line" in _record_with(manifest, "unparseable")["reason"]


def test_load_candidates_skips_a_non_object_line(tmp_path):
    # A well-formed JSON scalar/array is not a candidate record — skip it rather
    # than let `candidate.get(...)` AttributeError downstream.
    text = '{"url": "u/ok"}\n42\n'
    cands = load_candidates(text, manifest_path=tmp_path / "m.jsonl")
    assert [c["url"] for c in cands] == ["u/ok"]


def test_load_candidates_records_the_offending_line(tmp_path):
    # The manifest is the queue of unknown cases; capture the raw bad line so a
    # human can see what failed, not just the parser's message (Codex finding).
    manifest = tmp_path / "m.jsonl"
    load_candidates('{"url": "u/trunc", "abst', manifest_path=manifest)
    assert _record_with(manifest, "unparseable")["line"] == '{"url": "u/trunc", "abst'


# --- make_embedder: a corrupt cached vector quarantines, never crashes (rule 02) ---


def test_make_embedder_returns_none_on_a_corrupt_cache_file(tmp_path, monkeypatch):
    # embed_text saves atomically, but an externally-corrupted/edited cache file
    # must not crash the batch — read failure surfaces as None → quarantine.
    corrupt = tmp_path / "vec.json"
    corrupt.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr("paper_degist.abstract_filter.embed_text", lambda *a, **k: corrupt)
    embed = make_embedder(out_dir=tmp_path, manifest_path=tmp_path / "m.jsonl")
    assert embed("some abstract", "document") is None


# --- the calibrated constant is the measured value ---------------------------


def test_default_threshold_is_the_measured_constant():
    assert DEFAULT_THRESHOLD == 0.65
