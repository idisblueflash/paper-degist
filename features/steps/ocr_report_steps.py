import json
import tempfile
from pathlib import Path

from behave import given, when, then

from paper_degist.ocr_report import GAP, dimensions, ocr_report


def _root(context):
    """A temp root holding scores.jsonl and the generated report for the scenario."""
    if not getattr(context, "root", None):
        context.root = Path(tempfile.mkdtemp())
    return context.root


def _write_scores(context, records: list) -> Path:
    """Write ``records`` as scores.jsonl under the scenario root."""
    scores = _root(context) / "scores.jsonl"
    scores.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    context.scores = scores
    return scores


def _report_row(report: str, model: str) -> str:
    """The one scorecard table row whose first cell is ``model``."""
    return next(line for line in report.splitlines() if line.startswith(f"| {model} "))


def _aggregate(context) -> str:
    """Run ocr-report and return the report text."""
    report_path = ocr_report(
        context.scores,
        report_path=_root(context) / "report.md",
        manifest_path=_root(context) / "manifest.jsonl",
    )
    context.report = report_path.read_text(encoding="utf-8")
    return context.report


# --- AC1: summarize a dimension across a model's pages ---


@given('a scores.jsonl with dup_pct 0.0 and 20.0 on two pages for "{model}"')
def step_scores_two_pages(context, model):
    _write_scores(
        context,
        [
            {"model": model, "page": "p01", "dup_pct": 0.0},
            {"model": model, "page": "p02", "dup_pct": 20.0},
        ],
    )


@when("ocr-report aggregates it")
def step_aggregate_once(context):
    _aggregate(context)


@then('the scorecard cell for "{model}" dup_pct summarizes both pages')
def step_cell_summarizes(context, model):
    col = dimensions([json.loads(line) for line in context.scores.read_text().splitlines()]).index("dup_pct")
    cells = [cell.strip() for cell in _report_row(context.report, model).split("|")[1:-1]]
    assert cells[col + 1] == "10", cells  # +1 for the leading Model cell; mean(0, 20) = 10


# --- AC2: deterministic regeneration ---


@given('a scores.jsonl with a gold row for "{model}"')
def step_scores_gold_row(context, model):
    _write_scores(context, [{"model": model, "page": "p01", "gold": True, "text_edit_distance": 0.3, "teds": 0.9}])


@when("ocr-report aggregates it twice")
def step_aggregate_twice(context):
    context.first = _aggregate(context).encode("utf-8")
    context.second = _aggregate(context).encode("utf-8")


@then("the two reports are byte-identical")
def step_reports_identical(context):
    assert context.first == context.second


# --- AC3: a new model flows through with no code change ---


@given('a scores.jsonl that also carries a new model "{model}"')
def step_scores_new_model(context, model):
    _write_scores(
        context,
        [
            {"model": "qwen_qwen3-vl-4b", "page": "p01", "dup_pct": 0.0},
            {"model": model, "page": "p01", "dup_pct": 12.0},
        ],
    )


@then('the scorecard has a row for "{model}"')
def step_has_row(context, model):
    assert _report_row(context.report, model)


# --- AC4: a not-applicable cell is an explicit gap, never a false zero ---


@given('a scores.jsonl whose "{model}" gold page has no table')
def step_scores_no_table(context, model):
    _write_scores(context, [{"model": model, "page": "p01", "gold": True, "text_edit_distance": 0.05, "teds": None}])


@then('the "{model}" teds cell is an explicit gap, not a zero')
def step_teds_gap(context, model):
    col = dimensions([json.loads(line) for line in context.scores.read_text().splitlines()]).index("teds")
    cells = [cell.strip() for cell in _report_row(context.report, model).split("|")[1:-1]]
    assert cells[col + 1] == GAP, cells
