"""paper-degist — convert papers into Markdown for an LLM wiki.

The root ``paper-degist`` command is a signpost only: the pipeline is run one
step at a time via each step's own console script (see ``[project.scripts]``).
"""


import typer

from paper_degist._cli import invoke

_STEPS = [
    ("parse-url", "Extract http(s) URLs from a text blob (US1 AC1)."),
    ("fetch-one", "Fetch one paper file from a URL, save under files/ (US2 AC2)."),
]

app = typer.Typer(
    add_completion=False,
    help="Convert papers into Markdown for an LLM wiki.",
)


@app.callback(invoke_without_command=True)
def signpost() -> None:
    """Signpost only — run each step via its own console script."""
    typer.echo("paper-degist — run a pipeline step directly:\n")
    for name, desc in _STEPS:
        typer.echo(f"  {name:<12} {desc}")
    typer.echo("\nRun `uv run <step> --help` for a step's options.")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run paper-degist`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
