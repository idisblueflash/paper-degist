"""CLI behavior for the Typer-based steps (pytest + Typer CliRunner).

Closes the deferred "console entry point is not unit-tested" item: exercises
``main`` via each step's Typer ``app`` — file argument, stdin, and the
missing/unreadable-file error path (clean message + non-zero exit, no
traceback).
"""

import io
import json
from contextlib import contextmanager
from pathlib import Path

import typer
from typer.testing import CliRunner

import paper_degist
import paper_degist.browser_fetch as browser_fetch_mod
import paper_degist.browser_up as browser_up_mod
import paper_degist.fetch_one as fetch_one_mod
import paper_degist.ocr_page as ocr_page_mod
import paper_degist.parse_url as parse_url_mod
import paper_degist.resolve_oa as resolve_oa_mod
from paper_degist import app as root_app
from paper_degist._cli import invoke
from paper_degist.browser_fetch import app as browser_fetch_app
from paper_degist.browser_up import app as browser_up_app
from paper_degist.convert_html import app as convert_html_app
import paper_degist.discover as discover_mod
from paper_degist.discover import Candidate
from paper_degist.discover import app as discover_app
from paper_degist.embed_text import app as embed_text_app
from paper_degist.fetch_one import app as fetch_one_app
from paper_degist.ocr_batch import app as ocr_batch_app
from paper_degist.ocr_page import app as ocr_page_app
from paper_degist.parse_url import app as parse_url_app
from paper_degist.recover_blocked import app as recover_blocked_app
from paper_degist.ocr_report import app as ocr_report_app
from paper_degist.resolve_oa import app as resolve_oa_app

runner = CliRunner()


class _FakeResponse:
    def __init__(self, *, status_code=200, content_type="", content=b""):
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.content = content


def test_parse_url_reads_file_argument(tmp_path: Path):
    blob = tmp_path / "notes.md"
    blob.write_text("see https://example.com/a.pdf here", encoding="utf-8")

    result = runner.invoke(parse_url_app, [str(blob)])

    assert result.exit_code == 0
    assert result.stdout == "https://example.com/a.pdf\n"


def test_parse_url_reads_stdin_when_no_file(tmp_path: Path):
    result = runner.invoke(parse_url_app, input="a https://example.com/x\n")

    assert result.exit_code == 0
    assert result.stdout == "https://example.com/x\n"


def test_parse_url_prints_one_url_per_line(tmp_path: Path):
    blob = tmp_path / "notes.md"
    blob.write_text("https://a.com and https://b.com", encoding="utf-8")

    result = runner.invoke(parse_url_app, [str(blob)])

    assert result.exit_code == 0
    assert result.stdout == "https://a.com\nhttps://b.com\n"


def test_parse_url_missing_file_exits_two_without_traceback(tmp_path: Path):
    missing = tmp_path / "nope.md"

    result = runner.invoke(parse_url_app, [str(missing)])

    assert result.exit_code == 2  # Click's usage/validation exit code
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.output


def _fetch_one_save(tmp_path, monkeypatch):
    """Arrange a patched fetch + files dir and run `fetch-one` on a PDF URL."""
    resp = _FakeResponse(content_type="application/pdf", content=b"%PDF- data")
    monkeypatch.setattr(fetch_one_mod, "_default_fetch", lambda url: resp)
    files = tmp_path / "files"
    result = runner.invoke(
        fetch_one_app, ["https://example.com/a.pdf", "--files-dir", str(files)]
    )
    return result, files


def test_fetch_one_cli_exits_zero_on_save(tmp_path: Path, monkeypatch):
    result, _ = _fetch_one_save(tmp_path, monkeypatch)
    assert result.exit_code == 0


def test_fetch_one_cli_prints_saved_path(tmp_path: Path, monkeypatch):
    result, files = _fetch_one_save(tmp_path, monkeypatch)
    assert result.stdout.strip() == str(files / "a.pdf")


