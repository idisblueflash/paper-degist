"""US23 — Aggregate all per-page scores into one Markdown scorecard.

US21 and US22 emit per-(model, page) rows into ``scores.jsonl``; on their own
they are a pile of rows. The value the investigation report delivered was the
**scorecard** — a models × dimensions table with a short verdict per model. This
step reproduces that artifact *deterministically* from the stored scores, so it
regenerates in seconds and never re-hits the model server (rule 02: no LLM, no
network — pure summarization).

The core requirement, from the original ask, is that a newly added model needs
**no code change**: register it (US20), run the scorers (US21/22), regenerate
the report → it appears as a new row with its own verdict. The aggregation is
pure data: the model list and the dimension list are both *derived from the
records present*, never hard-coded, so a new model or a new dimension flows
through without a code edit.

Classify-then-dispatch (rule 02): each dimension is summarized by a summarizer
chosen from the *kind* of its values — categorical (``finish_reason``,
``cjk_present``) by their dominant value; count-like (``hyphen_artifacts``,
``citation_groups``, ``completion_tokens``) by a representative (median); and
ratio/score (``dup_pct``, ``text_edit_distance``, ``teds``, ``latency``) by
their average. A (model, dimension) cell with no measurement renders an explicit
**gap** marker, never a false ``0`` that would read as "scored badly" (AC4). A
record the step cannot place — one with no ``model`` — is quarantined to
``manifest.jsonl`` (``stage: "ocr-report"``) and skipped, never crashed over.

Runnable from the command line (rule 03):

    uv run ocr-report scores.jsonl
    uv run ocr-report scores.jsonl --report report.md
"""

import json
import math
import statistics
from pathlib import Path
from typing import Annotated

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke

# The marker rendered for a (model, dimension) cell that has no measurement —
# an em dash, visibly distinct from a real ``0`` (AC4: a missing measurement
# must never read as a poor one).
GAP = "—"

# The row-identity keys — they name *which* (model, page) row a score belongs
# to, not a scored dimension. Everything else in a record is a dimension, so a
# new metric appears in the scorecard without a code edit (AC3, data-driven).
_IDENTITY_KEYS = frozenset({"model", "page", "gold"})

# The direction of "better" for each numeric dimension the bench understands —
# encoded knowledge (rule 02), not a per-run judgement. A dimension in neither
# set (a brand-new metric, or a neutral one like ``completion_tokens``) still
# gets a scorecard column but is not ranked in the verdict until its direction
# is taught here (a one-line addition; DEVLOG deferred flag). Categorical
# dimensions (``finish_reason``, ``cjk_present``) are never leader-ranked.
_HIGHER_IS_BETTER = frozenset({"teds", "citation_groups"})
_LOWER_IS_BETTER = frozenset({"dup_pct", "hyphen_artifacts", "text_edit_distance", "latency"})


def models(records: list) -> list:
    """The distinct model ids across the records, sorted (deterministic, AC2).

    Derived from the records, never hard-coded — a newly scored model appears as
    its own scorecard row with no code change (AC3).
    """
    return sorted({record["model"] for record in records if "model" in record})


def dimensions(records: list) -> list:
    """The distinct scored dimensions across the records, sorted (AC2).

    Every record key that is not a row-identity key (``model``/``page``/``gold``)
    is a dimension; the union across all records is taken so a dimension only
    some rows carry (``teds`` on gold rows, ``dup_pct`` on reference-free rows)
    still gets a column. Derived from the data, so a new dimension flows through
    without a code edit.
    """
    found = set()
    for record in records:
        found.update(key for key in record if key not in _IDENTITY_KEYS)
    return sorted(found)


def aggregate(values: list):
    """Summarize one model's values for one dimension into a single raw value.

    Classify-then-dispatch by the kind of the (non-null) values (rule 02):
    count-like ints → a representative median; ratio/score numbers → their mean;
    categorical strings/bools → their dominant value. No measurement (empty or
    all-null) or an unrecognized/mixed kind → ``None`` (rendered as a ``GAP``,
    never a false ``0`` — AC4). Returns the raw value so the verdict can rank the
    numeric ones without re-parsing the rendered cell.
    """
    # Drop nulls and any non-finite number (a NaN/inf from a corrupted or
    # hand-edited scores file): neither is a measurement, and a NaN would poison a
    # mean into the nonsense cell "nan" (Codex US23 review). An all-null/all-NaN
    # dimension then falls through to a gap, never a false value.
    present = [
        value
        for value in values
        if value is not None and not (isinstance(value, float) and not math.isfinite(value))
    ]
    if not present:
        return None
    if all(isinstance(value, int) and not isinstance(value, bool) for value in present):
        # Pure counts: a representative value (median), not a mean one busy page
        # skews — matches the report's count-like dimensions (rule 02 case).
        return statistics.median(present)
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in present):
        return sum(present) / len(present)
    if all(isinstance(value, (str, bool)) for value in present):
        return _dominant(present)
    return None


