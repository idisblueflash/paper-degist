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
    _rendered_title,
    _target_path,
    _teardown,
    _url_content_tokens,
    _wall_reason,
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

# US40 shared fixtures: the synthetic full-text sample pins the readiness threshold
# (a filled ScienceDirect body), and the stub is a body container still holding the
# "Loading…" placeholder (blocker #3).
_LAZYLOAD_SAMPLE = Path(__file__).parent / "samples" / "sd-fulltext-lazyload.html"
_LOADING_STUB = (
    "<html><head><title>A systematic approach for developing a corpus of "
    "patient reported adverse drug events</title></head><body>"
    '<header><h1>A systematic approach for developing a corpus of patient '
    "reported adverse drug events</h1></header>"
    '<section class="Body">Loading...</section></body></html>'
)


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


# --- a per-URL *save* failure is quarantined honestly, not as a session error ---
# (Codex P2: the broad batch handler must not mask a filesystem/manifest write
#  failure as "browser session failed" — that hides a data-integrity problem.)


def test_batch_save_failure_is_labelled_save_not_session(tmp_path: Path):
    # files_dir is actually a *file*, so mkdir/write_text raises in the save path
    # (outside fetch_tab). It must quarantine this URL as a save failure, not be
    # mislabelled by the session-open handler.
    blocker = tmp_path / "files"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    browser_fetch_batch(
        [OK_URL],
        files_dir=blocker,
        manifest_path=manifest,
        probe_cdp=_reached,
        open_session=_fake_session(BODY),
    )
    reason = _records(manifest)[0]["reason"]
    assert "save failed" in reason and "session" not in reason


def test_batch_save_failure_saves_no_path(tmp_path: Path):
    blocker = tmp_path / "files"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    result = browser_fetch_batch(
        [OK_URL],
        files_dir=blocker,
        manifest_path=tmp_path / "manifest.jsonl",
        probe_cdp=_reached,
        open_session=_fake_session(BODY),
    )
    assert result == []


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


_NO_SLEEP = lambda _s: None  # keep the bounded settle free in unit tests


def test_fetch_on_new_tab_returns_the_rendered_content():
    page = _FakePage(BODY[OK_URL])
    assert (
        _fetch_on_new_tab(_FakeContext(page), OK_URL, timeout_ms=30000, sleep=_NO_SLEEP)
        == BODY[OK_URL]
    )


def test_fetch_on_new_tab_closes_the_finished_tab():
    page = _FakePage(BODY[OK_URL])
    _fetch_on_new_tab(_FakeContext(page), OK_URL, timeout_ms=30000, sleep=_NO_SLEEP)
    assert page.closed is True


def test_fetch_on_new_tab_leaves_the_context_open_for_the_next_url():
    page = _FakePage(BODY[OK_URL])
    ctx = _FakeContext(page)
    _fetch_on_new_tab(ctx, OK_URL, timeout_ms=30000, sleep=_NO_SLEEP)
    assert ctx.closed is False


# --- US40 AC1: the settle wait is domcontentloaded, never networkidle ---


def test_fetch_on_new_tab_waits_on_domcontentloaded_not_networkidle():
    # A heavy publisher SPA never reaches network idle (blocker #1); the settle
    # signal it *does* reach is domcontentloaded.
    page = _FakePage(BODY[OK_URL])
    _fetch_on_new_tab(_FakeContext(page), OK_URL, timeout_ms=30000, sleep=_NO_SLEEP)
    assert page.goto_args[1] == "domcontentloaded"


def test_fetch_on_new_tab_settles_before_probing():
    # AC1's "domcontentloaded + a bounded settle": an ordinary page (no lazy-load
    # container) must still get one settle sleep before it is accepted as ready, so
    # early client-side JS runs (US15 pages are not captured as an under-rendered
    # shell now that networkidle is gone).
    from paper_degist.browser_fetch import _SETTLE_S

    slept = []
    _fetch_on_new_tab(
        _FakeContext(_FakePage(BODY[OK_URL])), OK_URL, timeout_ms=30000, sleep=slept.append
    )
    assert _SETTLE_S in slept


