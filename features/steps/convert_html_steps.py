import json
import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.convert_html import convert_html


def _files_dir(context):
    """The literal files/ folder the spec names — created under a temp root."""
    if not getattr(context, "files_dir", None):
        context.files_dir = Path(tempfile.mkdtemp()) / "files"
        context.files_dir.mkdir()
    return context.files_dir


@given('a saved HTML file "{name}" with a heading and body text')
def step_html_paper(context, name):
    body = "<h1>Title</h1><p>" + "lorem ipsum dolor sit amet " * 40 + "</p>"
    context.html = _files_dir(context) / name
    context.html.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")


@given('a saved HTML file "{name}" that is a hollow SPA shell')
def step_html_shell(context, name):
    context.html = _files_dir(context) / name
    context.html.write_text(
        '<html><body><div id="__next"></div></body></html>', encoding="utf-8"
    )


@when("convert-html processes the file")
def step_convert(context):
    context.manifest = _files_dir(context).parent / "manifest.jsonl"
    context.result = convert_html(context.html, manifest_path=context.manifest)


@then('the Markdown file "{name}" is saved under files/')
def step_md_saved(context, name):
    target = _files_dir(context) / name
    assert target.exists(), f"{target} was not saved"
    assert target.parent.name == "files", f"{target} is not under a files/ folder"
    assert context.result == target, f"convert_html returned {context.result}, expected {target}"


@then("the heading is preserved as Markdown")
def step_heading_preserved(context):
    md = context.result.read_text(encoding="utf-8")
    assert "# Title" in md, f"heading not preserved in:\n{md}"


@then("no Markdown file is saved for it")
def step_nothing_saved(context):
    assert context.result is None
    assert not context.html.with_suffix(".md").exists()


@then('the file is recorded in the manifest with reason "{reason}"')
def step_manifest(context, reason):
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["path"] == str(context.html), f"{record} does not name {context.html}"
    assert record["reason"] == reason, f"reason was {record['reason']!r}, expected {reason!r}"