def _fetch_one_quarantine(tmp_path, monkeypatch):
    """Run `fetch-one` on a 403 URL; return (result, files, manifest)."""
    resp = _FakeResponse(status_code=403, content_type="text/html", content=b"no")
    monkeypatch.setattr(fetch_one_mod, "_default_fetch", lambda url: resp)
    files = tmp_path / "files"
    manifest = tmp_path / "manifest.jsonl"
    result = runner.invoke(
        fetch_one_app,
        ["https://example.com/x", "--files-dir", str(files), "--manifest", str(manifest)],
    )
    return result, files, manifest


def test_fetch_one_cli_quarantine_exits_zero(tmp_path: Path, monkeypatch):
    # quarantine is an expected outcome, not a crash
    result, _, _ = _fetch_one_quarantine(tmp_path, monkeypatch)
    assert result.exit_code == 0


def test_fetch_one_cli_quarantine_saves_no_file(tmp_path: Path, monkeypatch):
    _, files, _ = _fetch_one_quarantine(tmp_path, monkeypatch)
    assert not files.exists()


def test_fetch_one_cli_quarantine_writes_manifest(tmp_path: Path, monkeypatch):
    _, _, manifest = _fetch_one_quarantine(tmp_path, monkeypatch)
    assert manifest.exists()


def test_fetch_one_cli_quarantine_notes_url_on_stderr(tmp_path: Path, monkeypatch):
    # err=True output, which CliRunner folds into result.output
    result, _, _ = _fetch_one_quarantine(tmp_path, monkeypatch)
    assert "https://example.com/x" in result.output


def _convert_html_save(tmp_path):
    """Write a content-rich .html and run `convert-html` on it."""
    html = tmp_path / "paper.html"
    body = "<h1>Title</h1><p>" + "lorem ipsum dolor sit amet " * 40 + "</p>"
    html.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    result = runner.invoke(convert_html_app, [str(html)])
    return result, html


def test_convert_html_cli_exits_zero_on_save(tmp_path: Path):
    result, _ = _convert_html_save(tmp_path)
    assert result.exit_code == 0


def test_convert_html_cli_prints_saved_md_path(tmp_path: Path):
    result, html = _convert_html_save(tmp_path)
    assert result.stdout.strip() == str(html.with_suffix(".md"))


def _convert_html_quarantine(tmp_path):
    """Run `convert-html` on a hollow SPA shell; return (result, manifest)."""
    html = tmp_path / "spa.html"
    html.write_text('<html><body><div id="__next"></div></body></html>', encoding="utf-8")
    manifest = tmp_path / "manifest.jsonl"
    result = runner.invoke(convert_html_app, [str(html), "--manifest", str(manifest)])
    return result, manifest


def test_convert_html_cli_quarantine_exits_zero(tmp_path: Path):
    # too-thin quarantine is an expected outcome, not a crash
    result, _ = _convert_html_quarantine(tmp_path)
    assert result.exit_code == 0


def test_convert_html_cli_quarantine_notes_path_on_stderr(tmp_path: Path):
    result, _ = _convert_html_quarantine(tmp_path)
    assert "spa.html" in result.output


def test_convert_html_cli_missing_file_exits_two(tmp_path: Path):
    result = runner.invoke(convert_html_app, [str(tmp_path / "nope.html")])
    assert result.exit_code == 2


def _resolve_oa_run(tmp_path, monkeypatch, *, verdict):
    """Patch the Unpaywall lookup to `verdict` and run `resolve-oa` on a DOI URL."""
    monkeypatch.setattr(resolve_oa_mod, "_unpaywall_lookup", lambda email: (lambda doi: verdict))
    manifest = tmp_path / "manifest.jsonl"
    result = runner.invoke(
        resolve_oa_app,
        ["https://doi.org/10.1191/x", "--email", "me@example.com", "--manifest", str(manifest)],
    )
    return result, manifest


def test_resolve_oa_cli_prints_oa_pdf_url(tmp_path: Path, monkeypatch):
    result, _ = _resolve_oa_run(tmp_path, monkeypatch, verdict="https://oa.org/p.pdf")
    assert result.stdout.strip() == "https://oa.org/p.pdf"


