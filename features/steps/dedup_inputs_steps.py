import json
import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.dedup_inputs import dedup_inputs


@given("the input list:")
def step_input_list(context):
    context.inputs = [row["input"] for row in context.table]
    context.dedup_manifest = Path(tempfile.mkdtemp()) / "manifest.jsonl"


@when("dedup-inputs processes the list")
def step_dedup(context):
    context.kept = dedup_inputs(context.inputs, manifest_path=context.dedup_manifest)


@then("the kept inputs are exactly:")
def step_kept_exactly(context):
    expected = [row["input"] for row in context.table]
    assert context.kept == expected, f"expected {expected}, got {context.kept}"


@then('"{dropped}" is recorded in the manifest as a duplicate of "{kept}"')
def step_manifest_duplicate(context, dropped, kept):
    (line,) = context.dedup_manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["stage"] == "dedup-inputs", f"stage was {record.get('stage')!r}"
    assert record["input"] == dropped, f"input was {record.get('input')!r}"
    assert record["duplicate_of"] == kept, f"duplicate_of was {record.get('duplicate_of')!r}"