# ======================================================================== #
# US40 — the live readiness/interactive capture loop (_await_ready_body)
# ======================================================================== #
#
# The loop drives an already-navigated page: read content, classify (wall? body
# loaded?), and — while not ready — scroll-nudge the lazy-loader and poll. In
# interactive mode a detected wall notifies once and the loop keeps polling until
# the human clears it; in unattended mode a wall (or a body that never fills within
# the bound) returns immediately so the caller quarantines and the batch never
# blocks. sleep/notify are injected so the loop runs instantly and silently.


class _ScriptedPage:
    """A page whose content() walks a scripted sequence; records scroll nudges."""

    def __init__(self, contents):
        self._contents = list(contents)
        self._i = 0
        self.scrolls = 0
        self.goto_args = None

    def goto(self, url, *, wait_until, timeout):
        self.goto_args = (url, wait_until, timeout)

    def content(self):
        html = self._contents[min(self._i, len(self._contents) - 1)]
        self._i += 1
        return html

    def evaluate(self, script):
        if "scroll" in script.lower():
            self.scrolls += 1
        return None


def _await(page, url, **kw):
    from paper_degist.browser_fetch import _await_ready_body

    kw.setdefault("sleep", lambda _s: None)  # no real waiting in tests
    kw.setdefault("notify", lambda _m: None)
    kw.setdefault("poll_s", 3)
    kw.setdefault("max_wait_s", 30)
    kw.setdefault("interactive", False)
    return _await_ready_body(page, url, **kw)


_FILLED = _LAZYLOAD_SAMPLE.read_text(encoding="utf-8") if _LAZYLOAD_SAMPLE.exists() else ""


def test_await_returns_immediately_when_the_body_is_already_ready():
    # An ordinary page (no lazy-load container) is ready on the first probe — the
    # loop returns it without a single scroll nudge.
    page = _ScriptedPage([RENDERED])
    assert _await(page, OK_URL) == RENDERED


def test_await_does_not_scroll_a_page_that_is_already_ready():
    page = _ScriptedPage([RENDERED])
    _await(page, OK_URL)
    assert page.scrolls == 0


def test_await_scroll_nudges_a_stub_until_the_body_fills():
    # The body container shows "Loading…" then fills after a scroll — the loop
    # returns the *filled* HTML, not the stub (AC2).
    page = _ScriptedPage([_LOADING_STUB, _FILLED])
    assert _await(page, _LAZYLOAD_URL) == _FILLED


def test_await_scroll_nudges_at_least_once_before_the_body_fills():
    page = _ScriptedPage([_LOADING_STUB, _FILLED])
    _await(page, _LAZYLOAD_URL)
    assert page.scrolls >= 1


def test_await_unattended_returns_a_wall_immediately_for_quarantine():
    # Default (batch) mode never waits on a human: a wall is handed straight back
    # so the caller quarantines it and the batch moves on (AC4).
    page = _ScriptedPage([CLOUDFLARE_WALL])
    assert _await(page, WALL_URL, interactive=False) == CLOUDFLARE_WALL


def test_await_unattended_does_not_notify_on_a_wall():
    notes = []
    page = _ScriptedPage([CLOUDFLARE_WALL])
    _await(page, WALL_URL, interactive=False, notify=notes.append)
    assert notes == []


def test_await_interactive_resumes_once_the_wall_is_cleared():
    # The operator clears the wall by hand between polls; the loop auto-resumes and
    # returns the now-loaded body (AC3).
    page = _ScriptedPage([CLOUDFLARE_WALL, CLOUDFLARE_WALL, _FILLED])
    assert _await(page, _LAZYLOAD_URL, interactive=True) == _FILLED


def test_await_interactive_notifies_once_on_a_wall():
    notes = []
    page = _ScriptedPage([CLOUDFLARE_WALL, _FILLED])
    _await(page, _LAZYLOAD_URL, interactive=True, notify=notes.append)
    assert len(notes) == 1


def test_await_returns_the_stub_when_the_body_never_fills_within_the_bound():
    # The body never reaches the threshold before max_wait_s — the loop hands the
    # last stub back so the caller quarantines it (never hangs, AC4).
    page = _ScriptedPage([_LOADING_STUB])
    assert _await(page, _LAZYLOAD_URL, poll_s=3, max_wait_s=9) == _LOADING_STUB


