"""US16 — browser-fetch reuses one warm browser across a batch of URLs.

The batch injects an ``open_session`` collaborator — a context manager that
connects once and yields a per-URL ``fetch_tab(url) -> html``. The fake here
records how many times the connection is opened/detached (AC1/AC3) and maps
each URL to its rendered HTML or an exception to raise (AC4), so the loop runs
without a real Chrome — the same injected shape as US15's ``fetch_rendered``.

Step phrases are deliberately distinct from ``browser_fetch_steps.py`` (US15):
behave shares one step registry across all step files, so the batch scenarios
say "a *warm* dev-mode Chrome" and "a *batch* of bot-walled URLs" to avoid
redefining the single-URL step phrases (rule 06 phase 5).
"""

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

from behave import given, then, when

from paper_degist.browser_fetch import _target_path, browser_fetch_batch


def _batch_ctx(context):
    """Lazily seed the batch fixture: a fresh files/ + manifest and empty tallies."""
    if not getattr(context, "batch_ready", False):
        workdir = Path(tempfile.mkdtemp())
        context.b_files = workdir / "files"
        context.b_manifest = workdir / "manifest.jsonl"
        context.b_cdp = "http://localhost:9222"
        context.b_opens = []  # "enter"/"exit" per connection open/detach
        context.b_responses = {}  # url -> rendered HTML, or an Exception to raise
        context.b_reachable = True
        context.b_urls = []
        context.batch_ready = True
    return context


def _slug(url):
    return _target_path(url, Path("files")).name


@given('a warm dev-mode Chrome reachable at "{cdp_url}"')
def step_warm_chrome(context, cdp_url):
    _batch_ctx(context)
    context.b_cdp = cdp_url
    context.b_reachable = True


@given("a batch of bot-walled URLs:")
def step_batch_urls(context):
    _batch_ctx(context)
    context.b_urls = [row["url"] for row in context.table]
    for url in context.b_urls:
        # A distinct, self-describing body per URL (rule 08); a failing URL
        # overrides this via the step below (which must run *after* this one).
        context.b_responses.setdefault(url, f"<html><body>{url}</body></html>")


@given('the URL "{url}" whose navigation fails')
def step_url_nav_fails(context, url):
    _batch_ctx(context)
    context.b_responses[url] = TimeoutError("Page.navigate timed out after 30000ms")


def _open_session(context):
    @contextmanager
    def _open(cdp_url, **_kw):
        context.b_opens.append("enter")  # one warm connection for the whole list
        try:

            def fetch_tab(url):
                reply = context.b_responses[url]
                if isinstance(reply, Exception):
                    raise reply
                return reply

            yield fetch_tab
        finally:
            context.b_opens.append("exit")  # detach at the end (never browser.close)

    return _open


@when("browser-fetch processes the whole batch")
def step_process_batch(context):
    context.b_result = browser_fetch_batch(
        context.b_urls,
        cdp_url=context.b_cdp,
        files_dir=context.b_files,
        manifest_path=context.b_manifest,
        probe_cdp=lambda cdp: context.b_reachable,
        open_session=_open_session(context),
    )


@then("the CDP connection is opened exactly once")
def step_connection_once(context):
    assert context.b_opens.count("enter") == 1, context.b_opens


@then("the warm browser is left running after the batch detaches")
def step_detached(context):
    # The session context manager exited (detach) — the real session never calls
    # browser.close(), so the warm Chrome is left running for the next run (AC3).
    assert context.b_opens[-1:] == ["exit"], context.b_opens


@then("every URL's rendered HTML is saved under files/")
def step_all_saved(context):
    missing = [u for u in context.b_urls if not (context.b_files / _slug(u)).is_file()]
    assert not missing, f"not saved: {missing}"


@then("the saved paths are returned in first-seen order")
def step_order(context):
    expected = [context.b_files / _slug(u) for u in context.b_urls]
    assert context.b_result == expected, f"{context.b_result} != {expected}"


@then('the URL "{url}" is quarantined with a navigation reason')
def step_quarantined_nav(context, url):
    records = [json.loads(line) for line in context.b_manifest.read_text(encoding="utf-8").splitlines()]
    match = [r for r in records if r.get("url") == url]
    assert match, f"{url} not quarantined; records={records}"
    assert "navigation failed" in match[0]["reason"], match[0]


@then("the other URLs are still saved under files/")
def step_others_saved(context):
    failed = {u for u, r in context.b_responses.items() if isinstance(r, Exception)}
    survivors = [u for u in context.b_urls if u not in failed]
    missing = [u for u in survivors if not (context.b_files / _slug(u)).is_file()]
    assert survivors and not missing, f"survivors={survivors} missing={missing}"
