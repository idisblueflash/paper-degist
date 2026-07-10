import json
import tempfile
from pathlib import Path

from behave import given, then, when
from typer.testing import CliRunner

import paper_degist.discover as discover_mod
from paper_degist.discover import (
    Candidate,
    _build_registry,
    discover,
    parse_openalex_json,
    parse_serpapi_scholar,
    parse_serpapi_scholar_author,
)
from paper_degist.discover import app as discover_app


def _root(context):
    """A temp root holding manifest.jsonl for the scenario."""
    if not getattr(context, "root", None):
        context.root = Path(tempfile.mkdtemp())
    return context.root


def _candidate(source, *, abstract="Mixture of Experts models route tokens sparsely.", tldr=None):
    return Candidate(
        title="Switch Transformers",
        authors=["William Fedus", "Barret Zoph"],
        abstract=abstract,
        url="http://arxiv.org/abs/2101.03961v1",
        published="2021-01-11T18:41:03Z",
        source=source,
        source_id="2101.03961v1",
        tldr=tldr,
    )


def _recording_search(context, *, candidates=None, error=None):
    """A stand-in Search that records its calls (so we can assert contact)."""
    context.searched = []

    def search(query):
        context.searched.append(query)
        if error is not None:
            raise error
        return list(candidates or [])

    return search


@given('a topic query "{query}"')
def step_query(context, query):
    context.query = query


@given('an "{source}" source that returns {count:d} candidates')
def step_source_hits(context, source, count):
    context.registry = {source: _recording_search(context, candidates=[_candidate(source)] * count)}


@given('an "{source}" source whose candidate carries a tldr "{tldr}"')
def step_source_tldr(context, source, tldr):
    context.registry = {source: _recording_search(context, candidates=[_candidate(source, tldr=tldr)])}


@given('an "{source}" source whose candidate has no abstract')
def step_source_no_abstract(context, source):
    context.registry = {source: _recording_search(context, candidates=[_candidate(source, abstract=None)])}


@given('an "{source}" source that returns no candidates')
def step_source_empty(context, source):
    context.registry = {source: _recording_search(context, candidates=[])}


@given('an "{source}" source that errors')
def step_source_errors(context, source):
    # A hard, opaque API/network failure (not a typed 429) → immediate api-error.
    error = RuntimeError("HTTP 500 Internal Server Error")
    context.registry = {source: _recording_search(context, error=error)}


@given('an "{source}" source that always rate-limits')
def step_source_always_rate_limited(context, source):
    # A typed 429 on every attempt (US38): discover retries, then exhausts.
    from paper_degist.discover import RateLimited

    context.registry = {source: _recording_search(context, error=RateLimited())}


@given('an "{source}" source that rate-limits once then returns {count:d} candidates')
def step_source_rate_limited_once(context, source, count):
    # A typed 429 on the first attempt, then hits (US38): the retry recovers.
    from paper_degist.discover import RateLimited

    context.searched = []
    hits = [_candidate(source)] * count

    def search(query):
        context.searched.append(query)
        if len(context.searched) == 1:
            raise RateLimited()
        return list(hits)

    context.registry = {source: search}


@given('an "{source}" work whose abstract arrives as an inverted index')
def step_openalex_inverted_index(context, source):
    # A raw OpenAlex Works response — the adapter reconstructs the abstract from
    # the {token: [positions]} map (US29 AC2), so parse it through the real parser.
    raw = {
        "results": [
            {
                "id": "https://openalex.org/W2606780347",
                "doi": "https://doi.org/10.48550/arxiv.1704.01212",
                "title": "Neural Message Passing for Quantum Chemistry",
                "abstract_inverted_index": {
                    "Graph": [0],
                    "neural": [1],
                    "networks": [2],
                    "predict": [3],
                    "molecular": [4],
                    "properties": [5],
                },
            }
        ]
    }
    candidates = parse_openalex_json(raw)
    context.registry = {source: _recording_search(context, candidates=candidates)}


