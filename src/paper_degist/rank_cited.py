"""US32 — rank candidates by citation count, keep the top N.

`discover` / `discover-batch` (US25/31) over-return by design; this step cuts
the pool on the **influence** axis: sort by the `cited_by` count the source
adapters already emit, keep the top N. Pure, offline arithmetic over JSONL —
no API call, no LLM, no network (rule 02).

Runnable from the command line (rule 03):

    uv run rank-cited candidates.jsonl --top 10
    uv run discover-batch "…" "…" | uv run rank-cited
"""

import json
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke
from paper_degist.abstract_filter import load_candidates

# The operator's shortlist budget — not a measured heuristic (there is nothing
# to calibrate): enough to stand on the topic's established papers.
DEFAULT_TOP = 20


def _filtered(manifest_path: Path, *, url: str, reason: str, **fields: object) -> None:
    """Record a *deliberate* drop (beyond-top / no-cited-by) — never silent."""
    _manifest.append(
        manifest_path, stage="rank-cited", event="filtered", url=url, reason=reason, **fields
    )


def rank_cited(
    candidates: list[dict],
    *,
    top: int = DEFAULT_TOP,
    manifest_path: Path = Path("manifest.jsonl"),
) -> Optional[list[dict]]:
    """Rank `candidates` by descending `cited_by`; return the top `top` (US32)."""
    manifest_path = Path(manifest_path)
    rankable = []
    for record in candidates:
        # A usable count is an int (0 included — a new paper ranks last, it is
        # never confused with a missing field); anything else cannot be ranked
        # offline and is a classified drop, not a crash (rule 02). `bool` is an
        # int subclass — a malformed `cited_by: true` must not rank as 1.
        cited_by = record.get("cited_by")
        if isinstance(cited_by, int) and not isinstance(cited_by, bool):
            rankable.append(record)
            continue
        _filtered(manifest_path, url=record.get("url", ""), reason="no-cited-by")
    if not rankable or top <= 0:
        # AC6: nothing yields a ranking — either no usable counts or top=0.
        _manifest.append(
            manifest_path,
            stage="rank-cited",
            event="quarantined",
            candidates=len(candidates),
            reason="empty-rank: no candidate carries a usable cited_by count"
            if not rankable
            else f"empty-rank: top={top} leaves nothing to emit",
        )
        return None
    ranked = sorted(rankable, key=lambda r: r["cited_by"], reverse=True)
    for record in ranked[top:]:
        _filtered(
            manifest_path,
            url=record.get("url", ""),
            reason="beyond-top",
            cited_by=record["cited_by"],
        )
    return ranked[:top]


app = typer.Typer(
    add_completion=False,
    help="Rank candidates by citation count, keep the top N (US32).",
)


@app.command()
def run(
    candidates_file: Annotated[
        Optional[Path],
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="candidate JSONL (discover/discover-batch output); reads stdin when omitted",
        ),
    ] = None,
    top: Annotated[
        int,
        typer.Option("--top", help="how many of the most-cited candidates to keep"),
    ] = DEFAULT_TOP,
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of filtered/quarantined candidates"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Print the top N candidates as JSONL, most-cited first."""
    text = candidates_file.read_text(encoding="utf-8") if candidates_file else sys.stdin.read()
    candidates = load_candidates(text, manifest_path=manifest, stage="rank-cited")
    ranked = rank_cited(candidates, top=top, manifest_path=manifest)
    if ranked is None:
        typer.echo(
            f"quarantined (see {manifest}): nothing rankable among "
            f"{len(candidates)} candidate(s) — no usable cited_by",
            err=True,
        )
        return
    for record in ranked:
        typer.echo(json.dumps(record, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run rank-cited`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