def test_resolve_oa_cli_quarantine_exits_zero(tmp_path: Path, monkeypatch):
    # closed access is an expected outcome, not a crash
    result, _ = _resolve_oa_run(tmp_path, monkeypatch, verdict=None)
    assert result.exit_code == 0


def test_resolve_oa_cli_quarantine_notes_url_on_stderr(tmp_path: Path, monkeypatch):
    result, _ = _resolve_oa_run(tmp_path, monkeypatch, verdict=None)
    assert "https://doi.org/10.1191/x" in result.output


def test_resolve_oa_cli_slug_url_resolves_via_title_lookup(tmp_path: Path, monkeypatch):
    # A slug URL (no embedded DOI) must reach the Crossref title→DOI path the CLI
    # wires in, then flow the recovered DOI into the OA lookup (US10 AC1).
    monkeypatch.setattr(resolve_oa_mod, "_crossref_title_lookup", lambda email: (lambda t: "10.1/x"))
    monkeypatch.setattr(resolve_oa_mod, "_unpaywall_lookup", lambda email: (lambda doi: "https://oa.org/p.pdf"))
    result = runner.invoke(
        resolve_oa_app,
        [
            "https://www.researchgate.net/publication/249870239_An_investigation",
            "--email",
            "me@example.com",
            "--manifest",
            str(tmp_path / "manifest.jsonl"),
        ],
    )
    assert result.stdout.strip() == "https://oa.org/p.pdf"


def test_resolve_oa_cli_missing_email_exits_two(tmp_path: Path):
    # Unpaywall needs a contact email; the option is required.
    result = runner.invoke(resolve_oa_app, ["https://doi.org/10.1191/x"])
    assert result.exit_code == 2


def test_browser_up_cli_prints_endpoint_on_reuse(monkeypatch):
    # A reachable dev-mode Chrome is reused; the CLI prints its endpoint.
    monkeypatch.setattr(browser_up_mod, "_default_probe_cdp", lambda url: True)
    result = runner.invoke(browser_up_app, ["--cdp", "http://localhost:9222"])
    assert result.stdout.strip() == "http://localhost:9222"


def test_browser_up_cli_reuse_exits_zero(monkeypatch):
    monkeypatch.setattr(browser_up_mod, "_default_probe_cdp", lambda url: True)
    result = runner.invoke(browser_up_app, [])
    assert result.exit_code == 0


def test_browser_up_cli_loud_failure_exits_non_zero(monkeypatch):
    # A launch it cannot complete is a loud non-zero exit, not a quarantine.
    monkeypatch.setattr(browser_up_mod, "_default_probe_cdp", lambda url: False)
    monkeypatch.setattr(browser_up_mod, "_default_port_in_use", lambda h, p: False)
    monkeypatch.setattr(browser_up_mod, "_default_find_chrome", lambda: None)
    result = runner.invoke(browser_up_app, [])
    assert result.exit_code == 1


def test_browser_up_cli_loud_failure_names_the_reason_on_stderr(monkeypatch):
    monkeypatch.setattr(browser_up_mod, "_default_probe_cdp", lambda url: False)
    monkeypatch.setattr(browser_up_mod, "_default_port_in_use", lambda h, p: False)
    monkeypatch.setattr(browser_up_mod, "_default_find_chrome", lambda: None)
    result = runner.invoke(browser_up_app, [])
    assert "browser-up failed" in result.output


def test_browser_up_cli_loud_failure_is_not_a_stack_trace(monkeypatch):
    # AC4/AC5: never a stack-trace crash.
    monkeypatch.setattr(browser_up_mod, "_default_probe_cdp", lambda url: False)
    monkeypatch.setattr(browser_up_mod, "_default_port_in_use", lambda h, p: False)
    monkeypatch.setattr(browser_up_mod, "_default_find_chrome", lambda: None)
    result = runner.invoke(browser_up_app, [])
    assert "Traceback" not in result.output


def test_browser_up_main_returns_one_on_loud_failure(monkeypatch, capsys):
    # The exit code the shell actually sees for a loud failure.
    monkeypatch.setattr(browser_up_mod, "_default_probe_cdp", lambda url: False)
    monkeypatch.setattr(browser_up_mod, "_default_port_in_use", lambda h, p: False)
    monkeypatch.setattr(browser_up_mod, "_default_find_chrome", lambda: None)
    assert browser_up_mod.main([]) == 1