def test_await_polls_a_publisher_shell_until_the_body_renders():
    # The live QA case: the first probe is an unrendered ScienceDirect shell (no
    # container) — the loop must keep polling, not return the empty shell, and
    # resume once the body renders.
    page = _ScriptedPage([_SD_SHELL, _SD_SHELL, _FILLED])
    assert _await(page, _LAZYLOAD_URL) == _FILLED


def test_await_does_not_return_the_unrendered_shell_immediately():
    page = _ScriptedPage([_SD_SHELL, _FILLED])
    _await(page, _LAZYLOAD_URL)
    assert page.scrolls >= 1  # it scroll-nudged instead of accepting the shell


class _FlakyPage:
    """A page whose content() raises a transient once, then walks a sequence.

    Models Playwright's "execution context was destroyed" while a redirect is in
    flight (or the operator navigates to clear the wall) — the loop must treat it as
    still-loading and keep polling, not abort the capture.
    """

    def __init__(self, contents, *, raises=1):
        self._contents = list(contents)
        self._i = 0
        self._raises = raises

    def content(self):
        if self._raises > 0:
            self._raises -= 1
            raise RuntimeError("Execution context was destroyed, most likely because of a navigation")
        html = self._contents[min(self._i, len(self._contents) - 1)]
        self._i += 1
        return html

    def evaluate(self, script):
        return None


def test_await_survives_a_transient_content_error_and_resumes():
    # content() raises once (redirect in flight), then the body is ready — the loop
    # keeps polling instead of propagating the error (navigation-resilient, AC3).
    page = _FlakyPage([_FILLED], raises=1)
    assert _await(page, _LAZYLOAD_URL, interactive=True) == _FILLED


def test_await_reraises_a_persistent_content_error_at_the_bound():
    # If the page never yields content within the bound, the error propagates so the
    # caller quarantines it as a navigation failure — never returns empty/None.
    import pytest

    page = _FlakyPage([_FILLED], raises=100)
    with pytest.raises(RuntimeError):
        _await(page, _LAZYLOAD_URL, poll_s=3, max_wait_s=9)


# ======================================================================== #
# US35 — detect a wall page captured instead of the paper (_wall_reason)
# ======================================================================== #
#
# browser-fetch trusts whatever Chrome renders, so a login / consent / Cloudflare
# wall renders *successfully* and is saved as if it were the paper. _wall_reason
# classifies the rendered HTML on two cheap deterministic signals — a known wall
# marker, or a <title> that shares no content token with the requested URL's
# paper slug — so the caller quarantines *before* the save (the wall never
# becomes the sticky idempotent artifact).

# The AC's URLs, each distinct and self-describing (rule 08).
WALL_URL = "https://www.researchgate.net/publication/221609650_Retrieval_Practice_Produces_More_Learning"
MISMATCH_URL = "https://www.academia.edu/38654201/Distributed_Practice_in_Verbal_Recall_Tasks"

# A Cloudflare challenge page (AC1): renders fine, carries the challenge script,
# and its <title> is the CF interstitial — not the requested paper.
CLOUDFLARE_WALL = (
    "<html><head><title>Just a moment...</title></head><body>"
    '<div class="cf-wrapper"><script src="/cdn-cgi/challenge-platform/h/b/orchestrate">'
    "</script></div></body></html>"
)

# A page that renders a *different* paper than the one requested (AC2): no wall
# marker, but the <title> shares no content word with MISMATCH_URL's slug.
WRONG_PAPER = (
    "<html><head><title>The Psychology of Everyday Things | ResearchGate</title></head>"
    "<body><h1>The Psychology of Everyday Things</h1></body></html>"
)

# The genuine paper (AC3): the rendered <title> echoes the requested slug.
GENUINE_PAPER = (
    "<html><head><title>Retrieval Practice Produces More Learning</title></head>"
    "<body><h1>Retrieval Practice Produces More Learning</h1></body></html>"
)


# --- AC1: a known Cloudflare wall marker → a wall reason ---


