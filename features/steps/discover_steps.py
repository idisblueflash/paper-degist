import json
import tempfile
from pathlib import Path

from behave import given, then, when
from typer.testing import CliRunner

import paper_degist.discover as discover_mod
from paper_degist.discover import Candidate, discover, parse_openalex_json
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


@given('an "{source}" source that rate-limits the search')
def step_source_rate_limited(context, source):
    error = RuntimeError("HTTP 429 Too Many Requests")
    context.registry = {source: _recording_search(context, error=error)}


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
    candidate = _candidate(source)
    candidate = Candidate(**{**candidate.__dict__, "pdf_url": pdf_url})
    context.registry = {source: _recording_search(context, candidates=[candidate])}


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
    discover_mod._build_registry = lambda mr, key, email: {"openalex": search}
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