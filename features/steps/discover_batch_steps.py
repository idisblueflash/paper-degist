import json
import tempfile
from pathlib import Path

from behave import given, then, when

from paper_degist.discover import ARXIV_MIN_INTERVAL, Candidate
from paper_degist.discover_batch import discover_batch


def _root(context):
    if not getattr(context, "batch_root", None):
        context.batch_root = Path(tempfile.mkdtemp())
    return context.batch_root


def _batch_candidate(source, *, title, url, source_id, abstract, doi=None):
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


def _registry(context):
    if not getattr(context, "batch_registry", None):
        context.batch_registry = {}
    return context.batch_registry


def _recording(candidates=None, error=None):
    def search(query):
        search.queries.append(query)
        if error is not None:
            raise error
        return list(candidates or [])

    search.queries = []
    return search


@given('the batch query "{query}"')
def step_batch_one_query(context, query):
    context.batch_queries = [query]


@given('the batch queries "{first}" and "{second}"')
def step_batch_two_queries(context, first, second):
    context.batch_queries = [first, second]


@given('a batch "{source}" source returning one candidate')
def step_batch_source_one(context, source):
    _registry(context)[source] = _recording(
        candidates=[
            _batch_candidate(
                source,
                title=f"A {source} sequence-modeling paper",
                url=f"https://example.org/{source}/mamba",
                source_id=f"{source}-2312.00752",
                abstract="Selective state space models match Transformers.",
            )
        ],
    )


@given('a batch "{source}" source returning no candidates')
def step_batch_source_empty(context, source):
    _registry(context)[source] = _recording(candidates=[])


@given('a batch "{source}" source that rate-limits')
def step_batch_source_rate_limited(context, source):
    _registry(context)[source] = _recording(
        error=RuntimeError("HTTP 429 Too Many Requests")
    )


@given('two batch sources returning the same paper under DOI spellings "{doi_a}" and "{doi_b}"')
def step_batch_doi_duplicate(context, doi_a, doi_b):
    registry = _registry(context)
    registry["openalex"] = _recording(
        candidates=[
            _batch_candidate(
                "openalex",
                title="Liquid Time-constant Networks",
                url=f"https://doi.org/{doi_a}",
                source_id="W4402112233",
                abstract="Continuous-time RNNs with input-dependent time constants.",
                doi=doi_a,
            )
        ],
    )
    registry["s2"] = _recording(
        candidates=[
            _batch_candidate(
                "s2",
                title="Liquid Time-constant Networks",
                url="https://www.semanticscholar.org/paper/ltc99",
                source_id="ltc99",
                abstract="Continuous-time RNNs with input-dependent time constants.",
                doi=doi_b,
            )
        ],
    )


@given('a batch "{source}" source returning the same DOI-less paper for every query')
def step_batch_doiless_repeat(context, source):
    _registry(context)[source] = _recording(
        candidates=[
            _batch_candidate(
                source,
                title="RWKV: Reinventing RNNs for the Transformer Era",
                url="http://arxiv.org/abs/2305.13048v2",
                source_id="2305.13048v2",
                abstract="A linear-attention RNN that trains like a Transformer.",
            )
        ],
    )


@given('a batch "scholar-author" stub and a batch "openalex" duplicate carrying the abstract')
def step_batch_upgrade_pair(context):
    registry = _registry(context)
    registry["scholar-author"] = _recording(
        candidates=[
            _batch_candidate(
                "scholar-author",
                title="FlashAttention: Fast and Memory-Efficient Exact Attention",
                url="https://scholar.google.com/citations?view_op=view_citation&citation_for_view=fa1",
                source_id="TriDaoAAAJ:fa1",
                abstract=None,
                doi="10.48550/arxiv.2205.14135",
            )
        ],
    )
    registry["openalex"] = _recording(
        candidates=[
            _batch_candidate(
                "openalex",
                title="FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness",
                url="https://doi.org/10.48550/arxiv.2205.14135",
                source_id="W4281694645",
                abstract="We propose FlashAttention, an IO-aware exact attention algorithm.",
                doi="10.48550/arxiv.2205.14135",
            )
        ],
    )


@when("discover-batch runs")
def step_batch_runs(context):
    root = _root(context)
    context.batch_manifest = root / "manifest.jsonl"
    context.batch_waits = []
    context.batch_result = discover_batch(
        context.batch_queries,
        list(_registry(context)),
        registry=_registry(context),
        manifest_path=context.batch_manifest,
        pause=context.batch_waits.append,
    )


def _batch_rows(context):
    lines = context.batch_manifest.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


@then("every batch source saw both queries")
def step_batch_saw_both(context):
    for source, search in _registry(context).items():
        assert search.queries == context.batch_queries, (source, search.queries)


@then("the merged stream carries the arxiv and the openalex candidate")
def step_batch_merged_stream(context):
    sources = sorted(r["source"] for r in context.batch_result)
    assert sources == ["arxiv", "openalex"], context.batch_result


@then("a discover-batch summary record is written to the manifest")
def step_batch_summary(context):
    rows = [
        r
        for r in _batch_rows(context)
        if r["stage"] == "discover-batch" and "result_count" in r
    ]
    assert len(rows) == 1, rows


@then("only one merged candidate is emitted")
def step_batch_one_emitted(context):
    assert len(context.batch_result) == 1, context.batch_result


@then('the duplicate is filtered with reason "{reason}"')
def step_batch_filtered_reason(context, reason):
    dropped = [
        r
        for r in _batch_rows(context)
        if r["stage"] == "discover-batch" and r.get("event") == "filtered"
    ]
    assert [r["reason"] for r in dropped] == [reason], dropped


@then('the merged candidate is the "{source}" copy')
def step_batch_kept_source(context, source):
    (kept,) = context.batch_result
    assert kept["source"] == source, kept


@then("the surviving batch candidates are still emitted")
def step_batch_survivors(context):
    assert [r["source"] for r in context.batch_result] == ["arxiv"], context.batch_result


@then('the batch is quarantined with a "{reason}" reason')
def step_batch_quarantined(context, reason):
    assert context.batch_result is None
    (row,) = [r for r in _batch_rows(context) if r["stage"] == "discover-batch"]
    assert reason in row["reason"], row


@then("the batch waited the arXiv etiquette interval between the arXiv calls")
def step_batch_waited(context):
    assert context.batch_waits == [ARXIV_MIN_INTERVAL], context.batch_waits


@then("the batch waited the OpenAlex interval between the OpenAlex calls")
def step_batch_waited_openalex(context):
    from paper_degist.discover import OPENALEX_MIN_INTERVAL

    assert context.batch_waits == [OPENALEX_MIN_INTERVAL], context.batch_waits
