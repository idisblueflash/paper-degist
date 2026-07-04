"""US15 — browser-fetch: fetch a bot-walled page through a dev-mode Chrome (CDP).

Classify-then-dispatch over one cheap signal (rule 02): is a CDP endpoint
reachable? Reachable → navigate, wait for the DOM to settle, save the rendered
HTML and record ``saved``; not reachable → quarantine (a missing dev-mode
browser). A navigation that fails once the endpoint *is* reachable quarantines
with a **distinct** reason, so the manifest separates "no browser" from "browser
could not load this page". Like every other step it never crashes and never
calls an LLM — it just carries the item forward to the manifest.

The two collaborators (the CDP probe, the rendered-HTML fetcher) are injected so
the dispatch is exercised without a real Chrome — the same shape as
``browser_up``'s injected probe/launcher and ``fetch_one``'s injected ``fetch``.

One assertion per test (rule 05): each fails for exactly one reason; shared
arrange/act lives in ``_run`` / ``_run_with_existing`` so the split never
duplicates setup.
"""

import json
import os
from pathlib import Path

from contextlib import contextmanager

from paper_degist.browser_fetch import (
    _fetch_on_new_tab,
    _no_proxy_for,
    _target_path,
    _teardown,
    browser_fetch,
    browser_fetch_batch,
)

# The three ResearchGate publications the AC names, plus two more, each distinct
# and self-describing (rule 08) so a scenario's URL *is* its label.
OK_URL = "https://www.researchgate.net/publication/220320021_Spaced_Repetition_and_Long-Term_Retention"
NAV_FAIL_URL = "https://www.researchgate.net/publication/319012693_The_Testing_Effect_in_the_Classroom"
NO_BROWSER_URL = "https://www.researchgate.net/publication/234567890_Retrieval_Practice_Produces_More_Learning"
RERUN_URL = "https://www.researchgate.net/publication/200000001_Interleaving_Improves_Mathematics_Learning"

RENDERED = "<html><body><h1>Spaced Repetition and Long-Term Retention</h1></body></html>"


def _reached(cdp_url):
    return True


def _unreached(cdp_url):
    return False


def _render(html):
    return lambda cdp_url, url: html


def _boom(cdp_url, url):
    raise TimeoutError("Page.navigate timed out after 30000ms")


def _run(tmp_path, *, url, probe_cdp=_reached, fetch_rendered=None):
    """Arrange a fresh files/ + manifest and run browser_fetch; return the trio."""
    files = tmp_path / "files"
    manifest = tmp_path / "manifest.jsonl"
    result = browser_fetch(
        url,
        files_dir=files,
        manifest_path=manifest,
        probe_cdp=probe_cdp,
        fetch_rendered=fetch_rendered or _render(RENDERED),
    )
    return result, files, manifest


