"""Unit tests for US25 discover (pytest).

One assertion per test (rule 05): each test fails for exactly one reason. The
real HTTP adapters are injected as a ``registry`` of fake ``Search`` callables so
these stay fast and offline (rule 01) — the live arXiv/S2 calls are exercised in
the real E2E run (rule 06 §7), not here. The pure parsers are tested against
captured Atom/JSON fixtures. Distinct example queries/papers per case (rule 08)
label what each exercises.
"""

import json
from pathlib import Path

import pytest

from paper_degist.discover import (
    Candidate,
    discover,
    parse_arxiv_atom,
    parse_openalex_json,
    parse_s2_json,
    reconstruct_abstract,
)

SAMPLES = Path(__file__).parent / "samples"


# --- OpenAlex abstract_inverted_index reconstruction (US29 AC2, rule 02) ---


def test_reconstruct_orders_tokens_by_position():
    # OpenAlex ships {token: [positions]}, not plain text; reconstruction orders
    # each token by its position so the abstract reads in its original order.
    index = {"Graph": [0], "neural": [1], "networks": [2], "predict": [3]}
    assert reconstruct_abstract(index) == "Graph neural networks predict"


def test_reconstruct_places_a_repeated_token_at_each_position():
    # A token that recurs carries a position list with more than one index;
    # every occurrence must land, not just the first.
    index = {"the": [0, 2], "graph": [1], "model": [3]}
    assert reconstruct_abstract(index) == "the graph the model"


def test_reconstruct_null_index_is_none():
    # A work with no abstract carries a null inverted index (AC5) → None, so the
    # record is kept and flagged abstract_present false rather than dropped.
    assert reconstruct_abstract(None) is None


# --- arXiv Atom parser: map the feed into the common schema (AC1) ---


def _arxiv_feed() -> str:
    return (SAMPLES / "arxiv-switch-transformers.atom.xml").read_text(encoding="utf-8")


def test_arxiv_parses_one_candidate_per_entry():
    assert len(parse_arxiv_atom(_arxiv_feed())) == 2


def test_arxiv_collapses_the_newline_wrapped_title():
    first = parse_arxiv_atom(_arxiv_feed())[0]
    assert first.title == (
        "Switch Transformers: Scaling to Trillion Parameter Models "
        "with Simple and Efficient Sparsity"
    )


def test_arxiv_extracts_the_abstract():
    first = parse_arxiv_atom(_arxiv_feed())[0]
    assert first.abstract.startswith("In deep learning, models typically reuse")


def test_arxiv_extracts_all_authors():
    first = parse_arxiv_atom(_arxiv_feed())[0]
    assert first.authors == ["William Fedus", "Barret Zoph", "Noam Shazeer"]


def test_arxiv_uses_the_alternate_link_as_the_url():
    first = parse_arxiv_atom(_arxiv_feed())[0]
    assert first.url == "http://arxiv.org/abs/2101.03961v1"


def test_arxiv_extracts_the_published_date():
    first = parse_arxiv_atom(_arxiv_feed())[0]
    assert first.published == "2021-01-11T18:41:03Z"


def test_arxiv_source_id_is_the_bare_arxiv_id():
    first = parse_arxiv_atom(_arxiv_feed())[0]
    assert first.source_id == "2101.03961v1"


def test_arxiv_tags_the_source():
    first = parse_arxiv_atom(_arxiv_feed())[0]
    assert first.source == "arxiv"


def test_arxiv_empty_feed_yields_no_candidates():
    empty = (SAMPLES / "arxiv-empty.atom.xml").read_text(encoding="utf-8")
    assert parse_arxiv_atom(empty) == []


# --- arXiv robustness: a structurally broken entry is skipped, not emitted ---


def _arxiv_feed_with(entries: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom">' + entries + "</feed>"
    )


def test_arxiv_skips_an_entry_with_no_id():
    # An arXiv paper without its <id> (its primary key) is a malformed feed
    # entry with no url/source_id — skip it rather than emit an unfetchable junk
    # record. A well-formed sibling entry is still returned.
    feed = _arxiv_feed_with(
        "<entry><title>No id here</title><summary>orphan</summary></entry>"
        "<entry><id>http://arxiv.org/abs/2401.00001v1</id>"
        "<title>Has an id</title><summary>ok</summary></entry>"
    )
    ids = [c.source_id for c in parse_arxiv_atom(feed)]
    assert ids == ["2401.00001v1"]