@given('an "{source}" source whose candidate carries a pdf_url "{pdf_url}"')
def step_openalex_pdf_url(context, source, pdf_url):
    # Build a raw OpenAlex work whose best_oa_location has no pdf_url so the
    # adapter must take the oa_locations[] fallback (US29 AC3), then run it
    # through the real parser — this pins _openalex_pdf_url, not just to_record.
    raw = {
        "results": [
            {
                "id": "https://openalex.org/W2606780347",
                "doi": "https://doi.org/10.48550/arxiv.1704.01212",
                "title": "Neural Message Passing for Quantum Chemistry",
                "best_oa_location": {"pdf_url": None, "landing_page_url": "http://arxiv.org/abs/1704.01212"},
                "oa_locations": [{"pdf_url": pdf_url, "landing_page_url": "http://arxiv.org/abs/1704.01212"}],
            }
        ]
    }
    candidates = parse_openalex_json(raw)
    context.registry = {source: _recording_search(context, candidates=candidates)}


@when('discover runs the openalex CLI with no contact email')
def step_openalex_cli_no_email(context):
    # Exercise the real CLI path (where the missing-email warning lives), with a
    # stubbed registry so no network is touched. AC4: warn, do not quarantine.
    import os

    root = _root(context)
    context.searched = []

    def search(query):
        context.searched.append(query)
        return [_candidate("openalex")]

    os.environ.pop("OPENALEX_EMAIL", None)
    original_build_registry = discover_mod._build_registry
    discover_mod._build_registry = lambda mr, key, email, serp: {"openalex": search}
    try:
        context.cli_result = CliRunner().invoke(
            discover_app,
            [context.query, "--source", "openalex", "--manifest", str(root / "manifest.jsonl")],
        )
    finally:
        discover_mod._build_registry = original_build_registry


@then('the emitted record abstract reads "{abstract}"')
def step_record_abstract(context, abstract):
    assert context.result is not None, "expected records, got a quarantine"
    assert context.result[0]["abstract"] == abstract, context.result[0]["abstract"]


@then('the emitted record carries the pdf_url "{pdf_url}"')
def step_record_pdf_url(context, pdf_url):
    assert context.result is not None, "expected records, got a quarantine"
    assert context.result[0].get("pdf_url") == pdf_url, context.result[0].get("pdf_url")


@then('a polite-pool warning is emitted')
def step_polite_pool_warning(context):
    assert "polite pool" in context.cli_result.output, context.cli_result.output


@then('the openalex search is still run')
def step_openalex_search_run(context):
    # AC4: the missing email downgrades to the common pool, it does NOT block —
    # the adapter was actually called.
    assert context.searched, "the openalex adapter was not invoked"


@when('discover searches the "{source}" source')
def step_search(context, source):
    root = _root(context)
    context.manifest = root / "manifest.jsonl"
    # Default to an empty registry so an unknown source touches no adapter.
    registry = getattr(context, "registry", {})
    context.result = discover(context.query, source, manifest_path=context.manifest, registry=registry)


@when('discover searches the "{source}" source with a retry budget of {budget:d}')
def step_search_with_budget(context, source, budget):
    # US38: exercise the retry/backoff path with an injected no-op pause so the
    # scenario never really sleeps, and the given budget.
    root = _root(context)
    context.manifest = root / "manifest.jsonl"
    registry = getattr(context, "registry", {})
    context.result = discover(
        context.query,
        source,
        manifest_path=context.manifest,
        registry=registry,
        pause=lambda _seconds: None,
        max_retries=budget,
    )


@then("{count:d} candidate records are emitted")
def step_records_emitted(context, count):
    assert context.result is not None, "expected records, got a quarantine"
    assert len(context.result) == count, f"emitted {len(context.result)}, expected {count}"


@then("a discover record with result_count {count:d} is written to the manifest")
def step_manifest_result_count(context, count):
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["stage"] == "discover", record
    assert record["result_count"] == count, f"recorded {record.get('result_count')}, expected {count}"


