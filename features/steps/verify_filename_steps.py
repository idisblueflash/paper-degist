"""US13 steps — fetch-one verifies a saved filename against the paper's title.

Reuses the fetch_one steps' "When fetch-one processes the URL" and
"the file ... is saved under files/" phrases (behave shares one step registry);
these steps add only the title-setup Givens and the manifest-assertion Thens.
"""

import json

from behave import given, then


class _FakeResponse:
    """Offline stand-in for an httpx.Response (US2: runnable without network)."""

    def __init__(self, *, status_code=200, content_type="", content=b""):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = content


def _html_titled(title):
    body = f"<title>{title}</title>" if title is not None else ""
    return _FakeResponse(
        content_type="text/html; charset=utf-8",
        content=f"<html><head>{body}</head><body>paper body</body></html>".encode(),
    )


@given('a URL "{url}" returns HTML titled "{title}"')
def step_url_html_titled(context, url, title):
    context.url = url
    context.response = _html_titled(title)


@given('a URL "{url}" returns HTML with no title')
def step_url_html_untitled(context, url):
    context.url = url
    context.response = _html_titled(None)


def _records(context):
    return [json.loads(line) for line in context.manifest.read_text().splitlines()]


@then('the manifest flags "{name}" as a title mismatch')
def step_manifest_mismatch(context, name):
    (record,) = _records(context)
    assert record["file"].endswith(name), f"{record['file']} is not {name}"
    assert "does not reflect" in record["reason"], f"unexpected reason {record['reason']!r}"


@then('the manifest records "{name}" as title-unverifiable')
def step_manifest_unverifiable(context, name):
    (record,) = _records(context)
    assert record["file"].endswith(name), f"{record['file']} is not {name}"
    assert "title-unverifiable" in record["reason"], f"unexpected reason {record['reason']!r}"


@then("no title verification record is written")
def step_no_record(context):
    assert not context.manifest.exists(), f"unexpected manifest {context.manifest}"
