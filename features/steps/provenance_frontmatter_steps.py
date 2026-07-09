"""US37 steps — driven offline by injecting a fake fetch into fetch_batch."""

import json
import tempfile
from pathlib import Path

from behave import given, then, when

from paper_degist import _frontmatter
from paper_degist.convert_html import convert_html
from paper_degist.fetch_batch import fetch_batch


class _FakeResponse:
    def __init__(self, *, status_code=200, content_type="application/pdf", content=b"%PDF-1.7"):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = content


def _pdf_fetch(url):
    return _FakeResponse()


def _workdir(context):
    if not getattr(context, "workdir", None):
        context.workdir = Path(tempfile.mkdtemp())
    return context.workdir


def _write_candidates(context, records):
    path = _workdir(context) / "candidates.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    context.candidates = path


# --- fetch-batch scenarios ---


@given('a candidates file with a record for "{url}" carrying doi "{doi}"')
def step_candidates_one(context, url, doi):
    _write_candidates(context, [{"url": url, "doi": doi}])


@given('a candidates file whose first record has no url and whose second is "{url}"')
def step_candidates_no_url_then_ok(context, url):
    _write_candidates(context, [{"doi": "10.1/no-url"}, {"url": url}])


@when("fetch-batch runs over the candidates")
def step_run_fetch_batch(context):
    work = _workdir(context)
    context.manifest = work / "manifest.jsonl"
    context.saved = fetch_batch(
        context.candidates,
        files_dir=work / "files",
        manifest_path=context.manifest,
        fetch=_pdf_fetch,
    )


@then('a sidecar carrying doi "{doi}" is written next to the saved file')
def step_sidecar_has_doi(context, doi):
    assert _frontmatter.load_sidecar(context.saved[0])["doi"] == doi


@then('the url-less record is quarantined to stage "{stage}"')
def step_url_less_quarantined(context, stage):
    stages = [json.loads(line)["stage"] for line in context.manifest.read_text().splitlines()]
    assert stage in stages


@then("the second paper is still saved")
def step_second_saved(context):
    assert [p.name for p in context.saved] == ["1706.03762.pdf"]


# --- convert frontmatter scenarios ---


def _make_html_paper(context, *, with_sidecar):
    html = _workdir(context) / "attention.html"
    html.write_text("<html><body><h1>Title</h1><p>" + "word " * 80 + "</p></body></html>", encoding="utf-8")
    if with_sidecar:
        _frontmatter.write_sidecar(html, {"doi": "10.1/x", "url": "u", "pdf_url": "p", "venue": "Cognition"})
    context.html = html


@given('a fetched HTML paper whose sidecar carries venue "{venue}"')
def step_html_with_sidecar(context, venue):
    _make_html_paper(context, with_sidecar=True)


@given("a fetched HTML paper with no sidecar")
def step_html_no_sidecar(context):
    _make_html_paper(context, with_sidecar=False)


@when("convert-html runs on it")
def step_run_convert_html(context):
    context.md = convert_html(context.html, manifest_path=_workdir(context) / "manifest.jsonl")


@then("the .md begins with a YAML frontmatter block")
def step_md_has_frontmatter(context):
    assert context.md.read_text(encoding="utf-8").startswith("---\n")


@then("the .md has no frontmatter block")
def step_md_no_frontmatter(context):
    assert not context.md.read_text(encoding="utf-8").startswith("---\n")
