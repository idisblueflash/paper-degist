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

from paper_degist.browser_fetch import _no_proxy_for, _target_path, browser_fetch

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
