"""BDD steps for US11 — clickable doi.org link in the resolve-oa quarantine.

Behave shares one step registry, so these reuse US9's Given/When phrases (a
closed OA verdict, a no-DOI slug) and add *only* the Then phrases that assert
the derived ``doi_url`` field — never redefining a shared step.
"""

import json

from behave import then


def _only_record(context):
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


@then('the quarantine record carries a clickable link "{doi_url}"')
def step_record_has_doi_url(context, doi_url):
    assert context.result is None, f"expected quarantine, got {context.result!r}"
    assert _only_record(context)["doi_url"] == doi_url


@then("the quarantine record carries no clickable DOI link")
def step_record_has_no_doi_url(context):
    assert context.result is None, f"expected quarantine, got {context.result!r}"
    assert "doi_url" not in _only_record(context)
