import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.browser_fetch import _await_ready_body

# The synthetic fully-loaded ScienceDirect body (pins the readiness threshold), and
# a body container still holding the "Loading…" placeholder (blocker #3).
_SAMPLE = Path(__file__).resolve().parents[2] / "src" / "tests" / "samples" / "sd-fulltext-lazyload.html"
_FILLED = _SAMPLE.read_text(encoding="utf-8")
_LOADING_STUB = (
    "<html><head><title>A systematic approach for developing a corpus of "
    "patient reported adverse drug events</title></head><body>"
    '<section class="Body">Loading...</section></body></html>'
)
_CLOUDFLARE_WALL = (
    "<html><head><title>Just a moment...</title></head><body>"
    '<script src="/cdn-cgi/challenge-platform/h/b/orchestrate"></script>'
    "</body></html>"
)


def _setup(context):
    """Seed the browser-fetch collaborators (reachable Chrome), mirroring US15 steps."""
    if not getattr(context, "lz_ready", False):
        workdir = Path(tempfile.mkdtemp())
        context.files_dir = workdir / "files"
        context.manifest = workdir / "manifest.jsonl"
        context.cdp_url = "http://localhost:9222"
        context.deps = dict(probe_cdp=lambda _url: True)
        context.lz_ready = True
    return context


@given('a dev-mode Chrome that renders a lazy-load stub for "{url}"')
def step_renders_lazyload_stub(context, url):
    _setup(context)
    context.url = url
    context.deps["fetch_rendered"] = lambda cdp_url, target: _LOADING_STUB


@given('a dev-mode Chrome that renders the fully loaded ScienceDirect body for "{url}"')
def step_renders_full_body(context, url):
    _setup(context)
    context.url = url
    context.deps["fetch_rendered"] = lambda cdp_url, target: _FILLED


@given('a dev-mode Chrome that renders a Cloudflare challenge for the DOI "{url}"')
def step_renders_cloudflare_for_doi(context, url):
    _setup(context)
    context.url = url
    context.deps["fetch_rendered"] = lambda cdp_url, target: _CLOUDFLARE_WALL


@when("browser-fetch classifies the rendered capture in unattended mode")
def step_classifies_unattended(context):
    # The shared "classifies the rendered capture" when-step is unattended by default;
    # this alias makes the default explicit in the scenario text.
    from paper_degist.browser_fetch import browser_fetch

    context.result = browser_fetch(
        context.url,
        cdp_url=context.cdp_url,
        files_dir=context.files_dir,
        manifest_path=context.manifest,
        interactive=False,
        **context.deps,
    )


@then("the rendered full-text HTML is saved under files/")
def step_full_text_saved(context):
    saved = list(context.files_dir.glob("*.html"))
    assert saved, "expected a saved full-text HTML file under files/"
    assert context.result in saved, f"got {context.result!r}, expected one of {saved!r}"


# --- interactive-recovery loop (AC3): notify once, resume when the body loads ---


class _ScriptedPage:
    """A page whose content() walks a scripted sequence (wall → wall → filled body)."""

    def __init__(self, contents):
        self._contents = list(contents)
        self._i = 0

    def goto(self, url, *, wait_until, timeout):
        pass

    def content(self):
        html = self._contents[min(self._i, len(self._contents) - 1)]
        self._i += 1
        return html

    def evaluate(self, script):
        return None


@given("a walled page that the operator clears between polls, then loads the full body")
def step_walled_then_cleared(context):
    context.lz_page = _ScriptedPage([_CLOUDFLARE_WALL, _CLOUDFLARE_WALL, _FILLED])
    context.lz_notes = []


@when("browser-fetch polls the page in interactive mode")
def step_polls_interactive(context):
    context.lz_captured = _await_ready_body(
        context.lz_page,
        "https://doi.org/10.1016/j.jbi.2018.12.005",
        interactive=True,
        notify=context.lz_notes.append,
        sleep=lambda _s: None,
        poll_s=3,
        max_wait_s=240,
    )


@then("the operator is notified once to clear the wall by hand")
def step_notified_once(context):
    assert len(context.lz_notes) == 1, f"expected one notification, got {context.lz_notes!r}"


@then("the captured HTML is the fully loaded body, never the wall")
def step_captured_full_body(context):
    assert context.lz_captured == _FILLED, (
        f"expected the fully loaded body ({len(_FILLED)} chars), got "
        f"{len(context.lz_captured)} chars: {context.lz_captured[:80]!r}"
    )