# --- browser-fetch CLI: a *list* of URLs from a file/stdin over one warm session (US16) ---


B1 = "https://www.researchgate.net/publication/220320021_Spaced_Repetition_and_Long-Term_Retention"
B2 = "https://www.researchgate.net/publication/319012693_The_Testing_Effect_in_the_Classroom"


def _patch_browser_batch(monkeypatch, *, reachable=True):
    """Patch browser-fetch's collaborators so the CLI runs without a real Chrome."""
    monkeypatch.setattr(browser_fetch_mod, "_default_probe_cdp", lambda cdp: reachable)

    @contextmanager
    def _open(cdp_url, **_kw):
        yield lambda url: f"<html><body>{url}</body></html>"

    monkeypatch.setattr(browser_fetch_mod, "_default_open_session", _open)


def test_browser_fetch_cli_reads_urls_from_a_file_and_prints_saved_paths(tmp_path, monkeypatch):
    _patch_browser_batch(monkeypatch)
    urls = tmp_path / "urls.txt"
    urls.write_text(f"{B1}\n{B2}\n", encoding="utf-8")
    files = tmp_path / "files"

    result = runner.invoke(
        browser_fetch_app,
        [str(urls), "--files-dir", str(files), "--manifest", str(tmp_path / "m.jsonl")],
    )

    assert result.stdout == (
        f"{files / '220320021_Spaced_Repetition_and_Long-Term_Retention.html'}\n"
        f"{files / '319012693_The_Testing_Effect_in_the_Classroom.html'}\n"
    )


def test_browser_fetch_cli_reads_urls_from_stdin_when_no_file(tmp_path, monkeypatch):
    _patch_browser_batch(monkeypatch)
    files = tmp_path / "files"
    result = runner.invoke(
        browser_fetch_app,
        ["--files-dir", str(files), "--manifest", str(tmp_path / "m.jsonl")],
        input=f"{B1}\n",
    )
    assert result.stdout == f"{files / '220320021_Spaced_Repetition_and_Long-Term_Retention.html'}\n"


def test_browser_fetch_cli_skips_blank_lines(tmp_path, monkeypatch):
    _patch_browser_batch(monkeypatch)
    urls = tmp_path / "urls.txt"
    urls.write_text(f"\n{B1}\n   \n", encoding="utf-8")  # blanks/whitespace ignored
    files = tmp_path / "files"
    result = runner.invoke(
        browser_fetch_app,
        [str(urls), "--files-dir", str(files), "--manifest", str(tmp_path / "m.jsonl")],
    )
    assert result.stdout == f"{files / '220320021_Spaced_Repetition_and_Long-Term_Retention.html'}\n"


def test_browser_fetch_cli_no_browser_prints_nothing(tmp_path, monkeypatch):
    # Endpoint unreachable → nothing saved, so stdout is empty (the URLs wait in
    # the manifest); the run still exits cleanly, never crashes.
    _patch_browser_batch(monkeypatch, reachable=False)
    urls = tmp_path / "urls.txt"
    urls.write_text(f"{B1}\n{B2}\n", encoding="utf-8")
    result = runner.invoke(
        browser_fetch_app,
        [str(urls), "--files-dir", str(tmp_path / "files"), "--manifest", str(tmp_path / "m.jsonl")],
    )
    assert result.stdout == ""


def test_browser_fetch_cli_no_browser_notes_the_quarantine_on_stderr(tmp_path, monkeypatch):
    # A batch that saves nothing must not be silent — the user needs to know the
    # URLs were quarantined (and where), while stdout stays paths-only for piping.
    _patch_browser_batch(monkeypatch, reachable=False)
    urls = tmp_path / "urls.txt"
    urls.write_text(f"{B1}\n{B2}\n", encoding="utf-8")
    manifest = tmp_path / "m.jsonl"
    result = runner.invoke(
        browser_fetch_app,
        [str(urls), "--files-dir", str(tmp_path / "files"), "--manifest", str(manifest)],
    )
    assert "quarantined" in result.stderr