def _run_with_existing(tmp_path, *, url, name, content, fetch_rendered):
    """Run browser_fetch when ``files/<name>`` already holds ``content``."""
    files = tmp_path / "files"
    files.mkdir()
    (files / name).write_text(content, encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    result = browser_fetch(
        url,
        files_dir=files,
        manifest_path=manifest,
        probe_cdp=_reached,
        fetch_rendered=fetch_rendered,
    )
    return result, files, manifest


def _only_record(manifest: Path):
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


# --- pure helper: the rendered HTML is saved as files/<slug>.html ---


def test_target_path_appends_html_to_the_slug_basename():
    assert _target_path(OK_URL, Path("files")) == Path(
        "files/220320021_Spaced_Repetition_and_Long-Term_Retention.html"
    )


def test_target_path_does_not_double_the_html_extension():
    assert _target_path("https://example.com/paper.html", Path("files")) == Path("files/paper.html")


# --- proxy bypass: the CDP endpoint is a loopback debug server (US15 E2E) ---


def test_no_proxy_for_adds_the_cdp_host_to_no_proxy(monkeypatch):
    # playwright's connect_over_cdp respects HTTP_PROXY and 502s a loopback CDP
    # server routed through a proxy (surfaced by the real E2E); NO_PROXY must
    # carry the host *inside* the context so the driver hits Chrome directly.
    monkeypatch.delenv("NO_PROXY", raising=False)
    with _no_proxy_for("localhost"):
        assert "localhost" in os.environ["NO_PROXY"]


def test_no_proxy_for_restores_the_prior_no_proxy_after(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "example.com")
    with _no_proxy_for("localhost"):
        pass
    assert os.environ["NO_PROXY"] == "example.com"


def test_no_proxy_for_unions_entries_from_both_proxy_vars(monkeypatch):
    # NO_PROXY and no_proxy can each hold distinct entries; the CDP host must be
    # added *without* dropping either variable's existing hosts (Codex finding).
    monkeypatch.setenv("NO_PROXY", "corp.internal")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    with _no_proxy_for("localhost"):
        entries = set(os.environ["NO_PROXY"].split(","))
    assert {"corp.internal", "127.0.0.1", "localhost"} <= entries


# --- teardown: close only what we opened, never mask the nav result (Codex) ---


class _FakeClosable:
    """A page/context stand-in that records close() — or raises on cleanup."""

    def __init__(self, *, boom=False):
        self.closed = False
        self._boom = boom

    def close(self):
        if self._boom:
            raise RuntimeError("close failed")
        self.closed = True


def test_teardown_closes_the_tab_we_opened():
    page, ctx = _FakeClosable(), _FakeClosable()
    _teardown(page, ctx, created_context=False)
    assert page.closed is True


def test_teardown_leaves_a_reused_context_open():
    page, ctx = _FakeClosable(), _FakeClosable()
    _teardown(page, ctx, created_context=False)
    assert ctx.closed is False


def test_teardown_closes_a_context_we_created():
    page, ctx = _FakeClosable(), _FakeClosable()
    _teardown(page, ctx, created_context=True)
    assert ctx.closed is True


def test_teardown_suppresses_a_page_close_error_and_still_closes_the_context():
    page, ctx = _FakeClosable(boom=True), _FakeClosable()
    _teardown(page, ctx, created_context=True)  # must not raise
    assert ctx.closed is True


def test_teardown_tolerates_a_missing_page():
    ctx = _FakeClosable()
    _teardown(None, ctx, created_context=True)  # new_page() failed before assignment
    assert ctx.closed is True


# --- AC1: reachable endpoint → save the rendered HTML and record `saved` ---


def test_saves_rendered_html_returns_expected_path(tmp_path: Path):
    result, files, _ = _run(tmp_path, url=OK_URL)
    assert result == files / "220320021_Spaced_Repetition_and_Long-Term_Retention.html"


def test_saves_the_rendered_html_body(tmp_path: Path):
    _, files, _ = _run(tmp_path, url=OK_URL)
    saved = files / "220320021_Spaced_Repetition_and_Long-Term_Retention.html"
    assert saved.read_text(encoding="utf-8") == RENDERED


def test_success_appends_a_saved_manifest_record(tmp_path: Path):
    result, _, manifest = _run(tmp_path, url=OK_URL)
    assert _only_record(manifest) == {
        "stage": "browser-fetch",
        "url": OK_URL,
        "cdp_url": "http://localhost:9222",
        "result": "saved",
        "path": str(result),
    }


# --- AC2: no CDP endpoint reachable → quarantine (missing dev-mode browser) ---


def test_no_endpoint_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, url=NO_BROWSER_URL, probe_cdp=_unreached)
    assert result is None


def test_no_endpoint_saves_no_file(tmp_path: Path):
    _, files, _ = _run(tmp_path, url=NO_BROWSER_URL, probe_cdp=_unreached)
    assert not files.exists()


def test_no_endpoint_reason_names_a_missing_dev_mode_browser(tmp_path: Path):
    _, _, manifest = _run(tmp_path, url=NO_BROWSER_URL, probe_cdp=_unreached)
    assert "browser-up" in _only_record(manifest)["reason"]


def test_no_endpoint_records_browser_fetch_stage(tmp_path: Path):
    _, _, manifest = _run(tmp_path, url=NO_BROWSER_URL, probe_cdp=_unreached)
    assert _only_record(manifest)["stage"] == "browser-fetch"


def test_no_endpoint_does_not_navigate(tmp_path: Path):
    # The probe short-circuits before any navigation is attempted (never crash).
    _run(tmp_path, url=NO_BROWSER_URL, probe_cdp=_unreached, fetch_rendered=_boom)


# --- AC3: reachable but navigation fails → quarantine with a *distinct* reason ---


def test_nav_failure_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, url=NAV_FAIL_URL, fetch_rendered=_boom)
    assert result is None


def test_nav_failure_saves_no_file(tmp_path: Path):
    _, files, _ = _run(tmp_path, url=NAV_FAIL_URL, fetch_rendered=_boom)
    assert not files.exists()


def test_nav_failure_reason_names_the_navigation(tmp_path: Path):
    _, _, manifest = _run(tmp_path, url=NAV_FAIL_URL, fetch_rendered=_boom)
    assert "navigation failed" in _only_record(manifest)["reason"]