# --- OpenAlex JSON parser: common schema + reconstructed abstract, pdf_url ---


def _openalex_data() -> dict:
    return json.loads((SAMPLES / "openalex-molecular-gnn.json").read_text(encoding="utf-8"))


def test_openalex_parses_one_candidate_per_result():
    assert len(parse_openalex_json(_openalex_data())) == 2


def test_openalex_reconstructs_the_abstract_from_the_inverted_index():
    first = parse_openalex_json(_openalex_data())[0]
    assert first.abstract.startswith("Supervised learning on molecules has incredible")


def test_openalex_extracts_author_display_names():
    first = parse_openalex_json(_openalex_data())[0]
    assert first.authors == [
        "Justin Gilmer",
        "Samuel S. Schoenholz",
        "Patrick Riley",
        "Oriol Vinyals",
        "George E. Dahl",
    ]


def test_openalex_source_id_is_the_bare_work_id():
    first = parse_openalex_json(_openalex_data())[0]
    assert first.source_id == "W2606780347"


def test_openalex_doi_is_stripped_to_the_bare_doi():
    first = parse_openalex_json(_openalex_data())[0]
    assert first.doi == "10.48550/arxiv.1704.01212"


def test_openalex_tags_the_source():
    first = parse_openalex_json(_openalex_data())[0]
    assert first.source == "openalex"


def test_openalex_extracts_the_cited_by_count():
    first = parse_openalex_json(_openalex_data())[0]
    assert first.cited_by == 3010


# --- AC3: an OA pdf_url is carried when present, absent otherwise ---


def test_openalex_carries_the_oa_pdf_url_when_present():
    first = parse_openalex_json(_openalex_data())[0]
    assert first.pdf_url == "https://arxiv.org/pdf/1704.01212"


def test_openalex_pdf_url_is_none_when_no_oa_copy():
    # The second gnn record is OA-indexed but carries no direct pdf_url — it is
    # still emitted (AC3), just without a fetchable PDF link.
    second = parse_openalex_json(_openalex_data())[1]
    assert second.pdf_url is None


def test_openalex_pdf_url_record_omits_it_when_absent():
    second = parse_openalex_json(_openalex_data())[1]
    assert "pdf_url" not in second.to_record()


def test_openalex_pdf_url_record_includes_it_when_present():
    first = parse_openalex_json(_openalex_data())[0]
    assert first.to_record()["pdf_url"] == "https://arxiv.org/pdf/1704.01212"


# --- AC5: a null inverted index → kept, flagged abstract_present false ---


def test_openalex_null_abstract_index_stays_none():
    # A work whose abstract_inverted_index is null is kept (title + DOI still
    # feed the chain), not dropped.
    data = {"results": [{"id": "https://openalex.org/W123", "doi": "https://doi.org/10.1/x", "title": "No abstract", "abstract_inverted_index": None}]}
    assert parse_openalex_json(data)[0].abstract is None


def test_openalex_null_abstract_record_flags_abstract_present_false():
    data = {"results": [{"id": "https://openalex.org/W123", "title": "No abstract", "abstract_inverted_index": None}]}
    assert parse_openalex_json(data)[0].to_record()["abstract_present"] is False


# --- OpenAlex robustness: a result with no identity is skipped ---


def test_openalex_skips_a_result_with_no_identity():
    # No id, no doi → unfetchable, undedupable junk; skipped like arXiv/S2. A
    # well-formed sibling still comes through.
    data = {"results": [{"title": "Nameless"}, {"id": "https://openalex.org/W9", "title": "Has id"}]}
    ids = [c.source_id for c in parse_openalex_json(data)]
    assert ids == ["W9"]


# --- Semantic Scholar JSON parser: same schema, plus tldr + doi (AC2) ---


def _s2_data() -> dict:
    return json.loads((SAMPLES / "s2-crispr-base-editing.json").read_text(encoding="utf-8"))


def test_s2_parses_one_candidate_per_record():
    assert len(parse_s2_json(_s2_data())) == 2


def test_s2_extracts_the_title():
    first = parse_s2_json(_s2_data())[0]
    assert first.title.startswith("Programmable base editing of A")


def test_s2_extracts_author_names():
    first = parse_s2_json(_s2_data())[0]
    assert first.authors == ["Nicole M. Gaudelli", "Alexis C. Komor", "David R. Liu"]


