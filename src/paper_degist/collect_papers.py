"""US 36 — collect converted Markdown papers from a topic folder to a target.

Runnable from the command line (rule 03):

    uv run collect-papers mnemonic-method --dest /path/to/raw
    uv run collect-papers mnemonic-method --dest /path/to/raw --skip-existing
"""

import shutil
from pathlib import Path
from typing import Annotated

import typer

from paper_degist._cli import invoke


def collect_papers(
    topic_dir: Path,
    *,
    dest: Path,
    skip_existing: bool = False,
) -> list[Path]:
    """Copy all .md files from ``topic_dir`` to ``dest``; return copied paths.

    Raises ValueError if ``topic_dir`` does not exist.
    Creates ``dest`` if absent.
    """
    topic_dir = Path(topic_dir)
    dest = Path(dest)

    if not topic_dir.exists():
        raise ValueError(f"topic folder does not exist: {topic_dir}")

    dest.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for src in sorted(topic_dir.glob("*.md")):
        target = dest / src.name
        if skip_existing and target.exists():
            continue
        shutil.copy2(src, target)
        copied.append(target)

    return copied


app = typer.Typer(
    add_completion=False,
    help="Collect converted .md papers from a topic folder into a target directory (US 36).",
)


@app.command()
def run(
    topic: Annotated[
        str,
        typer.Argument(help="topic subfolder name under --files-dir (e.g. mnemonic-method)"),
    ],
    dest: Annotated[
        Path,
        typer.Option(help="target directory to copy .md files into"),
    ],
    files_dir: Annotated[
        Path,
        typer.Option(help="root folder that contains topic subfolders"),
    ] = Path("files"),
    skip_existing: Annotated[
        bool,
        typer.Option("--skip-existing", help="skip files already present in dest"),
    ] = False,
) -> None:
    """Copy all .md papers under files/<topic>/ into dest."""
    topic_dir = files_dir / topic
    try:
        copied = collect_papers(topic_dir, dest=dest, skip_existing=skip_existing)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1)

    if not copied:
        typer.echo(f"warning: no .md files found in {topic_dir}", err=True)
        return

    for path in copied:
        typer.echo(str(path))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03)."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