def test_nav_failure_reason_is_distinct_from_the_missing_endpoint_reason(tmp_path: Path):
    # Separate dirs so each run owns its manifest — the point is the two reasons
    # differ, so the manifest can tell "no browser" from "browser could not load".
    _, _, nav_manifest = _run(tmp_path / "nav", url=NAV_FAIL_URL, fetch_rendered=_boom)
    _, _, gone_manifest = _run(tmp_path / "gone", url=NO_BROWSER_URL, probe_cdp=_unreached)
    assert _only_record(nav_manifest)["reason"] != _only_record(gone_manifest)["reason"]


# --- AC4: a URL already saved by a prior run is skipped (re-runs stay safe) ---


def test_idempotent_skip_returns_existing_path(tmp_path: Path):
    result, files, _ = _run_with_existing(
        tmp_path,
        url=RERUN_URL,
        name="200000001_Interleaving_Improves_Mathematics_Learning.html",
        content="<html>already here</html>",
        fetch_rendered=_boom,
    )
    assert result == files / "200000001_Interleaving_Improves_Mathematics_Learning.html"


def test_idempotent_skip_leaves_the_file_unchanged(tmp_path: Path):
    _, files, _ = _run_with_existing(
        tmp_path,
        url=RERUN_URL,
        name="200000001_Interleaving_Improves_Mathematics_Learning.html",
        content="<html>already here</html>",
        fetch_rendered=_boom,
    )
    saved = files / "200000001_Interleaving_Improves_Mathematics_Learning.html"
    assert saved.read_text(encoding="utf-8") == "<html>already here</html>"


def test_idempotent_skip_appends_no_manifest_record(tmp_path: Path):
    _, _, manifest = _run_with_existing(
        tmp_path,
        url=RERUN_URL,
        name="200000001_Interleaving_Improves_Mathematics_Learning.html",
        content="<html>already here</html>",
        fetch_rendered=_boom,
    )
    assert not manifest.exists()


# ======================================================================== #
# US16 — reuse one warm browser across a batch of URLs (browser_fetch_batch)
# ======================================================================== #
#
# The batch injects an ``open_session`` collaborator (default: the real
# ``_default_open_session``) — a context manager that connects once and yields a
# per-URL ``fetch_tab(url) -> html``. The fake below records how many times the
# connection is opened and closed (AC1/AC3) and maps each URL to its rendered
# HTML or an exception to raise (AC4), so the batch loop is exercised without a
# real Chrome — the same injected shape as US15's ``fetch_rendered``.

# Distinct, self-describing HTML per URL (rule 08) so a saved file *is* its label.
BODY = {
    OK_URL: "<html><body><h1>Spaced Repetition and Long-Term Retention</h1></body></html>",
    NAV_FAIL_URL: TimeoutError("Page.navigate timed out after 30000ms"),
    NO_BROWSER_URL: "<html><body><h1>Retrieval Practice Produces More Learning</h1></body></html>",
    RERUN_URL: "<html><body><h1>Interleaving Improves Mathematics Learning</h1></body></html>",
}


def _slug_html(url):
    """files/<slug>.html for a ResearchGate publication URL, as _target_path derives it."""
    return _target_path(url, Path("files")).name


def _fake_session(responses, *, opens=None):
    """A fake warm session: one connection, a per-URL tab fetcher.

    ``opens`` (if given) records ``("enter", cdp_url)`` on connect and ``"exit"``
    on detach, so a test can assert the connection was opened **once** (AC1) and
    detached (AC3). ``responses`` maps each URL to its rendered HTML, or to an
    Exception the tab raises (a per-URL nav failure, AC4).
    """

    @contextmanager
    def _open(cdp_url):
        if opens is not None:
            opens.append(("enter", cdp_url))
        try:

            def fetch_tab(url):
                reply = responses[url]
                if isinstance(reply, Exception):
                    raise reply
                return reply

            yield fetch_tab
        finally:
            if opens is not None:
                opens.append(("exit", cdp_url))

    return _open


@contextmanager
def _boom_session(cdp_url, **_kw):
    """A session that fails to *open* — connect raised after the probe passed."""
    raise RuntimeError("Browser context management is not supported")
    yield  # pragma: no cover — unreachable; the open raised first


