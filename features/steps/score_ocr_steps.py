import json
import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.score_ocr import score_ocr


def _root(context):
    """A temp root holding out/, scores.jsonl, and manifest.jsonl for the scenario."""
    if not getattr(context, "root", None):
        context.root = Path(tempfile.mkdtemp())
    return context.root


def _save(context, rel_path: str, text: str) -> Path:
    """Save Markdown at out/<model>/<page>.md under the scenario root."""
    target = _root(context) / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    context.output = target
    return target


@given('a saved OCR output "{rel_path}" transcribing a clean page')
def step_output_clean(context, rel_path):
    _save(context, rel_path, "# Vocabulary Acquisition\n\nThe keyword method links a cue to a target.")


@given('an ocr-page manifest record for that output with finish_reason "{reason}"')
def step_manifest_record(context, reason):
    manifest = _root(context) / "manifest.jsonl"
    record = {
        "stage": "ocr-page",
        "model": "qwen/qwen3-vl-4b",
        "page": "pages/WordCraft/p02.png",
        "finish_reason": reason,
        "latency": 20.8,
        "completion_tokens": 167,
    }
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


@given('a saved OCR output "{rel_path}" degenerated into a repeated line')
def step_output_loop(context, rel_path):
    _save(context, rel_path, "\n".join(["the model looped on this line"] * 20))


@given('a saved OCR output "{rel_path}" full of "{artifact}" breaks')
def step_output_hyphen(context, rel_path, artifact):
    _save(context, rel_path, f"The {artifact} scan and the L1- Chinese glossary were hard to read.")


@given('a saved OCR output "{rel_path}" carrying "{citation}"')
def step_output_citation(context, rel_path, citation):
    _save(context, rel_path, f"Prior work builds {citation} from co-occurrence counts.")


@given('a saved OCR output "{rel_path}" whose bytes are not valid UTF-8')
def step_output_unreadable(context, rel_path):
    target = _root(context) / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")
    context.output = target


@when("score-ocr scores it")
def step_score(context):
    context.record = score_ocr(
        context.output,
        scores_path=_root(context) / "scores.jsonl",
        manifest_path=_root(context) / "manifest.jsonl",
    )


@then('a scores record keyed by "{model}" and "{page}" is appended')
def step_keyed(context, model, page):
    assert context.record["model"] == model and context.record["page"] == page, context.record


@then('that record carries the manifest finish_reason "{reason}"')
def step_carries_finish_reason(context, reason):
    assert context.record["finish_reason"] == reason, context.record


@then("the dup_pct dimension is scored high")
def step_dup_high(context):
    assert context.record["dup_pct"] >= 90.0, context.record["dup_pct"]


@then("the hyphen_artifacts dimension reports the count")
def step_hyphen_count(context):
    assert context.record["hyphen_artifacts"] >= 1, context.record["hyphen_artifacts"]


@then("the citation_groups dimension reports the count")
def step_citation_count(context):
    assert context.record["citation_groups"] == 1, context.record["citation_groups"]


@then('the output is quarantined with a "{stage}" stage')
def step_quarantined(context, stage):
    manifest = _root(context) / "manifest.jsonl"
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["stage"] == stage


@then("no scores record is written")
def step_no_scores(context):
    assert not (_root(context) / "scores.jsonl").exists()