def summarize_cell(values: list) -> str:
    """Render one model's values for one dimension as a scorecard cell string.

    The raw ``aggregate`` rendered: a number formatted compactly, a categorical
    dominant value as-is, and a no-measurement ``None`` as the ``GAP`` marker
    (AC4). Never crashes on an unsummarizable kind — it too renders a gap.
    """
    summary = aggregate(values)
    if summary is None:
        return GAP
    if isinstance(summary, (int, float)) and not isinstance(summary, bool):
        return _fmt_num(summary)
    return str(summary)


def _fmt_num(value: float) -> str:
    """Render a numeric summary compactly and deterministically.

    Rounds to 4 decimals (so a floating average never churns byte-for-byte on
    re-run, AC2) and formats with ``:g`` to trim trailing zeros — ``1.0`` → ``1``,
    ``0.9091`` stays ``0.9091`` — so the scorecard reads like the report's numbers.
    """
    return f"{round(value, 4):g}"


def _cell_values(records: list, model: str, dimension: str) -> list:
    """Every value one model recorded for one dimension, across its pages.

    A record contributes only when it is this model's and carries the dimension
    key at all — a row that never had the key (a reference-free row has no
    ``teds``) simply does not contribute, so a genuine gap stays a gap (AC4).
    """
    return [
        record[dimension]
        for record in records
        if record.get("model") == model and dimension in record
    ]


def _last_wins(records: list) -> list:
    """Collapse re-scored rows to the last one per (model, page, tier).

    ``scores.jsonl`` is append-only (the US21/US22 contract), so re-scoring a page
    appends a *second* row for it. Aggregating both would double-weight that page,
    so the newest row for each (model, page, reference-free-or-gold) key wins — a
    page is counted once. The reference-free row and the gold row for one page have
    different tiers, so both survive (they carry different dimensions).
    """
    collapsed = {}
    for record in records:
        key = (record.get("model"), record.get("page"), bool(record.get("gold")))
        collapsed[key] = record
    return list(collapsed.values())


def render_scorecard(records: list) -> str:
    """Render the stored score rows as a Markdown models × dimensions scorecard.

    One row per model, one column per dimension, each cell that model's dimension
    summarized across its pages (``summarize_cell``); a cell with no measurement
    is an explicit ``GAP`` (AC4). Both axes are derived from the records and
    sorted, so the artifact is deterministic (AC2) and a new model or dimension
    appears without a code edit (AC3). Re-scored rows collapse last-wins so a page
    is counted once (``_last_wins``).
    """
    records = _last_wins(records)
    model_ids = models(records)
    dims = dimensions(records)

    header = "| Model | " + " | ".join(dims) + " |"
    divider = "| --- | " + " | ".join("---" for _ in dims) + " |"
    rows = [header, divider]
    for model in model_ids:
        cells = [summarize_cell(_cell_values(records, model, dim)) for dim in dims]
        rows.append("| " + model + " | " + " | ".join(cells) + " |")

    verdicts = _verdicts(records, model_ids)
    return "# OCR Model Scorecard\n\n" + "\n".join(rows) + "\n\n" + verdicts + "\n"


def _numeric_summary(records: list, model: str, dimension: str):
    """One model's summarized value for a dimension, only if it is numeric.

    Returns the number a leader comparison ranks, or ``None`` when the model has
    no measurement for the dimension or the dimension is categorical — so a gap
    never masquerades as a rankable score.
    """
    summary = aggregate(_cell_values(records, model, dimension))
    if isinstance(summary, (int, float)) and not isinstance(summary, bool):
        return summary
    return None


def _leader(records: list, model_ids: list, dimension: str):
    """The single model that is *strictly* best on one directional dimension.

    Best is the min (lower-is-better) or max (higher-is-better) across the models
    that have a numeric value; a tie for best has no unique leader (returns
    ``None``), so the verdict never breaks a tie arbitrarily and stays
    deterministic (AC2).
    """
    scored = [(model, _numeric_summary(records, model, dimension)) for model in model_ids]
    scored = [(model, value) for model, value in scored if value is not None]
    if not scored:
        return None
    best = (min if dimension in _LOWER_IS_BETTER else max)(value for _, value in scored)
    winners = [model for model, value in scored if value == best]
    return winners[0] if len(winners) == 1 else None