def _run_batch(tmp_path, urls, *, probe_cdp=_reached, responses=None, opens=None, open_session=None):
    """Arrange a fresh files/ + manifest and run browser_fetch_batch; return the trio."""
    files = tmp_path / "files"
    manifest = tmp_path / "manifest.jsonl"
    if open_session is None:
        open_session = _fake_session(responses if responses is not None else BODY, opens=opens)
    result = browser_fetch_batch(
        urls,
        files_dir=files,
        manifest_path=manifest,
        probe_cdp=probe_cdp,
        open_session=open_session,
    )
    return result, files, manifest


def _records(manifest: Path):
    return [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]


# --- AC5: each saved page's path is returned/printed in first-seen order ---


def test_batch_returns_saved_paths_in_first_seen_order(tmp_path: Path):
    result, files, _ = _run_batch(tmp_path, [OK_URL, NO_BROWSER_URL])
    assert result == [files / _slug_html(OK_URL), files / _slug_html(NO_BROWSER_URL)]


# --- AC1: the CDP connection is opened once for the whole batch, not per URL ---


def test_batch_opens_the_connection_once_for_the_whole_list(tmp_path: Path):
    opens = []
    _run_batch(tmp_path, [OK_URL, NO_BROWSER_URL, RERUN_URL], opens=opens)
    assert [op for op, _ in opens].count("enter") == 1


# --- AC3: the batch detaches from the session when the list is done ---


def test_batch_detaches_from_the_session_when_done(tmp_path: Path):
    # The session context manager is exited (detach-not-close lives in the real
    # session; here we assert the batch *closes* the connection it opened).
    opens = []
    _run_batch(tmp_path, [OK_URL, NO_BROWSER_URL], opens=opens)
    assert opens[-1][0] == "exit"


# --- AC4: one URL failing (nav timeout / Chrome lost mid-batch) never aborts ---


def test_batch_continues_past_a_failed_url(tmp_path: Path):
    # NAV_FAIL_URL raises mid-batch; the URL *after* it must still be fetched.
    result, files, _ = _run_batch(tmp_path, [OK_URL, NAV_FAIL_URL, RERUN_URL])
    assert files / _slug_html(RERUN_URL) in result


def test_batch_omits_the_failed_url_from_the_saved_paths(tmp_path: Path):
    result, files, _ = _run_batch(tmp_path, [OK_URL, NAV_FAIL_URL, RERUN_URL])
    assert files / _slug_html(NAV_FAIL_URL) not in result


def test_batch_quarantines_the_failed_url_with_the_nav_reason(tmp_path: Path):
    _, _, manifest = _run_batch(tmp_path, [OK_URL, NAV_FAIL_URL, RERUN_URL])
    (failed,) = [r for r in _records(manifest) if r["url"] == NAV_FAIL_URL]
    assert "navigation failed" in failed["reason"]


# --- AC2 at batch scope: endpoint unreachable at the start → quarantine all ---


def test_batch_unreachable_endpoint_quarantines_every_url(tmp_path: Path):
    _, _, manifest = _run_batch(tmp_path, [OK_URL, NO_BROWSER_URL], probe_cdp=_unreached)
    assert [r["url"] for r in _records(manifest)] == [OK_URL, NO_BROWSER_URL]


def test_batch_unreachable_endpoint_reason_names_browser_up(tmp_path: Path):
    _, _, manifest = _run_batch(tmp_path, [OK_URL, NO_BROWSER_URL], probe_cdp=_unreached)
    assert all("browser-up" in r["reason"] for r in _records(manifest))


def test_batch_unreachable_endpoint_returns_no_saved_paths(tmp_path: Path):
    result, _, _ = _run_batch(tmp_path, [OK_URL, NO_BROWSER_URL], probe_cdp=_unreached)
    assert result == []


def test_batch_unreachable_endpoint_never_opens_a_session(tmp_path: Path):
    # Probe once at the batch boundary — never open a connection we can't use.
    opens = []
    _run_batch(tmp_path, [OK_URL, NO_BROWSER_URL], probe_cdp=_unreached, opens=opens)
    assert "enter" not in [op for op, _ in opens]


# --- US15 idempotency, unchanged over a list: an already-saved URL is skipped ---


def _preseed(tmp_path, url, content="<html>already here</html>"):
    """Pre-save ``files/<slug>`` for ``url`` so the batch should skip it."""
    files = tmp_path / "files"
    files.mkdir(parents=True, exist_ok=True)
    (files / _slug_html(url)).write_text(content, encoding="utf-8")
    return files / _slug_html(url)


def test_batch_skips_an_already_saved_url(tmp_path: Path):
    # RERUN_URL is pre-saved and would *raise* if fetched — so its presence in the
    # result proves it was skipped, not re-fetched.
    existing = _preseed(tmp_path, RERUN_URL)
    responses = {**BODY, RERUN_URL: RuntimeError("must not be fetched")}
    result, _, _ = _run_batch(tmp_path, [RERUN_URL, OK_URL], responses=responses)
    assert existing in result


