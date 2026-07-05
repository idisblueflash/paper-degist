import json
import tempfile
from pathlib import Path

from behave import given, then, when

from paper_degist.discover import Candidate, discover


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