def test_s2_extracts_the_doi_from_external_ids():
    first = parse_s2_json(_s2_data())[0]
    assert first.doi == "10.1038/nature24644"


def test_s2_extracts_the_tldr_text_when_present():
    first = parse_s2_json(_s2_data())[0]
    assert first.tldr.startswith("Adenine base editors are described")


def test_s2_tags_the_source():
    first = parse_s2_json(_s2_data())[0]
    assert first.source == "s2"


def test_s2_source_id_is_the_paper_id():
    first = parse_s2_json(_s2_data())[0]
    assert first.source_id == "0b3f2c1d4e5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c"


# --- S2 robustness: tolerate partial/null nested items, synthesize identity ---


def test_s2_tolerates_a_null_author_item():
    # A partial S2 response with a null (or non-object) author item must not
    # crash the parser; the good author names still come through.
    data = {"data": [{"paperId": "p1", "url": "https://s2/p1", "authors": [None, {"name": "Jane Roe"}]}]}
    assert parse_s2_json(data)[0].authors == ["Jane Roe"]


def test_s2_synthesizes_the_url_from_paper_id_when_missing():
    # S2's paper URL is deterministic from the paperId, so a record missing the
    # url field is repaired rather than emitted with an empty, unfetchable url.
    data = {"data": [{"paperId": "abc123", "title": "No url field"}]}
    assert parse_s2_json(data)[0].url == "https://www.semanticscholar.org/paper/abc123"


def test_s2_skips_a_record_with_no_identity():
    # A record with no paperId, no url, and no DOI cannot be fetched or deduped —
    # it is structurally unidentifiable junk, dropped by the parser (not a
    # relevance filter, which is US26's job).
    data = {"data": [{"title": "Nameless, unfetchable, undedupable"}]}
    assert parse_s2_json(data) == []


# --- AC3: a record with no abstract is kept, flagged, not dropped ---


def test_s2_missing_abstract_stays_none():
    second = parse_s2_json(_s2_data())[1]
    assert second.abstract is None


def test_missing_abstract_record_flags_abstract_present_false():
    second = parse_s2_json(_s2_data())[1]
    assert second.to_record()["abstract_present"] is False


def test_present_abstract_record_flags_abstract_present_true():
    first = parse_s2_json(_s2_data())[0]
    assert first.to_record()["abstract_present"] is True


# --- to_record: emit optional fields only when carried ---


def test_record_omits_doi_when_absent():
    candidate = Candidate(
        title="No DOI here",
        authors=["A. Author"],
        abstract="An abstract.",
        url="http://arxiv.org/abs/2101.03961v1",
        published="2021-01-11T18:41:03Z",
        source="arxiv",
        source_id="2101.03961v1",
    )
    assert "doi" not in candidate.to_record()


def test_record_omits_tldr_when_absent():
    second = parse_s2_json(_s2_data())[1]
    assert "tldr" not in second.to_record()


def test_record_includes_tldr_when_present():
    first = parse_s2_json(_s2_data())[0]
    assert "tldr" in first.to_record()


# --- orchestrator: shared arrange/act (rule 05 — factor setup into helpers) ---


def _one_candidate(source="arxiv") -> Candidate:
    return Candidate(
        title="Switch Transformers",
        authors=["William Fedus"],
        abstract="Mixture of Experts models route tokens sparsely.",
        url="http://arxiv.org/abs/2101.03961v1",
        published="2021-01-11T18:41:03Z",
        source=source,
        source_id="2101.03961v1",
    )


def _hits_search(candidates):
    """A Search that returns the given candidates; records the query it saw."""

    def search(query):
        search.queries.append(query)
        return list(candidates)

    search.queries = []
    return search


def _empty_search():
    """A Search that returns no candidates (a zero-result query)."""

    def search(query):
        return []

    return search


def _error_search(exc=None):
    """A Search that raises — an API error / rate-limit."""

    def search(query):
        raise exc or RuntimeError("HTTP 429 Too Many Requests")

    return search


def _boom_search():
    """A Search that raises if called — proves the network was not touched."""

    def search(query):
        raise AssertionError("network must not be touched")

    return search


def _run(tmp_path: Path, *, query="sparse mixture-of-experts routing", source="arxiv", search=None):
    """Run discover with a one-source registry backed by the given fake Search."""
    manifest = tmp_path / "manifest.jsonl"
    registry = {source if search else "arxiv": search or _hits_search([_one_candidate()])}
    result = discover(query, source, manifest_path=manifest, registry=registry)
    return result, manifest


