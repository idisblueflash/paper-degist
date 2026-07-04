"""US12 — bot-walled 403 assertions.

Reuses the Given/When steps registered in ``fetch_one_steps.py`` (behave shares
one step registry): ``a URL "..." that returns HTTP 403`` sets a 403 response
and ``fetch-one processes the URL`` runs it. Only the manifest-reading Then
steps are new here.
"""

import json

from behave import then


def _only_record(context):
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


@then('the manifest tags the URL blocked_by "{host}"')
def step_tags_blocked_by(context, host):
    record = _only_record(context)
    assert record.get("blocked_by") == host, f"blocked_by was {record.get('blocked_by')!r}"


@then("the manifest reason names a bot-walled source pointing at resolve-oa")
def step_reason_names_wall_and_lane(context):
    reason = _only_record(context)["reason"]
    assert "bot-walled" in reason and "resolve-oa" in reason, reason


@then("the manifest reason flags an abstract-only page")
def step_reason_flags_abstract(context):
    reason = _only_record(context)["reason"]
    assert "abstract" in reason, reason


@then("the manifest record carries no blocked_by host")
def step_no_blocked_by(context):
    assert "blocked_by" not in _only_record(context)