def test_wall_reason_flags_a_cloudflare_challenge_marker():
    # A challenge page whose <title> happens to echo the requested paper (so both
    # title checks abstain) is still caught by the challenge-widget blob in its body
    # — the marker path, isolated from the title path so it fails alone if a
    # challenge-specific marker is dropped.
    marker_only = (
        "<html><head><title>Retrieval Practice Produces More Learning</title></head>"
        "<body><script>window._cf_chl_opt={cvId:'3'};</script></body></html>"
    )
    assert _wall_reason(WALL_URL, marker_only) is not None


# --- AC2: a rendered title that reflects no content word of the URL slug → wall ---


def test_wall_reason_flags_a_title_that_does_not_reflect_the_url():
    assert _wall_reason(MISMATCH_URL, WRONG_PAPER) is not None


# --- AC3: a genuine paper whose title echoes the requested slug → not a wall ---


def test_wall_reason_passes_a_genuine_paper_page():
    assert _wall_reason(WALL_URL, GENUINE_PAPER) is None


# --- safe abstain: no <title> to judge, and no wall marker → not flagged ---


def test_wall_reason_abstains_when_the_page_has_no_title():
    titleless = "<html><body><h1>Distributed Practice in Verbal Recall Tasks</h1></body></html>"
    assert _wall_reason(MISMATCH_URL, titleless) is None


# --- safe abstain: an id-only slug carries no content token to compare ---


def test_wall_reason_abstains_on_an_id_only_url_slug():
    # arXiv's numeric slug (1706.03762) has no content word, so even a differing
    # title cannot be judged a mismatch — the safe direction (no false quarantine).
    arxiv = "https://arxiv.org/abs/1706.03762"
    other_title = "<html><head><title>An Unrelated Survey</title></head><body>x</body></html>"
    assert _wall_reason(arxiv, other_title) is None


def test_url_content_tokens_drop_the_numeric_id_and_stopwords():
    assert _url_content_tokens(WALL_URL) == frozenset(
        {"retrieval", "practice", "produces", "more", "learning"}
    )


def test_rendered_title_reads_the_title_from_an_html_string():
    assert _rendered_title(GENUINE_PAPER) == "Retrieval Practice Produces More Learning"


# --- AC1/AC4: a wall capture is quarantined *before* the save (never sticky) ---


def test_wall_capture_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, url=WALL_URL, fetch_rendered=_render(CLOUDFLARE_WALL))
    assert result is None


def test_wall_capture_saves_no_file(tmp_path: Path):
    # The check runs before write_text, so the wall never becomes the idempotent
    # "already saved" artifact of AC4 — a later logged-in run can recapture it.
    _, files, _ = _run(tmp_path, url=WALL_URL, fetch_rendered=_render(CLOUDFLARE_WALL))
    assert not files.exists()


def test_wall_capture_reason_flags_a_wall(tmp_path: Path):
    _, _, manifest = _run(tmp_path, url=WALL_URL, fetch_rendered=_render(CLOUDFLARE_WALL))
    assert "wall" in _only_record(manifest)["reason"]


def test_wall_capture_reason_is_distinct_from_a_nav_failure(tmp_path: Path):
    # The manifest must tell "captured a wall" apart from "browser could not load".
    _, _, wall_m = _run(tmp_path / "wall", url=WALL_URL, fetch_rendered=_render(CLOUDFLARE_WALL))
    _, _, nav_m = _run(tmp_path / "nav", url=NAV_FAIL_URL, fetch_rendered=_boom)
    assert _only_record(wall_m)["reason"] != _only_record(nav_m)["reason"]


# --- Codex review: tighten the false-positive surface (AC3 is the priority) ---


def test_wall_reason_ignores_an_interstitial_phrase_in_body_prose():
    # A real paper page whose *body* prose contains "just a moment..." (title still
    # reflects the slug) is not a wall — phrase markers match the <title>, not
    # arbitrary body text (Codex: whole-HTML scan false-positive).
    page = (
        "<html><head><title>Retrieval Practice Produces More Learning</title></head>"
        "<body><p>Wait just a moment... the retrieval effect is robust.</p></body></html>"
    )
    assert _wall_reason(WALL_URL, page) is None


