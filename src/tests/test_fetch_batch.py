"""Unit tests for US37 fetch_batch (pytest) — driven one test at a time (rule 05).

fetch_batch drives fetch_one over a candidates JSONL and writes a provenance
sidecar next to each saved file. It is exercised offline by injecting the same
fake ``fetch`` callable fetch_one uses, so no test touches the network.
"""

import json
from pathlib import Path

from paper_degist import _frontmatter
from paper_degist.fetch_batch import fetch_batch


class FakeResponse:
    """Minimal stand-in for an ``httpx.Response`` — just what fetch_one reads."""

    def __init__(self, *, status_code=200, content_type="", content=b""):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = content


PDF = FakeResponse(content_type="application/pdf", content=b"%PDF-1.7 data")
FORBIDDEN = FakeResponse(status_code=403, content_type="text/html", content=b"no")


def _write_candidates(tmp_path: Path, records: list[dict]) -> Path:
    path = tmp_path / "candidates.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def _run(tmp_path, records, *, fetch):
    """Arrange a fresh files/ + manifest and run fetch_batch; return the trio."""
    candidates = _write_candidates(tmp_path, records)
    files = tmp_path / "files"
    manifest = tmp_path / "manifest.jsonl"
    saved = fetch_batch(candidates, files_dir=files, manifest_path=manifest, fetch=fetch)
    return saved, files, manifest


def _records(manifest: Path) -> list[dict]:
    return [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]


# ---------------------------------------------------------------------------
# AC1 — each fetched paper gets a provenance sidecar
# ---------------------------------------------------------------------------

def test_writes_a_sidecar_next_to_the_saved_file(tmp_path):
    saved, _files, _m = _run(
        tmp_path,
        [{"url": "https://arxiv.org/pdf/2602.00762.pdf", "doi": "10.5555/smart"}],
        fetch=lambda url: PDF,
    )
    assert _frontmatter.sidecar_path(saved[0]).exists()


def test_sidecar_carries_the_records_doi(tmp_path):
    saved, _files, _m = _run(
        tmp_path,
        [{"url": "https://arxiv.org/pdf/2602.00762.pdf", "doi": "10.5555/smart",
          "pdf_url": "https://arxiv.org/pdf/2602.00762.pdf", "venue": "arXiv preprint"}],
        fetch=lambda url: PDF,
    )
    assert _frontmatter.load_sidecar(saved[0])["doi"] == "10.5555/smart"


def test_sidecar_missing_field_is_null(tmp_path):
    saved, _files, _m = _run(
        tmp_path,
        [{"url": "https://arxiv.org/pdf/2602.00762.pdf"}],  # no doi
        fetch=lambda url: PDF,
    )
    assert _frontmatter.load_sidecar(saved[0])["doi"] is None


# ---------------------------------------------------------------------------
# AC2 — a URL that quarantines in fetch_one gets no sidecar; batch continues
# ---------------------------------------------------------------------------

def test_quarantined_url_writes_no_sidecar(tmp_path):
    _saved, files, _m = _run(
        tmp_path,
        [{"url": "https://www.ncbi.nlm.nih.gov/pubmed/123", "doi": "10.1/walled"}],
        fetch=lambda url: FORBIDDEN,
    )
    assert list(files.glob("*.meta.json")) == []


def test_batch_continues_past_a_quarantined_url(tmp_path):
    saved, _files, _m = _run(
        tmp_path,
        [
            {"url": "https://www.ncbi.nlm.nih.gov/pubmed/123"},           # 403 → quarantine
            {"url": "https://arxiv.org/pdf/2602.00762.pdf"},              # ok → saved
        ],
        fetch=lambda url: FORBIDDEN if "ncbi" in url else PDF,
    )
    assert [p.name for p in saved] == ["2602.00762.pdf"]


# ---------------------------------------------------------------------------
# AC3 — a record with no url is quarantined to stage fetch-batch, never crashes
# ---------------------------------------------------------------------------

def test_record_without_url_is_quarantined_to_fetch_batch(tmp_path):
    _saved, _files, manifest = _run(
        tmp_path,
        [{"doi": "10.1/no-url"}],
        fetch=lambda url: PDF,
    )
    assert _records(manifest)[0]["stage"] == "fetch-batch"


def test_record_without_url_does_not_stop_the_batch(tmp_path):
    saved, _files, _m = _run(
        tmp_path,
        [
            {"doi": "10.1/no-url"},                            # malformed → quarantine
            {"url": "https://arxiv.org/pdf/2602.00762.pdf"},   # ok → saved
        ],
        fetch=lambda url: PDF,
    )
    assert [p.name for p in saved] == ["2602.00762.pdf"]


def test_non_string_url_is_quarantined(tmp_path):
    _saved, _files, manifest = _run(
        tmp_path,
        [{"url": ["https://arxiv.org/pdf/2602.00762.pdf"]}],  # url is a list, not a str
        fetch=lambda url: PDF,
    )
    assert _records(manifest)[0]["stage"] == "fetch-batch"


def test_malformed_json_line_is_quarantined(tmp_path):
    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text("{not valid json\n", encoding="utf-8")
    files = tmp_path / "files"
    manifest = tmp_path / "manifest.jsonl"
    fetch_batch(candidates, files_dir=files, manifest_path=manifest, fetch=lambda url: PDF)
    assert _records(manifest)[0]["stage"] == "fetch-batch"