def test_batch_skip_appends_no_manifest_record(tmp_path: Path):
    _preseed(tmp_path, RERUN_URL)
    responses = {**BODY, RERUN_URL: RuntimeError("must not be fetched")}
    _, _, manifest = _run_batch(tmp_path, [RERUN_URL, OK_URL], responses=responses)
    assert [r["url"] for r in _records(manifest)] == [OK_URL]


def test_batch_unreachable_endpoint_still_skips_an_already_saved_url(tmp_path: Path):
    # A pre-saved URL is returned even with no browser — idempotency precedes the
    # missing-endpoint quarantine, so a re-run of a partly-done batch stays quiet.
    existing = _preseed(tmp_path, RERUN_URL)
    result, _, _ = _run_batch(tmp_path, [RERUN_URL], probe_cdp=_unreached)
    assert result == [existing]


def test_batch_saves_each_url_body(tmp_path: Path):
    _, files, _ = _run_batch(tmp_path, [OK_URL, RERUN_URL])
    assert (files / _slug_html(RERUN_URL)).read_text(encoding="utf-8") == BODY[RERUN_URL]


# --- never crash: the warm session fails to *open* after the probe passed ---
# (US15 DEVLOG: a non-Chrome CDP server answers the probe, or Chrome dies between
#  probe and connect. US15's single fetch caught this per-URL; the batch must too.)


def test_batch_session_open_failure_does_not_crash(tmp_path: Path):
    result, _, _ = _run_batch(tmp_path, [OK_URL, NAV_FAIL_URL], open_session=_boom_session)
    assert result == []


def test_batch_session_open_failure_quarantines_every_url(tmp_path: Path):
    _, _, manifest = _run_batch(tmp_path, [OK_URL, NAV_FAIL_URL], open_session=_boom_session)
    assert [r["url"] for r in _records(manifest)] == [OK_URL, NAV_FAIL_URL]


def test_batch_session_open_failure_reason_is_distinct(tmp_path: Path):
    # Distinct from both "no browser" (probe failed) and per-URL "navigation failed".
    _, _, manifest = _run_batch(tmp_path, [OK_URL], open_session=_boom_session)
    reason = _records(manifest)[0]["reason"]
    assert "session" in reason and "browser-up" not in reason


def test_batch_session_open_failure_still_skips_an_already_saved_url(tmp_path: Path):
    # A pre-saved URL is returned (idempotent), never re-quarantined by the guard.
    existing = _preseed(tmp_path, RERUN_URL)
    result, _, _ = _run_batch(tmp_path, [RERUN_URL], open_session=_boom_session)
    assert result == [existing]


# --- an empty list is a no-op: never probe or open a browser for zero URLs ---


def test_batch_empty_list_is_a_no_op(tmp_path: Path):
    def _explode(cdp_url):
        raise AssertionError("must not probe (or open a browser) for an empty list")

    result, _, _ = _run_batch(tmp_path, [], probe_cdp=_explode)
    assert result == []


# --- AC2: a finished URL's tab is closed, but the context (browser) stays open ---


class _FakePage(_FakeClosable):
    """A page stand-in that records goto()/close() and returns canned content."""

    def __init__(self, html):
        super().__init__()
        self._html = html
        self.goto_args = None

    def goto(self, url, *, wait_until, timeout):
        self.goto_args = (url, wait_until, timeout)

    def content(self):
        return self._html


class _FakeContext:
    """A context stand-in that hands out one page and records its own close()."""

    def __init__(self, page):
        self._page = page
        self.closed = False

    def new_page(self):
        return self._page

    def close(self):
        self.closed = True


def test_fetch_on_new_tab_returns_the_rendered_content():
    page = _FakePage(BODY[OK_URL])
    assert _fetch_on_new_tab(_FakeContext(page), OK_URL, timeout_ms=30000) == BODY[OK_URL]


def test_fetch_on_new_tab_closes_the_finished_tab():
    page = _FakePage(BODY[OK_URL])
    _fetch_on_new_tab(_FakeContext(page), OK_URL, timeout_ms=30000)
    assert page.closed is True


def test_fetch_on_new_tab_leaves_the_context_open_for_the_next_url():
    page = _FakePage(BODY[OK_URL])
    ctx = _FakeContext(page)
    _fetch_on_new_tab(ctx, OK_URL, timeout_ms=30000)
    assert ctx.closed is False
