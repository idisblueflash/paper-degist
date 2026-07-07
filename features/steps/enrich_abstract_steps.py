import json
import tempfile
from pathlib import Path

from behave import given, then, when

from paper_degist.enrich_abstract import enrich_abstract
from paper_degist.abstract_filter import load_candidates


def _work_with_abstract(abstract_text: str) -> dict:
    words = abstract_text.split()
    inverted = {w: [i] for i, w in enumerate(words)}
    return {"id": "https://openalex.org/W1", "abstract_inverted_index": inverted}


def _work_no_abstract() -> dict:
    return {"id": "https://openalex.org/W2", "abstract_inverted_index": None}


@given('a candidate "{doi}" without an abstract')
def step_candidate_without_abstract(context, doi):
    context.ea_candidates = [{"title": f"Paper {doi}", "doi": doi,
                               "url": f"https://doi.org/{doi}",
                               "abstract": None, "abstract_present": False}]
    context.ea_fetch_work = lambda d, email: _work_no_abstract()
    context.ea_manifest = Path(tempfile.mkdtemp()) / "manifest.jsonl"


@given('a candidate "{doi}" with abstract "{abstract}"')
def step_candidate_with_abstract(context, doi, abstract):
    context.ea_candidates = [{"title": f"Paper {doi}", "doi": doi,
                               "url": f"https://doi.org/{doi}",
                               "abstract": abstract, "abstract_present": True}]
    context.ea_fetch_work = lambda d, email: _work_no_abstract()
    context.ea_manifest = Path(tempfile.mkdtemp()) / "manifest.jsonl"


@given('a candidate without a doi or abstract')
def step_candidate_without_doi(context):
    context.ea_candidates = [{"title": "No DOI Paper", "url": "https://example.com",
                               "abstract": None, "abstract_present": False}]
    context.ea_fetch_work = lambda d, email: _work_no_abstract()
    context.ea_manifest = Path(tempfile.mkdtemp()) / "manifest.jsonl"


@given('the OpenAlex work for "{doi}" has abstract "{abstract}"')
def step_work_has_abstract(context, doi, abstract):
    context.ea_fetch_work = lambda d, email: _work_with_abstract(abstract)


@given('the OpenAlex lookup for "{doi}" raises a not-found error')
def step_work_raises_not_found(context, doi):
    def _raise(d, email):
        raise RuntimeError("404 Not Found")
    context.ea_fetch_work = _raise


@given('the OpenAlex work for "{doi}" has no abstract on record')
def step_work_has_no_abstract(context, doi):
    context.ea_fetch_work = lambda d, email: _work_no_abstract()


@given('a candidate JSONL input with one garbage line and one valid candidate "{doi}" with abstract "{abstract}"')
def step_garbage_plus_valid(context, doi, abstract):
    garbage = "not valid json {{{"
    valid = json.dumps({"title": f"Paper {doi}", "doi": doi,
                        "url": f"https://doi.org/{doi}",
                        "abstract": abstract, "abstract_present": True})
    context.ea_raw_text = f"{garbage}\n{valid}\n"
    context.ea_fetch_work = lambda d, email: _work_no_abstract()
    context.ea_manifest = Path(tempfile.mkdtemp()) / "manifest.jsonl"
    # Parse candidates here so garbage is quarantined
    context.ea_candidates = load_candidates(context.ea_raw_text,
                                            manifest_path=context.ea_manifest,
                                            stage="enrich-abstract")


@when('enrich-abstract runs')
def step_run_enrich_abstract(context):
    context.ea_result = enrich_abstract(
        context.ea_candidates,
        manifest_path=context.ea_manifest,
        _fetch_work=context.ea_fetch_work,
    )


def _manifest_rows(context):
    p = context.ea_manifest
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


@then('the output contains the candidate with abstract "{abstract}"')
def step_output_has_abstract(context, abstract):
    abstracts = [r.get("abstract") for r in context.ea_result]
    assert abstract in abstracts, f"{abstract!r} not in {abstracts}"


@then('the output candidate has abstract_present true')
def step_output_has_abstract_present(context):
    assert any(r.get("abstract_present") is True for r in context.ea_result)


@then('nothing is emitted by enrich-abstract')
def step_nothing_emitted(context):
    assert context.ea_result == [], f"expected empty, got {context.ea_result}"


@then('the enrich-abstract manifest has a quarantined row with reason "{reason}"')
def step_manifest_quarantined_row(context, reason):
    rows = _manifest_rows(context)
    match = [r for r in rows if r.get("reason") == reason]
    assert match, f"no row with reason={reason!r} in {rows}"


@then('the enrich-abstract manifest has a quarantined row for the garbage line')
def step_manifest_garbage_row(context):
    rows = _manifest_rows(context)
    match = [r for r in rows if "unparseable" in r.get("reason", "")]
    assert match, f"no unparseable row in {rows}"
