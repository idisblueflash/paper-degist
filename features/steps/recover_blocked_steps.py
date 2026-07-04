"""US17 — recover-blocked routes the manifest's blocked_by URLs into the browser.

recover-blocked is deterministic, offline routing: it reads the append-only
manifest, selects the ``blocked_by`` records not yet recovered, and hands their
URLs to browser-fetch's warm-batch path (US16). These steps drive the **real**
join — ``recover_blocked`` over the **real** ``browser_fetch_batch`` — faking
only Chrome (an injected probe + one-warm-session ``open_session``, the same
shape as ``browser_fetch_batch_steps``), so the manifest read, the select, and
the delegate are all exercised end to end.

Step phrases are deliberately distinct from ``browser_fetch_batch_steps.py``
(behave shares one step registry): these say "for the recovery lane" and "routes
the blocked records" rather than redefining the batch phrases (rule 06 phase 5).
"""

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

from behave import given, then, when

from paper_degist import _manifest
from paper_degist.browser_fetch import _target_path, browser_fetch_batch
from paper_degist.recover_blocked import recover_blocked


def _rb_ctx(context):
    """Lazily seed the recover-blocked fixture: a fresh manifest and empty tallies."""
    if not getattr(context, "rb_ready", False):
        workdir = Path(tempfile.mkdtemp())
        context.rb_files = workdir / "files"
        context.rb_manifest = workdir / "manifest.jsonl"
        context.rb_cdp = "http://localhost:9222"
        context.rb_reachable = True
        context.rb_opens = 0  # warm connections opened
        context.rb_fetched = []  # URLs the browser lane actually fetched
        context.rb_ready = True
    return context


def _slug(url):
    return _target_path(url, Path("files")).name


@given("a manifest of fetch-one quarantines:")
def step_seed_manifest(context):
    _rb_ctx(context)
    context.rb_urls = []
    for row in context.table:
        url = row["url"]
        context.rb_urls.append(url)
        blocked_by = (row["blocked_by"] or "").strip()
        fields = {"url": url, "status": 403}
        if blocked_by:
            fields["blocked_by"] = blocked_by
        else:
            fields["reason"] = "http 403"  # a generic quarantine, not this lane
        _manifest.append(context.rb_manifest, stage="fetch-one", **fields)


@given("that URL was already recovered by browser-fetch in a prior run")
def step_prior_recovery(context):
    _rb_ctx(context)
    url = context.rb_urls[0]
    target = context.rb_files / _slug(url)
    _manifest.append(
        context.rb_manifest,
        stage="browser-fetch",
        url=url,
        result="saved",
        path=str(target),
    )


@given("a warm dev-mode Chrome for the recovery lane")
def step_warm_chrome(context):
    _rb_ctx(context)
    context.rb_reachable = True


@given("no dev-mode Chrome for the recovery lane")
def step_no_chrome(context):
    _rb_ctx(context)
    context.rb_reachable = False


def _batch(context):
    """The real browser_fetch_batch with only Chrome faked (probe + warm session)."""

    @contextmanager
    def _open(cdp_url, **_kw):
        context.rb_opens += 1  # one warm connection for the whole list

        def fetch_tab(url):
            context.rb_fetched.append(url)
            return f"<html><body>{url}</body></html>"  # rendered page (rule 08)

        yield fetch_tab

    def _fetch_batch(urls, **kwargs):
        return browser_fetch_batch(
            urls,
            probe_cdp=lambda cdp: context.rb_reachable,
            open_session=_open,
            **kwargs,
        )

    return _fetch_batch


@when("recover-blocked routes the blocked records")
def step_route(context):
    context.rb_result = recover_blocked(
        context.rb_manifest,
        cdp_url=context.rb_cdp,
        files_dir=context.rb_files,
        fetch_batch=_batch(context),
    )


def _records(context):
    text = context.rb_manifest.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@then("only the blocked_by URLs are dispatched to browser-fetch")
def step_only_blocked_dispatched(context):
    expected = [u for u in context.rb_urls if "example.edu" not in u]
    assert context.rb_fetched == expected, f"{context.rb_fetched} != {expected}"


@then("the generic quarantine URL is not dispatched")
def step_generic_not_dispatched(context):
    generic = [u for u in context.rb_urls if "example.edu" in u]
    assert generic and all(u not in context.rb_fetched for u in generic), context.rb_fetched


@then("the browser lane opens exactly one warm connection for the batch")
def step_one_connection(context):
    assert context.rb_opens == 1, context.rb_opens


@then("a new browser-fetch recovery record is appended for that URL")
def step_recovery_record(context):
    url = context.rb_urls[0]
    saved = [r for r in _records(context)
             if r.get("stage") == "browser-fetch" and r.get("url") == url and r.get("result") == "saved"]
    assert saved, f"no browser-fetch saved record for {url}; records={_records(context)}"


@then("the original blocked_by record is still present unchanged")
def step_original_untouched(context):
    url = context.rb_urls[0]
    original = [r for r in _records(context)
                if r.get("stage") == "fetch-one" and r.get("url") == url and r.get("blocked_by")]
    assert len(original) == 1 and original[0]["status"] == 403, original


@then("that URL stays quarantined with a missing-browser reason")
def step_missing_browser(context):
    url = context.rb_urls[0]
    quarantined = [r for r in _records(context)
                   if r.get("stage") == "browser-fetch" and r.get("url") == url
                   and "no dev-mode browser" in r.get("reason", "")]
    assert quarantined, f"no missing-browser quarantine for {url}; records={_records(context)}"


@then("recover-blocked recovers nothing and does not crash")
def step_recovers_nothing(context):
    assert context.rb_result == [], context.rb_result


@then("that URL is not dispatched to browser-fetch again")
def step_not_redispatched(context):
    url = context.rb_urls[0]
    assert url not in context.rb_fetched, context.rb_fetched
