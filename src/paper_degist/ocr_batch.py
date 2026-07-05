"""US28 — OCR a whole page directory across the model registry (ocr-batch).

The bench is built from single-item steps: ``render-pdf`` (US19) makes
``pages/<stem>/pNNNN.png``; ``ocr-page`` (US20) OCRs **one** page with **one**
model into ``out/<model>/<page>.md``; ``score-ocr`` / ``score-gold`` (US21-22)
score those files; ``ocr-report`` (US23) aggregates the scorecard. US20 left the
**grid** — every page × every registered model — to a future driver, "composed
from this step". This is that driver.

It composes ``ocr-page`` and holds no transport logic of its own. Its one job
beyond iterating the grid is the report §3 anti-flap rule applied *between
items*: the flaky MLX runtime must never see rapid-fire hits, so a **recovery
gap** is waited before each pair that will contact the server. ``ocr-page`` owns
the gap between *its own* retries; this driver owns the gap between one (page,
model) call and the next.

Classify-then-dispatch (rule 02) on one cheap signal per pair — does
``out/<model>/<page>.md`` already exist? Exists → idempotent skip, no network and
**no gap** (a re-run of the grid stays cheap, mirroring ocr-page's idempotency).
Missing → dispatch to ``ocr-page``, which owns the transport classify (unknown
model → quarantine without touching the network; 200 → save; 502 → retry then
quarantine). One quarantined pair never aborts the batch — the loop finishes and
the return simply omits it. No LLM is ever called to classify or rescue a pair;
this driver writes no manifest record of its own (each record is ocr-page's).

Runnable from the command line (rule 03):

    uv run ocr-batch pages/SpacedRepetition
    uv run ocr-batch pages/SpacedRepetition --model qwen/qwen3-vl-4b --gap 8
"""

import time
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer

from paper_degist._cli import invoke
from paper_degist.ocr_page import (
    DEFAULT_ATTEMPTS,
    DEFAULT_ENDPOINT,
    DEFAULT_GAP,
    REGISTRY,
    ModelSpec,
    ocr_page,
    output_path,
)

# The step this driver composes: (page, model, ...) -> saved path or None
# (quarantined). Injected in tests so the grid walk is exercised without the
# real curl-to-LM-Studio transport — the ocr-page shape (rule 02).
OcrStep = Callable[..., Optional[Path]]


def ocr_batch(
    pages_dir: Path,
    *,
    models: Optional[list[str]] = None,
    out_dir: Path = Path("out"),
    manifest_path: Path = Path("manifest.jsonl"),
    endpoint: str = DEFAULT_ENDPOINT,
    attempts: int = DEFAULT_ATTEMPTS,
    gap: float = DEFAULT_GAP,
    registry: dict[str, ModelSpec] = REGISTRY,
    ocr: OcrStep = ocr_page,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Path]:
    """OCR every page in ``pages_dir`` with every model in ``models``.

    Walks the directory's ``pNNNN.png`` pages (render-pdf's output) in page order
    then model order, calling ``ocr`` per pair. ``models`` defaults to the whole
    registry — a newly registered model joins the grid with no change here
    (rule 02). Returns the saved ``out/<model>/<page>.md`` paths (including the
    already-saved ones a re-run skips), omitting only quarantined pairs.

    The recovery gap is waited **before** a pair that will hit the server, and
    only once a prior pair already hit it — so a run of idempotent skips costs no
    gaps and a fresh grid spaces exactly the real calls. Never crashes on an empty
    or missing directory; never fires concurrently (report §3).
    """
    pages_dir = Path(pages_dir)
    out_dir = Path(out_dir)
    model_ids = list(registry) if models is None else models

    saved: list[Path] = []
    hit_server = False  # a prior pair contacted the server → cool down before the next
    for page in sorted(pages_dir.glob("p*.png")):
        for model_id in model_ids:
            # Classify in ocr-page's own layer order (rule 02): the registry check
            # comes *before* the idempotency skip, so an unknown model is never
            # short-circuited into "cached" by a stale output file — it dispatches
            # and ocr-page quarantines it (unknown model), before any network.
            registered = model_id in registry
            target = output_path(page, model_id, out_dir)
            if registered and target.exists():
                saved.append(target)  # idempotent skip — no network, no recovery gap
                continue
            # Only a registered pair with no cached output will hit the server; an
            # unknown model quarantines in ocr-page without a network call, so it is
            # neither preceded by a recovery gap nor counted as a prior server hit.
            if registered and hit_server:
                sleep(gap)  # recovery gap before a fresh server-hitting pair
            if registered:
                hit_server = True
            result = ocr(
                page,
                model_id,
                out_dir=out_dir,
                manifest_path=manifest_path,
                endpoint=endpoint,
                attempts=attempts,
                gap=gap,
                registry=registry,
            )
            if result is not None:
                saved.append(result)
    return saved


app = typer.Typer(
    add_completion=False,
    help="OCR a page directory across every registered vision model (US28).",
)


@app.command()
def run(
    pages_dir: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            readable=True,
            help="directory of rendered page PNGs (e.g. pages/<paper>/ from render-pdf)",
        ),
    ],
    model: Annotated[
        Optional[list[str]],
        typer.Option(help="restrict to these registered model id(s); default = whole registry"),
    ] = None,
    out_dir: Annotated[
        Path,
        typer.Option("--out-dir", help="directory to save Markdown under (out/<model>/)"),
    ] = Path("out"),
    endpoint: Annotated[
        str,
        typer.Option(help="chat-completions endpoint of the vision server"),
    ] = DEFAULT_ENDPOINT,
    attempts: Annotated[int, typer.Option(help="max POST attempts per pair before quarantine")] = DEFAULT_ATTEMPTS,
    gap: Annotated[float, typer.Option(help="recovery gap (seconds) between server-hitting calls")] = DEFAULT_GAP,
    manifest: Annotated[
        Path,
        typer.Option(help="manifest ocr-page records each pair / quarantine into"),
    ] = Path("manifest.jsonl"),
) -> None:
    """OCR the whole grid; print each saved Markdown path in page-then-model order."""
    paths = ocr_batch(
        pages_dir,
        models=model,
        out_dir=out_dir,
        manifest_path=manifest,
        endpoint=endpoint,
        attempts=attempts,
        gap=gap,
    )
    for path in paths:
        typer.echo(str(path))
    # Report the outcome on stderr so a run that OCR'd nothing (empty dir, or every
    # pair quarantined) is never silent — the manifest carries the per-pair reasons.
    typer.echo(
        f"ocr-batch: {len(paths)} page(s) OCR'd or already present (see {manifest})",
        err=True,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run ocr-batch`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