def test_browser_fetch_cli_no_browser_exits_zero(tmp_path, monkeypatch):
    _patch_browser_batch(monkeypatch, reachable=False)
    urls = tmp_path / "urls.txt"
    urls.write_text(f"{B1}\n", encoding="utf-8")
    result = runner.invoke(
        browser_fetch_app,
        [str(urls), "--files-dir", str(tmp_path / "files"), "--manifest", str(tmp_path / "m.jsonl")],
    )
    assert result.exit_code == 0


def test_browser_fetch_cli_missing_file_exits_two_without_traceback(tmp_path):
    result = runner.invoke(browser_fetch_app, [str(tmp_path / "nope.txt")])
    assert result.exit_code == 2
    assert "Traceback" not in result.output


# --- recover-blocked CLI: route the manifest's blocked_by URLs into browser-fetch (US17) ---


RB_RG = "https://www.researchgate.net/publication/287147155_The_Mnemonic_Keyword_Method"
RB_PUBMED = "https://pubmed.ncbi.nlm.nih.gov/2303742/"


def _blocked_manifest(tmp_path):
    """A manifest holding two fetch-one blocked_by quarantines and one generic one."""
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        '{"stage": "fetch-one", "url": "%s", "status": 403, "blocked_by": "researchgate.net"}\n'
        '{"stage": "fetch-one", "url": "https://example.edu/papers/some-closed-paper", "status": 403, "reason": "http 403"}\n'
        '{"stage": "fetch-one", "url": "%s", "status": 403, "blocked_by": "pubmed.ncbi.nlm.nih.gov"}\n'
        % (RB_RG, RB_PUBMED),
        encoding="utf-8",
    )
    return manifest


def test_recover_blocked_cli_prints_the_recovered_paths(tmp_path, monkeypatch):
    _patch_browser_batch(monkeypatch)  # a warm Chrome that renders each URL
    manifest = _blocked_manifest(tmp_path)
    files = tmp_path / "files"
    result = runner.invoke(recover_blocked_app, [str(manifest), "--files-dir", str(files)])
    assert result.stdout == (
        f"{files / '287147155_The_Mnemonic_Keyword_Method.html'}\n"
        f"{files / '2303742.html'}\n"
    )


def test_recover_blocked_cli_ignores_the_generic_quarantine(tmp_path, monkeypatch):
    # The plain http-403 (no blocked_by) is not this lane's job — its slug never
    # reaches files/.
    _patch_browser_batch(monkeypatch)
    manifest = _blocked_manifest(tmp_path)
    files = tmp_path / "files"
    result = runner.invoke(recover_blocked_app, [str(manifest), "--files-dir", str(files)])
    assert "some-closed-paper" not in result.stdout


def test_recover_blocked_cli_no_browser_exits_zero(tmp_path, monkeypatch):
    # No dev-mode Chrome: the blocked URLs wait in the manifest (browser-fetch's
    # own quarantine), and recover-blocked still exits cleanly (AC4).
    _patch_browser_batch(monkeypatch, reachable=False)
    manifest = _blocked_manifest(tmp_path)
    result = runner.invoke(recover_blocked_app, [str(manifest), "--files-dir", str(tmp_path / "files")])
    assert result.exit_code == 0


def test_recover_blocked_cli_no_blocked_records_prints_nothing(tmp_path, monkeypatch):
    _patch_browser_batch(monkeypatch)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(
        '{"stage": "fetch-one", "url": "https://example.edu/papers/some-closed-paper", "status": 403, "reason": "http 403"}\n',
        encoding="utf-8",
    )
    result = runner.invoke(recover_blocked_app, [str(manifest), "--files-dir", str(tmp_path / "files")])
    assert result.stdout == ""


def test_recover_blocked_cli_missing_manifest_exits_two(tmp_path):
    result = runner.invoke(recover_blocked_app, [str(tmp_path / "nope.jsonl")])
    assert result.exit_code == 2


def test_recover_blocked_cli_missing_manifest_has_no_traceback(tmp_path):
    result = runner.invoke(recover_blocked_app, [str(tmp_path / "nope.jsonl")])
    assert "Traceback" not in result.output