@then('the emitted record carries the tldr "{tldr}"')
def step_record_tldr(context, tldr):
    assert context.result is not None, "expected records, got a quarantine"
    assert context.result[0].get("tldr") == tldr, f"record tldr was {context.result[0].get('tldr')!r}"


@then("the emitted record has a null abstract flagged abstract_present false")
def step_record_null_abstract(context):
    assert context.result is not None, "expected records, got a quarantine"
    record = context.result[0]
    assert record["abstract"] is None, f"abstract was {record['abstract']!r}, expected null"
    assert record["abstract_present"] is False, "abstract_present should be false"


@then('the query is quarantined with a "{reason}" reason')
def step_quarantined_reason(context, reason):
    assert context.result is None, f"expected quarantine, got {context.result}"
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert reason in record["reason"], f"reason {record['reason']!r} lacks {reason!r}"


@then("the scholarly API is not contacted")
def step_not_contacted(context):
    assert getattr(context, "searched", []) == [], f"API was contacted: {context.searched}"


# --- US27: SerpAPI Google Scholar sources (scholar organic + scholar-author) ---


@given('an author id "{author_id}"')
def step_author_id(context, author_id):
    # scholar-author's query *is* the author id; reuse context.query as discover's
    # query argument (the engine maps it to author_id).
    context.query = author_id


@given('a "{source}" organic hit whose open resource is a pdf "{pdf_url}"')
def step_scholar_pdf(context, source, pdf_url):
    # A raw SerpAPI google_scholar organic body, parsed through the real parser so
    # the scenario pins resources[]→pdf_url extraction (US27 AC2), not to_record.
    raw = {
        "organic_results": [
            {
                "title": "Retrieval-augmented generation for code summarization",
                "result_id": "hK9c2mQ8x1wJ",
                "link": "https://openreview.net/forum?id=zv-typ1gPxA",
                "snippet": "We augment a code language model with a retriever …",
                "resources": [{"file_format": "PDF", "link": pdf_url}],
            }
        ]
    }
    context.registry = {source: _recording_search(context, candidates=parse_serpapi_scholar(raw))}


@given('a "{source}" organic hit cited {count:d} times')
def step_scholar_cited_by(context, source, count):
    raw = {
        "organic_results": [
            {
                "title": "Dense passage retrieval for open-domain question answering",
                "result_id": "pQ7r3nT9y2wL",
                "link": "https://aclanthology.org/2020.emnlp-main.550",
                "snippet": "We show that retrieval can be practically implemented using dense …",
                "inline_links": {"cited_by": {"total": count}},
            }
        ]
    }
    context.registry = {source: _recording_search(context, candidates=parse_serpapi_scholar(raw))}


@given('a "{source}" profile with one bibliographic article')
def step_scholar_author_article(context, source):
    raw = {
        "articles": [
            {
                "title": "Deep learning",
                "link": "https://scholar.google.com/citations?view_op=view_citation&citation_for_view=JicYPdAAAAAJ:xY1nfvUcv0IC",
                "citation_id": "JicYPdAAAAAJ:xY1nfvUcv0IC",
                "authors": "Y LeCun, Y Bengio, G Hinton",
                "cited_by": {"value": 98213},
                "year": "2015",
            }
        ]
    }
    context.registry = {source: _recording_search(context, candidates=parse_serpapi_scholar_author(raw))}


@given('a "{source}" source with no SerpAPI key')
def step_scholar_no_key(context, source):
    # The real key-gated adapter with no key: it raises MissingKeyError before any
    # network call, so discover quarantines it offline (US27 AC4).
    context.registry = {source: _build_registry(25, None, None, None)[source]}


@then("the emitted record carries the cited_by count {count:d}")
def step_record_cited_by(context, count):
    assert context.result is not None, "expected records, got a quarantine"
    assert context.result[0].get("cited_by") == count, context.result[0].get("cited_by")