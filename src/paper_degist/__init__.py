"""paper-degist — convert papers into Markdown for an LLM wiki.

The root ``paper-degist`` command is a signpost only: the pipeline is run one
step at a time via each step's own console script (see ``[project.scripts]``).
"""


import typer

from paper_degist._cli import invoke

_STEPS = [
    ("parse-url", "Extract http(s) URLs from a text blob (US1 AC1)."),
    ("dedup-inputs", "Collapse inputs pointing at the same DOI down to one (US14)."),
    ("fetch-one", "Fetch one paper file from a URL, save under files/ (US2 AC2)."),
    ("convert-html", "Convert a saved HTML paper into files/<name>.md (US5)."),
    ("resolve-oa", "Check a failed URL/DOI for an open-access copy (US9)."),
    ("browser-up", "Launch/reuse a dev-mode Chrome for the browser lane (US18)."),
    ("browser-fetch", "Fetch a bot-walled page through a dev-mode Chrome over CDP (US15)."),
    ("render-pdf", "Render a PDF into one PNG per page for the OCR bench (US19)."),
    ("recover-blocked", "Route the manifest's blocked_by URLs into browser-fetch (US17)."),
    ("ocr-page", "OCR one page image with one registered vision model (US20)."),
    ("ocr-batch", "OCR a page directory across every registered vision model (US28)."),
    ("score-ocr", "Score a saved OCR output on reference-free defect metrics (US21)."),
    ("score-gold", "Score a model against an OmniDocBench gold subset (US22)."),
    ("ocr-report", "Aggregate the stored OCR scores into one Markdown scorecard (US23)."),
    ("embed-text", "Embed one text with one registered local embedding model (US24)."),
    ("discover", "Discover candidate papers by topic from arXiv or Semantic Scholar (US25)."),
    ("discover-batch", "Fan topic queries across discover sources, merge the union (US31)."),
    ("abstract-filter", "Filter candidates by abstract similarity to a topic (US26)."),
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
        typer.echo(f"  {name:<14} {desc}")
    typer.echo("\nRun `uv run <step> --help` for a step's options.")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run paper-degist`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