def test_root_signpost_lists_recover_blocked():
    result = runner.invoke(root_app, [])
    assert "recover-blocked" in result.stdout


def test_root_signpost_lists_browser_fetch():
    result = runner.invoke(root_app, [])
    assert "browser-fetch" in result.stdout


def test_root_signpost_lists_browser_up():
    result = runner.invoke(root_app, [])
    assert "browser-up" in result.stdout


def test_root_signpost_lists_resolve_oa():
    result = runner.invoke(root_app, [])
    assert "resolve-oa" in result.stdout


def test_root_signpost_lists_convert_html():
    result = runner.invoke(root_app, [])
    assert "convert-html" in result.stdout


def test_root_signpost_lists_ocr_page():
    result = runner.invoke(root_app, [])
    assert "ocr-page" in result.stdout


# --- ocr-page CLI: unknown model quarantines without a crash or a network hit ---


def _ocr_page_unknown_model(tmp_path: Path):
    """Run `ocr-page` on an unregistered model; return (result, out_dir, manifest).

    The unknown-model branch quarantines before any network contact, so the CLI
    is exercisable offline with no injected transport.
    """
    page = tmp_path / "p02.png"
    page.write_bytes(b"\x89PNG page bytes")
    out_dir = tmp_path / "out"
    manifest = tmp_path / "manifest.jsonl"
    result = runner.invoke(
        ocr_page_app,
        [str(page), "some-unregistered-ocr", "--out-dir", str(out_dir), "--manifest", str(manifest)],
    )
    return result, out_dir, manifest


def test_ocr_page_cli_quarantine_exits_zero(tmp_path: Path):
    # quarantine is an expected outcome, not a crash
    result, _, _ = _ocr_page_unknown_model(tmp_path)
    assert result.exit_code == 0


def test_ocr_page_cli_quarantine_writes_manifest(tmp_path: Path):
    _, _, manifest = _ocr_page_unknown_model(tmp_path)
    assert manifest.exists()


def test_ocr_page_cli_quarantine_saves_no_output(tmp_path: Path):
    _, out_dir, _ = _ocr_page_unknown_model(tmp_path)
    assert not out_dir.exists()


def test_ocr_page_cli_missing_page_exits_two(tmp_path: Path):
    # Typer validates the page argument up front (exists=True) — clean exit 2.
    result = runner.invoke(ocr_page_app, [str(tmp_path / "absent.png"), "qwen/qwen3-vl-4b"])
    assert result.exit_code == 2


# --- ocr-batch CLI (US28): a grid of unknown-model pairs quarantines offline ---


def _ocr_batch_unknown_model(tmp_path: Path):
    """Run `ocr-batch` over a page dir, restricted to an unregistered model.

    Every pair takes ocr-page's unknown-model branch, which quarantines before
    any network contact — so the batch CLI is exercisable offline, no transport.
    """
    pages = tmp_path / "pages" / "SpacedRepetition"
    pages.mkdir(parents=True)
    (pages / "p0001.png").write_bytes(b"\x89PNG page bytes")
    out_dir = tmp_path / "out"
    manifest = tmp_path / "manifest.jsonl"
    result = runner.invoke(
        ocr_batch_app,
        [str(pages), "--model", "some-unregistered-ocr", "--out-dir", str(out_dir),
         "--manifest", str(manifest)],
    )
    return result, out_dir, manifest


def test_ocr_batch_cli_quarantine_exits_zero(tmp_path: Path):
    # every pair quarantined is an expected outcome, not a crash
    result, _, _ = _ocr_batch_unknown_model(tmp_path)
    assert result.exit_code == 0


def test_ocr_batch_cli_quarantine_writes_manifest(tmp_path: Path):
    _, _, manifest = _ocr_batch_unknown_model(tmp_path)
    assert manifest.exists()


def test_ocr_batch_cli_missing_dir_exits_two(tmp_path: Path):
    # Typer validates the pages_dir argument up front (exists=True) — clean exit 2.
    result = runner.invoke(ocr_batch_app, [str(tmp_path / "absent-pages")])
    assert result.exit_code == 2


