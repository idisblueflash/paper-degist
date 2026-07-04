import json
import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.ocr_page import OcrResponse, TransportError, ocr_page


def _root(context):
    """A temp root holding pages/, out/, and manifest.jsonl for the scenario."""
    if not getattr(context, "root", None):
        context.root = Path(tempfile.mkdtemp())
    return context.root


def _recording_transport(context, *, response=None, error=None):
    """A stand-in transport that records its calls (so we can assert contact).

    Returns ``response`` on a 200, or raises ``error`` to mimic a 502 — the
    orchestrator's retry/quarantine policy is what the scenario exercises.
    """
    context.calls = []

    def post(model_id, prompt, image_path, endpoint):
        context.calls.append((model_id, prompt, image_path, endpoint))
        if error is not None:
            raise error
        return response

    return post


@given('a saved page image "{name}"')
def step_saved_page(context, name):
    pages = _root(context) / "pages" / "WordCraft"
    pages.mkdir(parents=True, exist_ok=True)
    context.page = pages / name
    context.page.write_bytes(b"\x89PNG page bytes")


@given("a vision server that returns Markdown for a registered model")
def step_server_ok(context):
    context.post = _recording_transport(
        context, response=OcrResponse("# A Paper Title\n\nBody.", "stop", 128)
    )


@given("a vision server that always returns 502")
def step_server_502(context):
    context.post = _recording_transport(context, error=TransportError("server returned 502"))


@given('the page was already OCR\'d by model "{model}"')
def step_already_ocrd(context, model):
    target = _root(context) / "out" / model.replace("/", "_") / (context.page.stem + ".md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# already OCR'd", encoding="utf-8")
    # A transport that raises if called — a clean run proves it was skipped.
    context.post = _recording_transport(context, error=TransportError("must not be called"))


@when('ocr-page OCRs the page with model "{model}"')
def step_ocr(context, model):
    root = _root(context)
    context.manifest = root / "manifest.jsonl"
    post = getattr(context, "post", None) or _recording_transport(
        context, response=OcrResponse("# Default", "stop", 1)
    )
    context.result = ocr_page(
        context.page,
        model,
        out_dir=root / "out",
        manifest_path=context.manifest,
        post=post,
        gap=0.0,
        sleep=lambda _s: None,
    )


@then('the Markdown is saved as "{relpath}"')
def step_saved_as(context, relpath):
    expected = _root(context) / relpath
    assert context.result == expected, f"saved {context.result}, expected {expected}"
    assert expected.read_text(encoding="utf-8"), "saved Markdown is empty"


@then('an ocr record for "{model}" is written to the manifest')
def step_manifest_ocr_record(context, model):
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["stage"] == "ocr-page", record
    assert record["model"] == model, f"recorded model {record['model']!r}, expected {model!r}"


@then("the vision server is not contacted")
def step_not_contacted(context):
    assert context.calls == [], f"server was contacted: {context.calls}"


@then('the page and model are quarantined with a "{reason}" reason')
def step_quarantined_reason(context, reason):
    assert context.result is None, f"expected quarantine, got {context.result}"
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert reason in record["reason"], f"reason {record['reason']!r} lacks {reason!r}"