def test_wall_reason_flags_a_cloudflare_interstitial_title():
    # A challenge page whose <title> is the interstitial but which carries no
    # challenge *script* is still caught — via the title marker.
    page = "<html><head><title>Just a moment...</title></head><body>x</body></html>"
    assert _wall_reason(WALL_URL, page) is not None


def test_wall_reason_ignores_a_noscript_javascript_notice():
    # "enable javascript and cookies to continue" is legit boilerplate on many
    # pages; dropping it as a marker means a real, correctly-titled paper carrying
    # it is not flagged (Codex: over-broad marker).
    page = (
        "<html><head><title>Retrieval Practice Produces More Learning</title></head>"
        "<body><noscript>Please enable JavaScript and cookies to continue.</noscript>"
        "<h1>Retrieval Practice Produces More Learning</h1></body></html>"
    )
    assert _wall_reason(WALL_URL, page) is None


def test_wall_reason_abstains_on_a_generic_repository_basename():
    # A non-descriptive CGI/repository basename (viewcontent.cgi) carries no
    # paper-identifying token, so a differing title must not be judged a wall
    # (Codex: false-positive on DOI/repository basenames).
    cgi_url = "https://rdw.rowan.edu/cgi/viewcontent.cgi?article=1080&context=etd"
    other = "<html><head><title>Rowan University Digital Works Home</title></head><body>x</body></html>"
    assert _wall_reason(cgi_url, other) is None


# ======================================================================== #
# US40 — capture lazy-loaded full-text through an interactive wall
# ======================================================================== #
#
# Between "the DOM settled" and "save", browser-fetch now also gates on whether
# the lazy-loaded body has actually filled: _body_word_count reads the real word
# count of the publisher's body container (ScienceDirect / Elsevier), and
# _readiness_reason turns a "Loading…" stub into a quarantine — while *abstaining*
# on an ordinary page that has no such container (so every US15/US35 page still
# saves as before). The threshold is pinned against a synthetic full-text fixture.

# --- pure readiness signal: real word count of the lazy-load body container ---


def test_body_word_count_of_a_filled_body_exceeds_the_threshold():
    from paper_degist.browser_fetch import _body_word_count, READY_WORDS

    assert _body_word_count(_LAZYLOAD_SAMPLE.read_text(encoding="utf-8")) > READY_WORDS


def test_body_word_count_of_a_loading_placeholder_is_zero():
    from paper_degist.browser_fetch import _body_word_count

    assert _body_word_count(_LOADING_STUB) == 0


def test_body_word_count_is_minus_one_when_no_lazy_load_container():
    # An ordinary paper page (US15) has none of the publisher body selectors, so
    # the readiness gate must abstain — signalled by -1.
    from paper_degist.browser_fetch import _body_word_count

    assert _body_word_count(RENDERED) == -1


# --- readiness gate: a stub quarantines, a filled body / ordinary page passes ---


def test_readiness_reason_passes_a_filled_body():
    from paper_degist.browser_fetch import _readiness_reason

    assert _readiness_reason(_LAZYLOAD_SAMPLE.read_text(encoding="utf-8")) is None


def test_readiness_reason_flags_a_loading_stub():
    from paper_degist.browser_fetch import _readiness_reason

    assert _readiness_reason(_LOADING_STUB) is not None


def test_readiness_reason_abstains_on_an_ordinary_page_without_a_container():
    # No lazy-load container ⇒ abstain, so every US15/US35 page still saves.
    from paper_degist.browser_fetch import _readiness_reason

    assert _readiness_reason(RENDERED) is None


# An unrendered ScienceDirect/Elsevier SPA shell (caught by the live QA run): a
# publisher marker is present, the <title> is the bare host, and the body has NOT
# rendered — no article container, empty <body>. Distinct from an ordinary page:
# here "no container" means "still loading", not "nothing to wait for".
_SD_SHELL = (
    "<html><head><title>ScienceDirect</title>"
    '<meta name="tdm-policy" content="https://www.elsevier.com/tdm/tdmrep-policy.json">'
    '<script src="https://sdfestaticassets-us-east-1.sciencedirectassets.com/app.js"></script>'
    '</head><body><div id="app"></div></body></html>'
)


