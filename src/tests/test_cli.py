"""CLI behavior for the Typer-based steps (pytest + Typer CliRunner).

Closes the deferred "console entry point is not unit-tested" item: exercises
``main`` via each step's Typer ``app`` — file argument, stdin, and the
missing/unreadable-file error path (clean message + non-zero exit, no
traceback).
"""

import io
from pathlib import Path

import typer
from typer.testing import CliRunner

import paper_degist
import paper_degist.fetch_one as fetch_one_mod
import paper_degist.parse_url as parse_url_mod
from paper_degist import app as root_app
from paper_degist._cli import invoke
from paper_degist.fetch_one import app as fetch_one_app
from paper_degist.parse_url import app as parse_url_app

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


def test_fetch_one_saves_file_and_prints_path(tmp_path: Path, monkeypatch):
    resp = _FakeResponse(content_type="application/pdf", content=b"%PDF- data")
    monkeypatch.setattr(fetch_one_mod, "_default_fetch", lambda url: resp)
    files = tmp_path / "files"

    result = runner.invoke(
        fetch_one_app, ["https://example.com/a.pdf", "--files-dir", str(files)]
    )

    assert result.exit_code == 0
    assert result.stdout.strip() == str(files / "a.pdf")
    assert (files / "a.pdf").read_bytes() == b"%PDF- data"


def test_fetch_one_quarantine_exits_zero_with_stderr_note(tmp_path: Path, monkeypatch):
    resp = _FakeResponse(status_code=403, content_type="text/html", content=b"no")
    monkeypatch.setattr(fetch_one_mod, "_default_fetch", lambda url: resp)
    files = tmp_path / "files"
    manifest = tmp_path / "manifest.jsonl"

    result = runner.invoke(
        fetch_one_app,
        [
            "https://example.com/x",
            "--files-dir",
            str(files),
            "--manifest",
            str(manifest),
        ],
    )

    assert result.exit_code == 0  # quarantine is expected, not a crash
    assert not files.exists()
    assert manifest.exists()


def test_root_signpost_lists_steps():
    result = runner.invoke(root_app, [])

    assert result.exit_code == 0
    assert "parse-url" in result.stdout
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