def _only_record(manifest: Path) -> dict:
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


# --- happy path: emit one record per hit + a discover success record (AC1) ---


def test_hits_return_one_record_per_candidate(tmp_path: Path):
    search = _hits_search([_one_candidate(), _one_candidate()])
    result, _ = _run(tmp_path, search=search)
    assert len(result) == 2


def test_hits_emit_the_common_schema_record(tmp_path: Path):
    result, _ = _run(tmp_path, search=_hits_search([_one_candidate()]))
    assert result[0]["title"] == "Switch Transformers"


def test_hits_pass_the_query_to_the_adapter(tmp_path: Path):
    search = _hits_search([_one_candidate()])
    _run(tmp_path, query="graph neural network expressivity", search=search)
    assert search.queries == ["graph neural network expressivity"]


def test_hits_manifest_records_discover_stage(tmp_path: Path):
    _, manifest = _run(tmp_path, search=_hits_search([_one_candidate()]))
    assert _only_record(manifest)["stage"] == "discover"


def test_hits_manifest_records_the_source(tmp_path: Path):
    _, manifest = _run(tmp_path, search=_hits_search([_one_candidate()]))
    assert _only_record(manifest)["source"] == "arxiv"


def test_hits_manifest_records_the_query(tmp_path: Path):
    _, manifest = _run(tmp_path, query="protein language models", search=_hits_search([_one_candidate()]))
    assert _only_record(manifest)["query"] == "protein language models"


def test_hits_manifest_records_the_result_count(tmp_path: Path):
    search = _hits_search([_one_candidate(), _one_candidate(), _one_candidate()])
    _, manifest = _run(tmp_path, search=search)
    assert _only_record(manifest)["result_count"] == 3


def test_hits_success_record_has_no_reason(tmp_path: Path):
    _, manifest = _run(tmp_path, search=_hits_search([_one_candidate()]))
    assert "reason" not in _only_record(manifest)


# --- AC5: an unknown source quarantines offline, without touching the network ---


def test_unknown_source_returns_none(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    result = discover("gene therapy", "pubmed", manifest_path=manifest, registry={"arxiv": _boom_search()})
    assert result is None


def test_unknown_source_does_not_touch_the_network(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    # A recording adapter under the *known* source: an unknown --source must never
    # reach it, so its recorded call list stays empty.
    known = _hits_search([_one_candidate()])
    discover("gene therapy", "pubmed", manifest_path=manifest, registry={"arxiv": known})
    assert known.queries == []


def test_unknown_source_reason_names_unknown_source(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    discover("gene therapy", "pubmed", manifest_path=manifest, registry={"arxiv": _boom_search()})
    assert "unknown source" in _only_record(manifest)["reason"]


def test_unknown_source_manifest_records_discover_stage(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    discover("gene therapy", "pubmed", manifest_path=manifest, registry={"arxiv": _boom_search()})
    assert _only_record(manifest)["stage"] == "discover"


# --- AC4: an empty result and an API error quarantine with DISTINCT reasons ---


def test_empty_result_returns_none(tmp_path: Path):
    result, _ = _run(tmp_path, search=_empty_search())
    assert result is None


def test_empty_result_reason_is_empty_result(tmp_path: Path):
    _, manifest = _run(tmp_path, search=_empty_search())
    assert "empty-result" in _only_record(manifest)["reason"]


def test_api_error_returns_none(tmp_path: Path):
    result, _ = _run(tmp_path, search=_error_search())
    assert result is None


def test_api_error_reason_is_api_error(tmp_path: Path):
    _, manifest = _run(tmp_path, search=_error_search())
    assert "api-error" in _only_record(manifest)["reason"]


def test_empty_and_api_error_reasons_are_distinct(tmp_path: Path):
    _, empty_manifest = _run(tmp_path, search=_empty_search())
    _, error_manifest = _run(tmp_path / "e", search=_error_search())
    assert _only_record(empty_manifest)["reason"] != _only_record(error_manifest)["reason"]


def test_api_error_does_not_crash_and_records_the_exception(tmp_path: Path):
    _, manifest = _run(tmp_path, search=_error_search(ValueError("bad gateway")))
    assert "bad gateway" in _only_record(manifest)["reason"]
