import json
import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.fetch_one import fetch_one


class _FakeResponse:
    """Offline stand-in for an httpx.Response (US2: runnable without network)."""

    def __init__(self, *, status_code=200, content_type="", content=b""):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = content


def _work_dir(context):
    if not getattr(context, "work_dir", None):
        context.work_dir = Path(tempfile.mkdtemp())
    return context.work_dir


@given('a URL "{url}" that returns a PDF')
def step_url_pdf(context, url):
    context.url = url
    context.response = _FakeResponse(content_type="application/pdf", content=b"%PDF-1.7 data")


@given('a URL "{url}" that returns HTML')
def step_url_html(context, url):
    context.url = url
    context.response = _FakeResponse(
        content_type="text/html; charset=utf-8", content=b"<html>paper</html>"
    )


@given('a URL "{url}" that returns HTTP {status:d}')
def step_url_status(context, url, status):
    context.url = url
    context.response = _FakeResponse(status_code=status, content_type="text/html", content=b"nope")


@when("fetch-one processes the URL")
def step_fetch(context):
    work = _work_dir(context)
    context.files_dir = work / "files"
    context.manifest = work / "manifest.jsonl"
    context.result = fetch_one(
        context.url,
        files_dir=context.files_dir,
        manifest_path=context.manifest,
        fetch=lambda url: context.response,
    )


@then('the file "{name}" is saved under files/')
def step_file_saved(context, name):
    target = context.files_dir / name
    assert target.exists(), f"{target} was not saved"
    assert context.result == target, f"fetch_one returned {context.result}, expected {target}"


@then("no file is saved under files/")
def step_nothing_saved(context):
    saved = list(context.files_dir.glob("*")) if context.files_dir.exists() else []
    assert not saved, f"expected nothing saved, found {saved}"
    assert context.result is None


@then("the URL is recorded in the manifest")
def step_manifest(context):
    lines = context.manifest.read_text(encoding="utf-8").splitlines()
    urls = [json.loads(line)["url"] for line in lines]
    assert context.url in urls, f"{context.url} not in manifest {urls}"
