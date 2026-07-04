"""US17 — recover-blocked: route bot-walled records into the browser lane.

recover-blocked reads the append-only ``manifest.jsonl``, selects the records
that carry a ``blocked_by`` host (fetch-one's US12 tag), and hands their URLs to
browser-fetch's warm-batch path (US16). It is deterministic, offline routing:
it filters the manifest and delegates the fetching — no browser logic, no LLM.

The classifier ``select_retry_urls`` is pure (a list of records → the retry
URLs), so the two-field classify (does it carry ``blocked_by``? already
recovered?) is exercised without a manifest file or a browser. The orchestrator
``recover_blocked`` injects a ``fetch_batch`` collaborator (default: the real
``browser_fetch_batch``) so the delegation is checked without a real Chrome —
the same injected-collaborator shape as ``browser_fetch`` / ``fetch_one``.

One assertion per test (rule 05): each fails for exactly one reason; shared
arrange/act lives in the helpers so the split never duplicates setup. Each
example URL is distinct and self-describing (rule 08).
"""

import json
from pathlib import Path

from paper_degist.recover_blocked import recover_blocked, select_retry_urls

# The two bot-walled hosts US12 names, plus a generic non-blocked quarantine —
# each URL's slug is its label (rule 08).
RG_URL = "https://www.researchgate.net/publication/287147155_The_Mnemonic_Keyword_Method"
PUBMED_URL = "https://pubmed.ncbi.nlm.nih.gov/2303742/"
GENERIC_URL = "https://example.edu/papers/some-closed-paper"


def _blocked(url, host):
    return {"stage": "fetch-one", "url": url, "status": 403, "blocked_by": host}


def _generic(url):
    return {"stage": "fetch-one", "url": url, "status": 403, "reason": "http 403"}


def _recovered(url):
    return {"stage": "browser-fetch", "url": url, "result": "saved", "path": f"files/{url[-8:]}.html"}


def test_selects_only_blocked_by_urls_ignoring_generic_quarantines():
    records = [
        _blocked(RG_URL, "researchgate.net"),
        _generic(GENERIC_URL),
    ]
    assert select_retry_urls(records) == [RG_URL]


def test_selects_every_blocked_host_in_first_seen_order():
    records = [
        _blocked(RG_URL, "researchgate.net"),
        _generic(GENERIC_URL),
        _blocked(PUBMED_URL, "pubmed.ncbi.nlm.nih.gov"),
    ]
    assert select_retry_urls(records) == [RG_URL, PUBMED_URL]


def test_skips_a_blocked_url_already_recovered_in_a_later_record():
    records = [
        _blocked(RG_URL, "researchgate.net"),
        _recovered(RG_URL),
        _blocked(PUBMED_URL, "pubmed.ncbi.nlm.nih.gov"),
    ]
    assert select_retry_urls(records) == [PUBMED_URL]


def test_deduplicates_a_url_blocked_across_two_runs():
    records = [
        _blocked(RG_URL, "researchgate.net"),
        _blocked(RG_URL, "researchgate.net"),
    ]
    assert select_retry_urls(records) == [RG_URL]


# --- orchestrator: recover_blocked over a manifest file, delegating a batch ----
#
# The batch is injected (default: the real ``browser_fetch_batch``) so the
# delegation is exercised without a real Chrome — the browser_fetch / fetch_one
# injected-collaborator shape. ``_recorder`` captures the dispatched call.


def _write_manifest(tmp_path, records):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return manifest


def _recorder(returns=None):
    """A fake browser_fetch_batch: record its call, return a fixed path list."""
    calls = []

    def _batch(urls, **kwargs):
        calls.append({"urls": list(urls), **kwargs})
        return list(returns or [])

    _batch.calls = calls
    return _batch


def test_dispatches_the_selected_blocked_urls_to_the_batch(tmp_path: Path):
    manifest = _write_manifest(tmp_path, [
        _blocked(RG_URL, "researchgate.net"),
        _generic(GENERIC_URL),
        _blocked(PUBMED_URL, "pubmed.ncbi.nlm.nih.gov"),
    ])
    batch = _recorder()
    recover_blocked(manifest, fetch_batch=batch)
    assert batch.calls[0]["urls"] == [RG_URL, PUBMED_URL]


def test_dispatches_the_whole_retry_set_in_one_warm_batch(tmp_path: Path):
    manifest = _write_manifest(tmp_path, [
        _blocked(RG_URL, "researchgate.net"),
        _blocked(PUBMED_URL, "pubmed.ncbi.nlm.nih.gov"),
    ])
    batch = _recorder()
    recover_blocked(manifest, fetch_batch=batch)
    assert len(batch.calls) == 1  # one Chrome for the whole list (AC2), not per URL


def test_returns_the_saved_paths_the_batch_reports(tmp_path: Path):
    manifest = _write_manifest(tmp_path, [_blocked(RG_URL, "researchgate.net")])
    saved = [Path("files/287147155_The_Mnemonic_Keyword_Method.html")]
    result = recover_blocked(manifest, fetch_batch=_recorder(returns=saved))
    assert result == saved


def test_passes_the_manifest_path_through_to_the_batch(tmp_path: Path):
    manifest = _write_manifest(tmp_path, [_blocked(RG_URL, "researchgate.net")])
    batch = _recorder()
    recover_blocked(manifest, fetch_batch=batch)
    assert batch.calls[0]["manifest_path"] == manifest


def test_passes_the_cdp_endpoint_through_to_the_batch(tmp_path: Path):
    manifest = _write_manifest(tmp_path, [_blocked(RG_URL, "researchgate.net")])
    batch = _recorder()
    recover_blocked(manifest, cdp_url="http://localhost:9333", fetch_batch=batch)
    assert batch.calls[0]["cdp_url"] == "http://localhost:9333"


def test_missing_manifest_dispatches_nothing(tmp_path: Path):
    batch = _recorder()
    recover_blocked(tmp_path / "absent.jsonl", fetch_batch=batch)
    assert batch.calls == []


def test_no_blocked_records_never_opens_a_batch(tmp_path: Path):
    manifest = _write_manifest(tmp_path, [_generic(GENERIC_URL)])
    batch = _recorder()
    recover_blocked(manifest, fetch_batch=batch)
    assert batch.calls == []


def test_tolerates_a_malformed_manifest_line_without_crashing(tmp_path: Path):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        json.dumps(_blocked(RG_URL, "researchgate.net")) + "\n" + "{ not json\n",
        encoding="utf-8",
    )
    batch = _recorder()
    recover_blocked(manifest, fetch_batch=batch)
    assert batch.calls[0]["urls"] == [RG_URL]
