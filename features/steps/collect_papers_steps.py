import subprocess
import sys
import tempfile
from pathlib import Path

from behave import given, then, when


def _files_dir(context):
    if not getattr(context, "files_dir", None):
        context.files_dir = Path(tempfile.mkdtemp()) / "files"
        context.files_dir.mkdir()
    return context.files_dir


def _dest_dir(context):
    if not getattr(context, "dest_dir", None):
        context.dest_dir = Path(tempfile.mkdtemp()) / "raw"
        context.dest_dir.mkdir()
    return context.dest_dir


@given('a topic folder "{topic}" containing converted .md papers')
def step_topic_with_mds(context, topic):
    topic_dir = _files_dir(context) / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    context.topic = topic
    context.topic_dir = topic_dir
    (topic_dir / "2507.05444v3.md").write_text("# Mnemonic Keyword Method\n")
    (topic_dir / "2409.13952v1.md").write_text("# Spaced Repetition Survey\n")
    (topic_dir / "2507.05444v3.pdf").write_bytes(b"%PDF")


@given('a topic folder "{topic}" with no .md files')
def step_topic_no_mds(context, topic):
    topic_dir = _files_dir(context) / topic
    topic_dir.mkdir(parents=True, exist_ok=True)
    context.topic = topic
    context.topic_dir = topic_dir
    (topic_dir / "2507.05444v3.pdf").write_bytes(b"%PDF")


@given('a stale copy of one .md already exists in the dest folder')
def step_stale_copy(context):
    dest = _dest_dir(context)
    (dest / "2507.05444v3.md").write_text("stale content")


@given('no topic folder named "{topic}" under files/')
def step_missing_topic(context, topic):
    _files_dir(context)
    context.topic = topic


@when('collect-papers runs for topic "{topic}" with a dest folder')
def step_run_collect(context, topic):
    dest = _dest_dir(context)
    result = subprocess.run(
        [
            sys.executable, "-m", "paper_degist.collect_papers",
            topic,
            "--dest", str(dest),
            "--files-dir", str(_files_dir(context)),
        ],
        capture_output=True,
        text=True,
    )
    context.proc = result
    context.dest_dir = dest


@then("all .md files are present in the dest folder")
def step_all_mds_copied(context):
    dest = _dest_dir(context)
    assert (dest / "2507.05444v3.md").exists()
    assert (dest / "2409.13952v1.md").exists()
    assert not (dest / "2507.05444v3.pdf").exists()


@then("no files are copied and the step exits 0")
def step_no_files_exit_0(context):
    assert context.proc.returncode == 0
    dest = _dest_dir(context)
    assert list(dest.iterdir()) == []


@then("the dest file contains the fresh content from the topic folder")
def step_fresh_content(context):
    dest = _dest_dir(context)
    content = (dest / "2507.05444v3.md").read_text()
    assert content == "# Mnemonic Keyword Method\n"


@then("the step exits non-zero")
def step_exits_nonzero(context):
    assert context.proc.returncode != 0


@then("an error message is printed to stderr")
def step_error_on_stderr(context):
    assert context.proc.stderr.strip() != ""
