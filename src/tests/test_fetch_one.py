"""Unit tests for US2 fetch_one (pytest).

One assertion per test: each test fails for exactly one reason, so a refactor
turns exactly the affected test red. Shared arrange/act lives in the helpers
below (``_run``/``_run_with_existing``) so the split does not duplicate setup.

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


PDF = FakeResponse(content_type="application/pdf", content=b"%PDF-1.7 data")
HTML = FakeResponse(content_type="text/html; charset=utf-8", content=b"<html>")
UNKNOWN = FakeResponse(content_type="application/json", content=b"{}")
FORBIDDEN = FakeResponse(status_code=403, content_type="text/html", content=b"no")


def _always(response):
    return lambda url: response


def _run(tmp_path, *, url, response=None, fetch=None):
    """Arrange a fresh files/ + manifest and run fetch_one; return the trio."""
    files = tmp_path / "files"
    manifest = tmp_path / "manifest.jsonl"
    result = fetch_one(
        url,
        files_dir=files,
        manifest_path=manifest,
        fetch=fetch or _always(response),
    )
    return result, files, manifest


def _run_with_existing(tmp_path, *, url, response, name, content):
    """Run fetch_one when ``files/<name>`` already holds ``content``."""
    files = tmp_path / "files"
    files.mkdir()
    (files / name).write_bytes(content)
    manifest = tmp_path / "manifest.jsonl"
    result = fetch_one(url, files_dir=files, manifest_path=manifest, fetch=_always(response))
    return result, files, manifest


def _only_record(manifest: Path):
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


# --- classify: Content-Type first, byte sniff second ---


def test_classify_pdf_by_content_type():
    assert classify("application/pdf", b"") == "pdf"


def test_classify_pdf_by_content_type_with_charset_param():
    assert classify("application/pdf; charset=binary", b"") == "pdf"


def test_classify_pdf_by_byte_sniff_when_content_type_is_generic():
    assert classify("application/octet-stream", b"%PDF-1.7 ...") == "pdf"


def test_classify_html_by_content_type():
    assert classify("text/html; charset=utf-8", b"<html>") == "html"


def test_classify_unknown_returns_none():
    assert classify("application/json", b"{}") is None


# --- save a PDF under files/ (AC2, AC3) ---


def test_saves_pdf_returns_expected_path(tmp_path: Path):
    result, files, _ = _run(tmp_path, url="https://arxiv.org/pdf/2602.00762", response=PDF)
    assert result == files / "2602.00762.pdf"


def test_saves_pdf_writes_response_bytes(tmp_path: Path):
    _, files, _ = _run(tmp_path, url="https://arxiv.org/pdf/2602.00762", response=PDF)
    assert (files / "2602.00762.pdf").read_bytes() == b"%PDF-1.7 data"


# --- save an HTML paper under files/ (AC4) ---


def test_saves_html_returns_expected_path(tmp_path: Path):
    result, files, _ = _run(tmp_path, url="https://example.com/paper", response=HTML)
    assert result == files / "paper.html"


def test_saves_html_writes_response_bytes(tmp_path: Path):
    _, files, _ = _run(tmp_path, url="https://example.com/paper", response=HTML)
    assert (files / "paper.html").read_bytes() == b"<html>"


# --- filename rule ---


def test_does_not_double_extension_when_basename_already_has_it(tmp_path: Path):
    result, files, _ = _run(tmp_path, url="https://example.com/a.pdf", response=PDF)
    assert result == files / "a.pdf"


# --- idempotent skip: an existing target is left untouched ---


def test_idempotent_skip_returns_existing_path(tmp_path: Path):
    result, files, _ = _run_with_existing(
        tmp_path, url="https://example.com/a.pdf", response=PDF, name="a.pdf", content=b"original"
    )
    assert result == files / "a.pdf"


def test_idempotent_skip_leaves_file_unchanged(tmp_path: Path):
    _, files, _ = _run_with_existing(
        tmp_path, url="https://example.com/a.pdf", response=PDF, name="a.pdf", content=b"original"
    )
    assert (files / "a.pdf").read_bytes() == b"original"


# --- quarantine an unrecognized Content-Type (AC6) ---


def test_unknown_type_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, url="https://example.com/thing", response=UNKNOWN)
    assert result is None


def test_unknown_type_saves_no_file(tmp_path: Path):
    _, files, _ = _run(tmp_path, url="https://example.com/thing", response=UNKNOWN)
    assert not files.exists()


def test_unknown_type_manifest_records_input(tmp_path: Path):
    _, _, manifest = _run(tmp_path, url="https://example.com/thing", response=UNKNOWN)
    record = _only_record(manifest)
    assert {k: record[k] for k in ("url", "status", "content_type")} == {
        "url": "https://example.com/thing",
        "status": 200,
        "content_type": "application/json",
    }


def test_unknown_type_manifest_records_a_reason(tmp_path: Path):
    _, _, manifest = _run(tmp_path, url="https://example.com/thing", response=UNKNOWN)
    assert _only_record(manifest)["reason"]


# --- quarantine an HTTP error status (AC6) ---


def test_http_error_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, url="https://example.com/paywalled", response=FORBIDDEN)
    assert result is None


def test_http_error_manifest_records_status(tmp_path: Path):
    _, _, manifest = _run(tmp_path, url="https://example.com/paywalled", response=FORBIDDEN)
    assert _only_record(manifest)["status"] == 403


# --- quarantine a fetch exception without raising (AC6) ---


def _boom(url):
    raise TimeoutError("connection timed out")


def test_fetch_exception_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, url="https://example.com/slow", fetch=_boom)
    assert result is None


def test_fetch_exception_manifest_records_null_status(tmp_path: Path):
    _, _, manifest = _run(tmp_path, url="https://example.com/slow", fetch=_boom)
    assert _only_record(manifest)["status"] is None


def test_fetch_exception_manifest_reason_mentions_the_error(tmp_path: Path):
    _, _, manifest = _run(tmp_path, url="https://example.com/slow", fetch=_boom)
    assert "timed out" in _only_record(manifest)["reason"]
