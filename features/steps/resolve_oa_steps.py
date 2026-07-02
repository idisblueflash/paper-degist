import json
import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.resolve_oa import resolve_oa


def _work_dir(context):
    if not getattr(context, "work_dir", None):
        context.work_dir = Path(tempfile.mkdtemp())
    return context.work_dir


@given('a failed URL "{url}" the OA index reports open at "{pdf_url}"')
def step_oa_open(context, url, pdf_url):
    context.url = url
    context.oa_lookup = lambda doi: pdf_url


@given('a failed URL "{url}" the OA index reports closed')
def step_oa_closed(context, url):
    context.url = url
    context.oa_lookup = lambda doi: None


@given('a failed URL "{url}" with no DOI')
def step_oa_no_doi(context, url):
    context.url = url
    # No DOI means the lookup must never run; make that a hard failure if it does.
    def _must_not_call(doi):
        raise AssertionError("oa_lookup ran without a DOI")

    context.oa_lookup = _must_not_call


@when("resolve-oa looks it up")
def step_resolve(context):
    context.manifest = _work_dir(context) / "manifest.jsonl"
    context.result = resolve_oa(
        context.url,
        manifest_path=context.manifest,
        oa_lookup=context.oa_lookup,
    )


@then('resolve-oa outputs the OA PDF URL "{pdf_url}"')
def step_outputs_pdf(context, pdf_url):
    assert context.result == pdf_url, f"got {context.result!r}, expected {pdf_url!r}"


@then('the input is quarantined with reason "{reason}"')
def step_quarantined_reason(context, reason):
    assert context.result is None, f"expected quarantine, got {context.result!r}"
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["reason"] == reason


@then('the input is quarantined with a reason mentioning "{needle}"')
def step_quarantined_reason_contains(context, needle):
    assert context.result is None, f"expected quarantine, got {context.result!r}"
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    assert needle in json.loads(line)["reason"]