def test_readiness_reason_flags_an_unrendered_publisher_shell():
    # A ScienceDirect shell with no article body yet must NOT be saved — the gate
    # must not abstain the way it does for an ordinary container-less page.
    from paper_degist.browser_fetch import _readiness_reason

    assert _readiness_reason(_SD_SHELL) is not None


def test_is_lazyload_publisher_detects_a_sciencedirect_shell():
    from paper_degist.browser_fetch import _is_lazyload_publisher

    assert _is_lazyload_publisher(_SD_SHELL) is True


def test_is_lazyload_publisher_is_false_for_an_ordinary_page():
    from paper_degist.browser_fetch import _is_lazyload_publisher

    assert _is_lazyload_publisher(RENDERED) is False


# --- DOI-slug abstain: a DOI carries no judgeable title token (so it never
#     false-quarantines a real ScienceDirect capture before the readiness gate) ---


def test_wall_reason_abstains_on_a_doi_url_slug():
    # doi.org/10.1016/j.jbi.2018.12.005 → slug tokens {jbi, j} are a journal
    # abbreviation, not title words; a real article title shares none of them, so
    # the title-mismatch heuristic must abstain (the safe direction), not quarantine.
    doi = "https://doi.org/10.1016/j.jbi.2018.12.005"
    real = (
        "<html><head><title>A systematic approach for developing a corpus of "
        "patient reported adverse drug events</title></head><body>x</body></html>"
    )
    assert _wall_reason(doi, real) is None


def test_wall_reason_still_flags_a_cloudflare_marker_on_a_doi_url():
    # Abstaining on the DOI *slug* must not blind the wall check to a genuine
    # Cloudflare challenge — the body/title markers still fire (AC3 relies on this).
    doi = "https://doi.org/10.1016/j.jbi.2018.12.005"
    assert _wall_reason(doi, CLOUDFLARE_WALL) is not None


def test_wall_reason_passes_a_cleared_page_carrying_the_jsd_telemetry_script():
    # LIVE QA (US40): a *cleared* ScienceDirect article still carries Cloudflare's
    # generic JS-Detections telemetry script (/cdn-cgi/challenge-platform/scripts/jsd/)
    # — Cloudflare injects it into ordinary pages, not only interstitials. It must
    # NOT read as a wall: its <title> echoes the paper and it carries no challenge
    # blob. Otherwise the --interactive loop polls forever after the human clears the
    # wall (the article had loaded, yet _wall_reason kept flagging the page).
    doi = "https://doi.org/10.1016/j.jbi.2018.12.005"
    cleared = (
        "<html><head><title>A systematic approach for developing a corpus of "
        "patient reported adverse drug events - ScienceDirect</title>"
        '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>'
        '</head><body><section class="Body">full rendered article text</section>'
        "</body></html>"
    )
    assert _wall_reason(doi, cleared) is None


# --- AC2: a "Loading…" stub is quarantined before the save, not saved header-only ---

_LAZYLOAD_URL = "https://doi.org/10.1016/j.artmed.2021.102083"


def test_stub_capture_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, url=_LAZYLOAD_URL, fetch_rendered=_render(_LOADING_STUB))
    assert result is None


def test_stub_capture_saves_no_file(tmp_path: Path):
    # The gate runs before write_text, so the stub never becomes the sticky
    # idempotent artifact — a later scroll-nudged run can capture the full body.
    _, files, _ = _run(tmp_path, url=_LAZYLOAD_URL, fetch_rendered=_render(_LOADING_STUB))
    assert not files.exists()


def test_stub_capture_reason_names_the_unloaded_body(tmp_path: Path):
    _, _, manifest = _run(tmp_path, url=_LAZYLOAD_URL, fetch_rendered=_render(_LOADING_STUB))
    assert "not loaded" in _only_record(manifest)["reason"]


def test_filled_lazyload_body_is_saved(tmp_path: Path):
    # A fully-loaded ScienceDirect body (container above the threshold) passes the
    # readiness gate and saves, exactly as an ordinary page does.
    html = _LAZYLOAD_SAMPLE.read_text(encoding="utf-8")
    result, _, _ = _run(tmp_path, url=_LAZYLOAD_URL, fetch_rendered=_render(html))
    assert result is not None
