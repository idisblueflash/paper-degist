"""Unit tests for US5 convert_html (pytest).

One assertion per test (rule 05): each test fails for exactly one reason, so a
refactor turns exactly the affected test red. The structure-preservation claim
(AC1) is one fact per structure — a heading test, a list test, a table test, a
code test — never one bundle.
"""

import json
from pathlib import Path

from paper_degist.convert_html import convert_html, html_to_markdown


# A content-rich body that clears the density threshold (a real paper's shape).
_PAPER_BODY = "<h1>Title</h1><p>" + "lorem ipsum dolor sit amet " * 40 + "</p>"


def _write_html(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return path


def _run(tmp_path: Path, *, name="paper.html", body=_PAPER_BODY):
    """Arrange an HTML file + manifest and run convert_html; return the trio."""
    html = _write_html(tmp_path, name, body)
    manifest = tmp_path / "manifest.jsonl"
    result = convert_html(html, manifest_path=manifest)
    return result, html, manifest


def _run_with_existing(tmp_path: Path, *, existing: str):
    """Run convert_html when the target .md already holds ``existing``."""
    html = _write_html(tmp_path, "paper.html", _PAPER_BODY)
    target = html.with_suffix(".md")
    target.write_text(existing, encoding="utf-8")
    result = convert_html(html, manifest_path=tmp_path / "manifest.jsonl")
    return result, target


def _only_record(manifest: Path):
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


# --- structure preservation (AC1): each markup kind is its own fact ---


def test_heading_becomes_atx_heading():
    assert "# Title" in html_to_markdown("<h1>Title</h1>")


def test_unordered_list_item_becomes_a_bullet():
    assert "* a" in html_to_markdown("<ul><li>a</li><li>b</li></ul>")


def test_table_becomes_a_gfm_pipe_row():
    md = html_to_markdown("<table><tr><th>H</th></tr><tr><td>c</td></tr></table>")
    assert "| H |" in md


def test_code_block_is_fenced():
    assert "```" in html_to_markdown("<pre><code>x = 1</code></pre>")


# --- save files/<name>.md alongside the .html (AC1) ---


def test_returns_md_path_alongside_html(tmp_path: Path):
    result, html, _ = _run(tmp_path)
    assert result == html.with_suffix(".md")


def test_writes_converted_markdown_to_the_md_file(tmp_path: Path):
    result, _, _ = _run(tmp_path)
    assert result.read_text(encoding="utf-8").startswith("# Title")


# --- idempotent skip: an existing .md is left untouched ---


def test_idempotent_skip_returns_existing_path(tmp_path: Path):
    result, target = _run_with_existing(tmp_path, existing="hand-edited")
    assert result == target


def test_idempotent_skip_leaves_md_unchanged(tmp_path: Path):
    _, target = _run_with_existing(tmp_path, existing="hand-edited")
    assert target.read_text(encoding="utf-8") == "hand-edited"


# --- quarantine a hollow SPA shell (AC2: "HTML too thin") ---

_HOLLOW_SHELL = '<div id="__next"></div>'


def test_too_thin_returns_none(tmp_path: Path):
    result, _, _ = _run(tmp_path, name="spa.html", body=_HOLLOW_SHELL)
    assert result is None


def test_too_thin_writes_no_md(tmp_path: Path):
    _, html, _ = _run(tmp_path, name="spa.html", body=_HOLLOW_SHELL)
    assert not html.with_suffix(".md").exists()


def test_too_thin_manifest_records_path(tmp_path: Path):
    _, html, manifest = _run(tmp_path, name="spa.html", body=_HOLLOW_SHELL)
    assert _only_record(manifest)["path"] == str(html)


def test_too_thin_manifest_reason_is_html_too_thin(tmp_path: Path):
    _, _, manifest = _run(tmp_path, name="spa.html", body=_HOLLOW_SHELL)
    assert _only_record(manifest)["reason"] == "HTML too thin"


def test_too_thin_manifest_records_convert_html_stage(tmp_path: Path):
    # the manifest is shared across steps; a stage discriminator keeps records
    # readable when fetch-one and convert-html both append to it (review #3).
    _, _, manifest = _run(tmp_path, name="spa.html", body=_HOLLOW_SHELL)
    assert _only_record(manifest)["stage"] == "convert-html"


# --- quarantine an undecodable (non-UTF-8) HTML file — never crash (rule 02) ---


def _run_undecodable(tmp_path: Path):
    """Write a Latin-1 file with a byte invalid as UTF-8 and run convert_html."""
    html = tmp_path / "latin1.html"
    html.write_bytes(b"<html><body><p>caf\xe9 " + b"x" * 500 + b"</p></body></html>")
    manifest = tmp_path / "manifest.jsonl"
    return convert_html(html, manifest_path=manifest), html, manifest


def test_undecodable_html_returns_none(tmp_path: Path):
    result, _, _ = _run_undecodable(tmp_path)
    assert result is None


def test_undecodable_html_manifest_reason_names_the_encoding(tmp_path: Path):
    _, _, manifest = _run_undecodable(tmp_path)
    assert _only_record(manifest)["reason"] == "undecodable HTML (not UTF-8)"


# --- a real captured HTML paper converts, not quarantined (AC1 on real input) ---

_SAMPLE = Path(__file__).parent / "samples" / "keyword-method.html"


def test_real_sample_html_is_converted_not_quarantined(tmp_path: Path):
    html = tmp_path / "keyword-method.html"
    html.write_text(_SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    result = convert_html(html, manifest_path=tmp_path / "manifest.jsonl")
    assert result == html.with_suffix(".md")