def test_root_signpost_lists_ocr_batch():
    result = runner.invoke(root_app, [])
    assert "ocr-batch" in result.stdout


def test_root_signpost_lists_embed_text():
    result = runner.invoke(root_app, [])
    assert "embed-text" in result.stdout


# --- embed-text CLI: unknown model quarantines without a crash or a network hit ---


def _embed_text_unknown_model(tmp_path: Path):
    """Run `embed-text` on an unregistered model; return (result, out_dir, manifest).

    The unknown-model branch quarantines before any network contact, so the CLI
    is exercisable offline with no injected transport.
    """
    text_file = tmp_path / "abstract.txt"
    text_file.write_text("Spaced repetition improves retention.", encoding="utf-8")
    out_dir = tmp_path / "out"
    manifest = tmp_path / "manifest.jsonl"
    result = runner.invoke(
        embed_text_app,
        [
            "some-unregistered-embed",
            str(text_file),
            "--out-dir",
            str(out_dir),
            "--manifest",
            str(manifest),
        ],
    )
    return result, out_dir, manifest


def test_embed_text_cli_quarantine_exits_zero(tmp_path: Path):
    # quarantine is an expected outcome, not a crash
    result, _, _ = _embed_text_unknown_model(tmp_path)
    assert result.exit_code == 0


def test_embed_text_cli_quarantine_writes_manifest(tmp_path: Path):
    _, _, manifest = _embed_text_unknown_model(tmp_path)
    assert manifest.exists()


def test_embed_text_cli_quarantine_saves_no_output(tmp_path: Path):
    _, out_dir, _ = _embed_text_unknown_model(tmp_path)
    assert not out_dir.exists()


def test_embed_text_cli_missing_text_file_exits_two(tmp_path: Path):
    # Typer validates the text-file argument up front (exists=True) — clean exit 2.
    result = runner.invoke(embed_text_app, ["nomic-embed-text-v1.5", str(tmp_path / "absent.txt")])
    assert result.exit_code == 2


# --- discover CLI: unknown source quarantines offline; hits print JSONL ---


def _discover_unknown_source(tmp_path: Path):
    """Run `discover --source pubmed`; return (result, manifest).

    The unknown-source branch quarantines before any network contact, so the CLI
    is exercisable offline with no injected registry.
    """
    manifest = tmp_path / "manifest.jsonl"
    result = runner.invoke(
        discover_app,
        ["gene therapy delivery vectors", "--source", "pubmed", "--manifest", str(manifest)],
    )
    return result, manifest


def test_discover_cli_unknown_source_exits_zero(tmp_path: Path):
    # quarantine is an expected outcome, not a crash
    result, _ = _discover_unknown_source(tmp_path)
    assert result.exit_code == 0


def test_discover_cli_unknown_source_writes_manifest(tmp_path: Path):
    _, manifest = _discover_unknown_source(tmp_path)
    assert manifest.exists()


def test_discover_cli_hits_print_one_jsonl_line_per_candidate(tmp_path: Path, monkeypatch):
    # Inject a fake registry so the CLI never touches the network; assert the
    # emitted stdout is one JSON object per hit (drop-in to the filter chain).
    candidate = Candidate(
        title="Switch Transformers",
        authors=["William Fedus"],
        abstract="Mixture of Experts models route tokens sparsely.",
        url="http://arxiv.org/abs/2101.03961v1",
        published="2021-01-11T18:41:03Z",
        source="arxiv",
        source_id="2101.03961v1",
    )
    monkeypatch.setattr(
        discover_mod, "_build_registry", lambda mr, key: {"arxiv": lambda q: [candidate]}
    )
    result = runner.invoke(
        discover_app,
        ["sparse mixture of experts", "--source", "arxiv", "--manifest", str(tmp_path / "m.jsonl")],
    )
    line = result.stdout.strip()
    assert json.loads(line)["title"] == "Switch Transformers"


def test_root_signpost_lists_discover():
    result = runner.invoke(root_app, [])
    assert "discover" in result.stdout


