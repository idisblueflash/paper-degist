import json
import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.embed_text import EmbedResponse, TransportError, _text_hash, embed_text


def _root(context):
    """A temp root holding out/ and manifest.jsonl for the scenario."""
    if not getattr(context, "root", None):
        context.root = Path(tempfile.mkdtemp())
    return context.root


def _recording_transport(context, *, response=None, error=None):
    """A stand-in transport that records its calls (so we can assert contact).

    Returns ``response`` on a 200, or raises ``error`` to mimic a 502 — the
    orchestrator's retry/quarantine policy is what the scenario exercises.
    """
    context.calls = []

    def post(model_id, input_text, endpoint):
        context.calls.append((model_id, input_text, endpoint))
        if error is not None:
            raise error
        return response

    return post


@given('a text to embed "{text}"')
def step_text(context, text):
    context.embed_input = text


@given("an embedding server that returns a vector for a registered model")
def step_server_ok(context):
    context.post = _recording_transport(context, response=EmbedResponse([0.1, 0.2, 0.3, 0.4]))


@given("an embedding server that always returns 502")
def step_server_502(context):
    context.post = _recording_transport(context, error=TransportError("server returned 502"))


@given('the text was already embedded by model "{model}" with role "{role}"')
def step_already_embedded(context, model, role):
    target = (
        _root(context)
        / "out"
        / "embeddings"
        / model.replace("/", "_")
        / f"{_text_hash(model, role, context.embed_input)}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"embedding": [0.0]}), encoding="utf-8")
    # A transport that raises if called — a clean run proves it was skipped.
    context.post = _recording_transport(context, error=TransportError("must not be called"))


@when('embed-text embeds the text with model "{model}" and role "{role}"')
def step_embed(context, model, role):
    root = _root(context)
    context.manifest = root / "manifest.jsonl"
    post = getattr(context, "post", None) or _recording_transport(
        context, response=EmbedResponse([0.5])
    )
    context.result = embed_text(
        context.embed_input,
        model,
        role=role,
        out_dir=root / "out",
        manifest_path=context.manifest,
        post=post,
        gap=0.0,
        sleep=lambda _s: None,
    )


@then('the vector is saved under "{reldir}"')
def step_saved_under(context, reldir):
    expected_dir = _root(context) / reldir
    assert context.result is not None, "expected a saved vector, got a quarantine"
    assert context.result.parent == expected_dir, f"saved under {context.result.parent}, expected {expected_dir}"
    assert json.loads(context.result.read_text(encoding="utf-8"))["embedding"], "saved vector is empty"


@then('an embed record for "{model}" is written to the manifest')
def step_manifest_embed_record(context, model):
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["stage"] == "embed-text", record
    assert record["model"] == model, f"recorded model {record['model']!r}, expected {model!r}"


@then("the embedding server is not contacted")
def step_not_contacted(context):
    assert context.calls == [], f"server was contacted: {context.calls}"


@then('the text is quarantined with a "{reason}" reason')
def step_quarantined_reason(context, reason):
    assert context.result is None, f"expected quarantine, got {context.result}"
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert reason in record["reason"], f"reason {record['reason']!r} lacks {reason!r}"