def _verdicts(records: list, model_ids: list) -> str:
    """A short verdict line per model: the directional dimensions it leads.

    Presents the dimensions side by side (each model's category wins), *not* a
    single weighted ranking — that weighting is deferred until the dimension
    panel stabilizes (the story's "Later stages"). A model that leads nothing
    reads ``leads: none``.
    """
    directional = [dim for dim in dimensions(records) if dim in _HIGHER_IS_BETTER or dim in _LOWER_IS_BETTER]
    leaders = {dim: _leader(records, model_ids, dim) for dim in directional}
    lines = ["## Verdict", ""]
    for model in model_ids:
        led = sorted(dim for dim, leader in leaders.items() if leader == model)
        lines.append(f"- **{model}** — leads: {', '.join(led) if led else 'none'}")
    return "\n".join(lines)


def _load_records(scores_path: Path, manifest_path: Path) -> list:
    """Read the score rows from ``scores.jsonl``, holding the never-crash line.

    A malformed line (not JSON, or valid JSON that is not an object) is skipped —
    it is not a score record — so a hand-edited or truncated file still renders.
    A well-formed record with no ``model`` cannot be placed in the models × … grid,
    so it is quarantined to ``manifest.jsonl`` (``stage="ocr-report"``) and left
    out, rather than crashing the aggregation (rule 02).
    """
    records = []
    if not scores_path.exists():
        return records
    try:
        text = scores_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # A non-text file (the wrong path — a PDF, an image) is a whole-file usage
        # error, not a per-record quarantine: fail with an actionable message, not
        # a decode traceback (rule 02 — never crash; mirrors score-gold's whole-file
        # ValueError). The CLI renders this as a clean BadParameter (exit 2).
        raise ValueError(f"{scores_path} is not a UTF-8 scores.jsonl (is it the right file?)") from exc
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        # The model keys a scorecard row (and is string-concatenated into it) and
        # the page keys the last-wins dedup tuple, so both must be well-typed: a
        # null/typed model would crash `sorted(models)`, a list page would be an
        # unhashable dedup key (Codex US23 review). A record that fails either is
        # unplaceable → quarantine it, never crash (rule 02).
        model = record.get("model")
        if not isinstance(model, str):
            _manifest.append(
                manifest_path, stage="ocr-report", record=record, reason="score record has no string model"
            )
            continue
        page = record.get("page")
        if page is not None and not isinstance(page, str):
            _manifest.append(
                manifest_path, stage="ocr-report", record=record, reason="score record has a non-string page"
            )
            continue
        records.append(record)
    return records


def ocr_report(
    scores_path: Path,
    *,
    report_path: Path = Path("report.md"),
    manifest_path: Path = Path("manifest.jsonl"),
) -> Path:
    """Aggregate ``scores.jsonl`` into the Markdown scorecard at ``report_path``.

    Reads the stored US21/US22 rows, renders the deterministic scorecard, and
    writes it — no model call, no score computed here (rule 02). Re-running on the
    same scores overwrites with byte-identical content (AC2). Returns the report
    path. Never crashes: unreadable lines are skipped and unplaceable records are
    quarantined (see ``_load_records``).
    """
    scores_path = Path(scores_path)
    report_path = Path(report_path)
    manifest_path = Path(manifest_path)

    records = _load_records(scores_path, manifest_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_scorecard(records), encoding="utf-8")
    return report_path


def _dominant(values: list) -> str:
    """The most common value, ties broken by sorted order (deterministic, AC2).

    ``max`` returns the first maximal element in iteration order, so iterating a
    sorted candidate list makes an equal-count tie resolve to the lowest-sorting
    value every run — the report never churns on an arbitrary tie.
    """
    candidates = sorted(set(str(value) for value in values))
    string_values = [str(value) for value in values]
    return max(candidates, key=string_values.count)


app = typer.Typer(
    add_completion=False,
    help="Aggregate the stored OCR scores into one Markdown scorecard (US23).",
)


@app.command()
def run(
    scores: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="the scores.jsonl written by score-ocr (US21) / score-gold (US22)",
        ),
    ] = Path("scores.jsonl"),
    report: Annotated[
        Path,
        typer.Option("--report", help="where to write the Markdown scorecard"),
    ] = Path("report.md"),
    manifest: Annotated[
        Path,
        typer.Option(help="manifest to quarantine unplaceable (no-model) records to"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Aggregate the scores; print the report path it wrote."""
    try:
        written = ocr_report(scores, report_path=report, manifest_path=manifest)
    except ValueError as exc:
        # A non-text / mis-pointed scores file surfaces as a clean usage error
        # (exit 2, no traceback), the way Typer renders bad parameters.
        raise typer.BadParameter(str(exc), param_hint="SCORES") from exc
    typer.echo(f"scorecard -> {written}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run ocr-report`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
