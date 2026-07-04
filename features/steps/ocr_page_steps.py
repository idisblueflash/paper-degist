import json
import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.ocr_page import ocr_page


def _root(context):
    """A temp working root for out/ and manifest.jsonl."""
    if not getattr(context, "ocr_root", None):
        context.ocr_root = Path(tempfile.mkdtemp())
    return context.ocr_root


def _make_page(context, name):
    root = _root(context)
    page = root / name
    page.write_bytes(b"\x89PNGfake-image-bytes")
    return page


def _record_post(context, code, body=""):
    """Install a fake transport that returns (code, body) and counts its calls."""
    context.post_calls = 0

    def post(server, body_path):
        context.post_calls += 1
        return (code, body)

    context.post = post


@given('a page image "{name}" and the registered model "{model}"')
def step_page_and_model(context, name, model):
    context.page = _make_page(context, name)
    context.model = model
    context.post = None  # set by a later "server answers" step
    context.post_calls = 0


@given('a page image "{name}" and the unregistered model "{model}"')
def step_page_and_unregistered_model(context, name, model):
    context.page = _make_page(context, name)
    context.model = model

    def post(server, body_path):
        context.post_calls += 1
        return ("200", "")

    context.post = post
    context.post_calls = 0


@given('the server answers 200 with the Markdown "{markdown}"')
def step_server_ok(context, markdown):
    body = json.dumps(
        {
            "choices": [
                {"message": {"content": markdown.replace("\\n", "\n")}, "finish_reason": "stop"}
            ],
            "usage": {"completion_tokens": 17},
        }
    )
    _record_post(context, "200", body)


@given("the server keeps returning 502")
def step_server_502(context):
    _record_post(context, "502", "")


@given('a page image "{name}" already OCR\'d by "{model}" in a prior run')
def step_already_ocrd(context, name, model):
    context.page = _make_page(context, name)
    context.model = model
    root = _root(context)
    target = root / "out" / model.replace("/", "_") / (Path(name).stem + ".md")
    target.parent.mkdir(parents=True)
    target.write_text("# already ocr'd\n", encoding="utf-8")

    def post(server, body_path):
        context.post_calls += 1
        return ("200", "")

    context.post = post
    context.post_calls = 0


@when("ocr-page sends the page over the transport")
def step_send(context):
    root = _root(context)
    context.manifest = root / "manifest.jsonl"
    context.result = ocr_page(
        context.page,
        context.model,
        out_dir=root / "out",
        manifest_path=context.manifest,
        retries=3,
        post=context.post,
        sleep=lambda _s: None,
    )


@then('the Markdown is saved as "{rel}"')
def step_saved_as(context, rel):
    expected = _root(context) / rel
    assert context.result == expected, f"saved {context.result}, expected {expected}"
    assert expected.exists(), f"no file at {expected}"


@then('an ocr record for "{model}" is written to the manifest')
def step_ocr_record(context, model):
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["stage"] == "ocr-page", record
    assert record["model"] == model, record
    assert "latency" in record and "completion_tokens" in record, record


@then("the server is not hit again")
def step_server_not_hit_again(context):
    assert context.result is not None
    assert context.post_calls == 0, f"server was hit {context.post_calls} times"


@then("the server is not hit at all")
def step_server_not_hit_at_all(context):
    assert context.post_calls == 0, f"server was hit {context.post_calls} times"


@then("no new record is written to the manifest")
def step_no_new_record(context):
    assert not context.manifest.exists(), "a manifest record was written on a skip"


@then('the page is quarantined with reason naming "{needle}"')
def step_quarantined(context, needle):
    assert context.result is None, f"expected quarantine, got {context.result}"
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert needle in record["reason"], f"reason {record['reason']!r} lacks {needle!r}"


@then("no Markdown is saved for it")
def step_no_markdown(context):
    assert not (_root(context) / "out").exists()
