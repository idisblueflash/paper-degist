"""Unit tests for US2 fetch_one (pytest).

fetch_one is exercised offline by injecting a fake ``fetch`` callable that
returns a response-shaped object (``status_code``, ``headers``, ``content``),
so no test touches the network — the workflow stays runnable offline (US2
design principle).
"""

import json
from pathlib import Path

from paper_degist.fetch_one import classify, fetch_one


class FakeResponse:
    """Minimal stand-in for an ``httpx.Response`` — just what fetch_one reads."""

    def __init__(self, *, status_code=200, content_type="", content=b""):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = content


def _fetch(response):
    """Return a fetch callable that always yields ``response``."""
    return lambda url: response


# --- classify: Content-Type first, byte sniff second ---


def test_classify_pdf_by_content_type():
    assert classify("application/pdf", b"") == "pdf"


def test_classify_pdf_by_content_type_with_charset_param():
    assert classify("application/pdf; charset=binary", b"") == "pdf"


def test_classify_pdf_by_byte_sniff_when_content_type_is_generic():
    assert classify("application/octet-stream", b"%PDF-1.7\n...") == "pdf"


def test_classify_html_by_content_type():
    assert classify("text/html; charset=utf-8", b"<html>") == "html"


def test_classify_unknown_returns_none():
    assert classify("application/json", b"{}") is None


# --- fetch_one: fetch, classify, save under files/ (AC2, AC3, AC4) ---


def test_saves_pdf_under_files_dir(tmp_path: Path):
    files = tmp_path / "files"
    resp = FakeResponse(content_type="application/pdf", content=b"%PDF-1.7 data")

    target = fetch_one(
        "https://arxiv.org/pdf/2602.00762",
        files_dir=files,
        fetch=_fetch(resp),
    )

    assert target == files / "2602.00762.pdf"
    assert target.read_bytes() == b"%PDF-1.7 data"


def test_saves_html_under_files_dir(tmp_path: Path):
    files = tmp_path / "files"
    resp = FakeResponse(content_type="text/html; charset=utf-8", content=b"<html>")

    target = fetch_one("https://example.com/paper", files_dir=files, fetch=_fetch(resp))

    assert target == files / "paper.html"
    assert target.read_bytes() == b"<html>"


def test_does_not_double_extension_when_basename_already_has_it(tmp_path: Path):
    files = tmp_path / "files"
    resp = FakeResponse(content_type="application/pdf", content=b"%PDF-")

    target = fetch_one("https://example.com/a.pdf", files_dir=files, fetch=_fetch(resp))

    assert target == files / "a.pdf"


def test_idempotent_skip_does_not_overwrite_existing_file(tmp_path: Path):
    files = tmp_path / "files"
    files.mkdir()
    (files / "a.pdf").write_bytes(b"original")
    resp = FakeResponse(content_type="application/pdf", content=b"%PDF- new")

    target = fetch_one("https://example.com/a.pdf", files_dir=files, fetch=_fetch(resp))

    assert target == files / "a.pdf"
    assert target.read_bytes() == b"original"  # untouched


# --- fetch_one: quarantine, never crash (AC6) ---


def _manifest_records(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_unknown_content_type_is_quarantined_and_returns_none(tmp_path: Path):
    files = tmp_path / "files"
    manifest = tmp_path / "manifest.jsonl"
    resp = FakeResponse(content_type="application/json", content=b"{}")

    target = fetch_one(
        "https://example.com/thing",
        files_dir=files,
        manifest_path=manifest,
        fetch=_fetch(resp),
    )

    assert target is None
    assert not files.exists()  # nothing saved
    (record,) = _manifest_records(manifest)
    assert record["url"] == "https://example.com/thing"
    assert record["content_type"] == "application/json"
    assert record["status"] == 200
    assert "reason" in record


def test_http_error_status_is_quarantined(tmp_path: Path):
    files = tmp_path / "files"
    manifest = tmp_path / "manifest.jsonl"
    resp = FakeResponse(status_code=403, content_type="text/html", content=b"nope")

    target = fetch_one(
        "https://example.com/paywalled",
        files_dir=files,
        manifest_path=manifest,
        fetch=_fetch(resp),
    )

    assert target is None
    (record,) = _manifest_records(manifest)
    assert record["status"] == 403


def test_fetch_exception_is_quarantined_not_raised(tmp_path: Path):
    files = tmp_path / "files"
    manifest = tmp_path / "manifest.jsonl"

    def boom(url):
        raise TimeoutError("connection timed out")

    target = fetch_one(
        "https://example.com/slow",
        files_dir=files,
        manifest_path=manifest,
        fetch=boom,
    )

    assert target is None
    (record,) = _manifest_records(manifest)
    assert record["status"] is None
    assert "timed out" in record["reason"]
