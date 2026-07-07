import json
import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.browser_fetch import browser_fetch

RENDERED = "<html><body><h1>captured through the real browser</h1></body></html>"


def _fakes(context):
    """Lazily seed the injected collaborators with reachable + renders defaults."""
    if not getattr(context, "bf_ready", False):
        workdir = Path(tempfile.mkdtemp())
        context.files_dir = workdir / "files"
        context.manifest = workdir / "manifest.jsonl"
        context.cdp_url = "http://localhost:9222"
        context.deps = dict(
            probe_cdp=lambda url: True,
            fetch_rendered=lambda cdp_url, url: RENDERED,
        )
        context.bf_ready = True
    return context


@given('a dev-mode Chrome reachable at "{cdp_url}"')
def step_chrome_reachable_bf(context, cdp_url):
    _fakes(context)
    context.cdp_url = cdp_url
    context.deps["probe_cdp"] = lambda url: True


@given('no dev-mode Chrome is reachable at "{cdp_url}"')
def step_chrome_unreachable_bf(context, cdp_url):
    _fakes(context)
    context.cdp_url = cdp_url
    context.deps["probe_cdp"] = lambda url: False


@given('a bot-walled URL "{url}"')
def step_bot_walled_url(context, url):
    _fakes(context)
    context.url = url


@given('a bot-walled URL "{url}" whose navigation fails')
def step_bot_walled_url_nav_fails(context, url):
    _fakes(context)
    context.url = url

    def _boom(cdp_url, target):
        raise TimeoutError("Page.navigate timed out after 30000ms")

    context.deps["fetch_rendered"] = _boom


@given('the HTML "{name}" was already saved under files/')
def step_html_already_saved(context, name):
    _fakes(context)
    context.files_dir.mkdir(parents=True, exist_ok=True)
    (context.files_dir / name).write_text("<html>already here</html>", encoding="utf-8")
    context.preexisting = context.files_dir / name


def _run_bf(context):
    context.result = browser_fetch(
        context.url,
        cdp_url=context.cdp_url,
        files_dir=context.files_dir,
        manifest_path=context.manifest,
        **context.deps,
    )


@when("browser-fetch navigates to it and the DOM settles")
def step_navigate_settles(context):
    _run_bf(context)


@when("browser-fetch cannot connect")
def step_cannot_connect(context):
    _run_bf(context)


@when("browser-fetch cannot render the page")
def step_cannot_render(context):
    _run_bf(context)


@when("browser-fetch runs again on the same URL")
def step_runs_again(context):
    _run_bf(context)


@then("the rendered HTML \"{name}\" is saved under files/")
def step_html_saved(context, name):
    saved = context.files_dir / name
    assert saved.is_file(), f"expected {saved} to exist"
    assert context.result == saved, f"got {context.result!r}, expected {saved!r}"


@then('a "saved" record is appended to the manifest with stage "{stage}"')
def step_saved_record(context, stage):
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["stage"] == stage, f"stage was {record.get('stage')!r}"
    assert record["result"] == "saved", f"expected a saved record, got {record!r}"


@then("no HTML file is saved under files/")
def step_no_html_saved(context):
    saved = list(context.files_dir.glob("*.html")) if context.files_dir.exists() else []
    assert saved == [], f"unexpected saved files: {saved!r}"


@then('the URL is recorded in the manifest with reason mentioning "{needle}"')
def step_url_recorded_reason(context, needle):
    (line,) = context.manifest.read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["url"] == context.url, f"url was {record.get('url')!r}"
    assert needle in record["reason"], f"{needle!r} not in {record['reason']!r}"


@then("the saved HTML file is left unchanged")
def step_file_unchanged(context):
    assert context.result == context.preexisting, f"got {context.result!r}"
    assert context.preexisting.read_text(encoding="utf-8") == "<html>already here</html>"


@then("no new record is appended to the manifest")
def step_no_new_record(context):
    assert not context.manifest.exists(), f"unexpected manifest: {context.manifest}"


# --- US35: a wall (Cloudflare / a different paper) captured instead of the paper ---

# A Cloudflare challenge page: renders fine, carries the challenge script, and its
# <title> is the interstitial — not the requested paper.
_CLOUDFLARE_WALL = (
    "<html><head><title>Just a moment...</title></head><body>"
    '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate"></script>'
    "</body></html>"
)

# A page that renders a *different* paper: no wall marker, but the <title> shares
# no content word with the requested URL's slug.
_WRONG_PAPER = (
    "<html><head><title>The Psychology of Everyday Things</title></head>"
    "<body><h1>The Psychology of Everyday Things</h1></body></html>"
)


@given('a dev-mode Chrome that renders a Cloudflare challenge for "{url}"')
def step_renders_cloudflare_wall(context, url):
    _fakes(context)
    context.deps["probe_cdp"] = lambda _url: True
    context.url = url
    context.deps["fetch_rendered"] = lambda cdp_url, target: _CLOUDFLARE_WALL


@given('a dev-mode Chrome that renders a different paper for "{url}"')
def step_renders_different_paper(context, url):
    _fakes(context)
    context.deps["probe_cdp"] = lambda _url: True
    context.url = url
    context.deps["fetch_rendered"] = lambda cdp_url, target: _WRONG_PAPER


@given('a dev-mode Chrome that renders the genuine paper titled "{title}" for "{url}"')
def step_renders_genuine_paper(context, title, url):
    _fakes(context)
    context.deps["probe_cdp"] = lambda _url: True
    context.url = url
    html = f"<html><head><title>{title}</title></head><body><h1>{title}</h1></body></html>"
    context.deps["fetch_rendered"] = lambda cdp_url, target: html


@when("browser-fetch classifies the rendered capture")
def step_classifies_capture(context):
    _run_bf(context)
