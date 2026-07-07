"""Tests for collect_papers (US 36) — driven one test at a time (rule 05)."""

import pytest
from pathlib import Path

from paper_degist.collect_papers import collect_papers


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_topic(tmp_path: Path, stems: list[str]) -> Path:
    """Create a topic folder with .md (and dummy .pdf) files for each stem."""
    topic_dir = tmp_path / "mnemonic-method"
    topic_dir.mkdir()
    for stem in stems:
        (topic_dir / f"{stem}.md").write_text(f"# {stem}\n")
        (topic_dir / f"{stem}.pdf").write_bytes(b"%PDF")
    return topic_dir


def _run(topic_dir: Path, dest: Path, **kwargs):
    return collect_papers(topic_dir, dest=dest, **kwargs)


# ---------------------------------------------------------------------------
# AC1 — copies all .md files to dest
# ---------------------------------------------------------------------------

def test_copies_md_files_to_dest(tmp_path):
    topic_dir = _make_topic(tmp_path, ["2507.05444v3", "2409.13952v1"])
    dest = tmp_path / "raw"
    dest.mkdir()

    copied = _run(topic_dir, dest)

    assert {p.name for p in copied} == {"2507.05444v3.md", "2409.13952v1.md"}


def test_copied_files_exist_in_dest(tmp_path):
    topic_dir = _make_topic(tmp_path, ["2507.05444v3"])
    dest = tmp_path / "raw"
    dest.mkdir()

    _run(topic_dir, dest)

    assert (dest / "2507.05444v3.md").exists()


def test_non_md_files_are_not_copied(tmp_path):
    topic_dir = _make_topic(tmp_path, ["2507.05444v3"])
    dest = tmp_path / "raw"
    dest.mkdir()

    _run(topic_dir, dest)

    assert not (dest / "2507.05444v3.pdf").exists()


# ---------------------------------------------------------------------------
# AC2 — no .md files → returns empty list, no crash
# ---------------------------------------------------------------------------

def test_empty_topic_folder_returns_empty(tmp_path):
    topic_dir = tmp_path / "empty-topic"
    topic_dir.mkdir()
    dest = tmp_path / "raw"
    dest.mkdir()

    copied = _run(topic_dir, dest)

    assert copied == []


# ---------------------------------------------------------------------------
# AC3 — idempotent: overwrites by default, skip-existing skips
# ---------------------------------------------------------------------------

def test_overwrite_by_default(tmp_path):
    topic_dir = _make_topic(tmp_path, ["2507.05444v3"])
    dest = tmp_path / "raw"
    dest.mkdir()
    (dest / "2507.05444v3.md").write_text("old content")

    _run(topic_dir, dest)

    assert (dest / "2507.05444v3.md").read_text() == "# 2507.05444v3\n"


def test_skip_existing_leaves_file_unchanged(tmp_path):
    topic_dir = _make_topic(tmp_path, ["2507.05444v3"])
    dest = tmp_path / "raw"
    dest.mkdir()
    (dest / "2507.05444v3.md").write_text("old content")

    _run(topic_dir, dest, skip_existing=True)

    assert (dest / "2507.05444v3.md").read_text() == "old content"


# ---------------------------------------------------------------------------
# AC4 — missing topic folder raises ValueError
# ---------------------------------------------------------------------------

def test_missing_topic_folder_raises(tmp_path):
    dest = tmp_path / "raw"
    dest.mkdir()

    with pytest.raises(ValueError, match="does not exist"):
        collect_papers(tmp_path / "nonexistent-topic", dest=dest)


# ---------------------------------------------------------------------------
# dest is created if absent
# ---------------------------------------------------------------------------

def test_dest_created_if_absent(tmp_path):
    topic_dir = _make_topic(tmp_path, ["2507.05444v3"])
    dest = tmp_path / "raw"

    _run(topic_dir, dest)

    assert dest.is_dir()
