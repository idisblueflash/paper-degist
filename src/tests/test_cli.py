"""CLI behavior for the Typer-based steps (pytest + Typer CliRunner).

Closes the deferred "console entry point is not unit-tested" item: exercises
``main`` via each step's Typer ``app`` — file argument, stdin, and the
missing/unreadable-file error path (clean message + non-zero exit, no
traceback).
"""

from pathlib import Path

from typer.testing import CliRunner

from paper_degist import app as root_app
from paper_degist.parse_url import app as parse_url_app

runner = CliRunner()


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


def test_parse_url_missing_file_exits_nonzero_without_traceback(tmp_path: Path):
    missing = tmp_path / "nope.md"

    result = runner.invoke(parse_url_app, [str(missing)])

    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.output


def test_root_signpost_lists_steps():
    result = runner.invoke(root_app, [])

    assert result.exit_code == 0
    assert "parse-url" in result.stdout