def test_root_signpost_lists_steps():
    result = runner.invoke(root_app, [])

    assert result.exit_code == 0
    assert "parse-url" in result.stdout


def test_root_signpost_lists_fetch_one():
    result = runner.invoke(root_app, [])
    assert "fetch-one" in result.stdout


# --- main(argv) -> int wrappers: the exit codes the shell actually sees ---


def test_parse_url_main_returns_zero_on_success(tmp_path: Path, capsys):
    blob = tmp_path / "notes.md"
    blob.write_text("https://a.com and https://b.com", encoding="utf-8")

    assert parse_url_mod.main([str(blob)]) == 0
    assert capsys.readouterr().out == "https://a.com\nhttps://b.com\n"


def test_parse_url_main_reads_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("x https://example.com/x\n"))

    assert parse_url_mod.main([]) == 0
    assert capsys.readouterr().out == "https://example.com/x\n"


def test_parse_url_main_returns_two_on_missing_file(tmp_path: Path, capsys):
    assert parse_url_mod.main([str(tmp_path / "nope.md")]) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_parse_url_main_help_returns_zero(capsys):
    assert parse_url_mod.main(["--help"]) == 0


def test_root_main_returns_zero(capsys):
    assert paper_degist.main([]) == 0
    assert "parse-url" in capsys.readouterr().out


def test_invoke_normalizes_non_integer_exit_code_to_one():
    app = typer.Typer(add_completion=False)

    @app.command()
    def boom() -> None:
        raise SystemExit("kaboom")  # non-int payload — must not crash the wrapper

    assert invoke(app, []) == 1


# --- ocr-report (US23): aggregate scores.jsonl into a Markdown scorecard ---


def _ocr_report_run(tmp_path):
    """Run `ocr-report` on a one-row scores.jsonl; return (result, report path)."""
    scores = tmp_path / "scores.jsonl"
    scores.write_text('{"model": "qwen_qwen3-vl-4b", "page": "p01", "dup_pct": 0.0}\n', encoding="utf-8")
    report = tmp_path / "report.md"
    result = runner.invoke(
        ocr_report_app,
        [str(scores), "--report", str(report), "--manifest", str(tmp_path / "manifest.jsonl")],
    )
    return result, report


def test_ocr_report_cli_exits_zero_on_write(tmp_path: Path):
    result, _ = _ocr_report_run(tmp_path)
    assert result.exit_code == 0


def test_ocr_report_cli_prints_the_report_path(tmp_path: Path):
    result, report = _ocr_report_run(tmp_path)
    assert str(report) in result.stdout


def test_ocr_report_cli_missing_scores_exits_two(tmp_path: Path):
    result = runner.invoke(ocr_report_app, [str(tmp_path / "nope.jsonl")])
    assert result.exit_code == 2


def test_ocr_report_cli_non_text_scores_exits_two_without_traceback(tmp_path: Path):
    # The wrong file (a binary) is a clean usage error, not a decode traceback.
    scores = tmp_path / "not-scores.pdf"
    scores.write_bytes(b"%PDF-\xc4\xff binary")
    result = runner.invoke(ocr_report_app, [str(scores)])
    assert result.exit_code == 2
    assert "Traceback" not in result.output


def test_ocr_report_runs_as_a_script_via_the_main_guard(tmp_path: Path):
    # Rule 03: the `python <module>` __main__ guard must actually work — a helper
    # defined *after* the guard would NameError only on this path (CliRunner
    # imports the module fully and hides it). Format a real number to exercise it.
    import subprocess
    import sys

    scores = tmp_path / "scores.jsonl"
    scores.write_text('{"model": "qwen_qwen3-vl-4b", "page": "p01", "dup_pct": 1.5}\n', encoding="utf-8")
    module = Path("src/paper_degist/ocr_report.py").resolve()
    result = subprocess.run(
        [sys.executable, str(module), str(scores), "--report", str(tmp_path / "report.md"),
         "--manifest", str(tmp_path / "manifest.jsonl")],
        capture_output=True,
        text=True,
        cwd=Path.cwd(),
    )
    assert result.returncode == 0, result.stderr
