"""Unit tests for US23 ocr_report (pytest).

One logical assertion per test (rule 05): each fails for exactly one reason. The
aggregation is a pure deterministic function of the stored ``scores.jsonl`` rows
(US21 reference-free + US22 gold), so every test is offline and fast. Distinct
example values per case (rule 08) label what each exercises.
"""

import json
from pathlib import Path

from paper_degist.ocr_report import (
    GAP,
    composite_accuracy,
    dimensions,
    models,
    ocr_report,
    render_scorecard,
    summarize_cell,
)


def _write_scores(tmp_path: Path, records: list) -> Path:
    """Write ``records`` as a scores.jsonl under ``tmp_path`` and return its path."""
    scores = tmp_path / "scores.jsonl"
    scores.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return scores


# A small mixed scores.jsonl: two models, US21 reference-free rows + a US22 gold
# row each. deepseek loops (high dup_pct) but is faithful on the one gold table;
# qwen is clean text but drops the table. Distinct values per cell (rule 08) so a
# rendered cell names what it measures.
def _scores() -> list:
    return [
        {"model": "qwen_qwen3-vl-4b", "page": "p01", "dup_pct": 0.0, "citation_groups": 5, "cjk_present": True},
        {"model": "qwen_qwen3-vl-4b", "page": "p02", "dup_pct": 0.0, "citation_groups": 7, "cjk_present": True},
        {"model": "qwen_qwen3-vl-4b", "page": "p01", "gold": True, "text_edit_distance": 0.05, "teds": None},
        {"model": "deepseek-ocr_8bit", "page": "p01", "dup_pct": 95.0, "citation_groups": 0, "cjk_present": False},
        {"model": "deepseek-ocr_8bit", "page": "p01", "gold": True, "text_edit_distance": 0.4, "teds": 0.91},
    ]


# --- summarize_cell: dispatch a summarizer by the dimension's value kind ---


def test_summarize_empty_values_is_a_gap():
    assert summarize_cell([]) == GAP


def test_summarize_all_null_values_is_a_gap():  # AC4: not-applicable, never a false 0
    assert summarize_cell([None, None]) == GAP


def test_summarize_float_values_are_averaged():
    # ratio/score dimensions (dup_pct, text_edit_distance, teds) → their mean.
    assert summarize_cell([0.0, 0.4]) == "0.2"


def test_summarize_int_values_are_a_representative_median():
    # count-like dimensions (hyphen_artifacts, citation_groups) → a representative,
    # not a mean an outlier page skews: median([0, 0, 4]) = 0, not 1.33.
    assert summarize_cell([0, 0, 4]) == "0"


def test_summarize_string_values_are_the_dominant_value():
    # categorical finish_reason → the value that dominates the model's pages.
    assert summarize_cell(["stop", "stop", "length"]) == "stop"


def test_summarize_bool_values_are_the_dominant_value():
    # categorical cjk_present → whether the model read the CJK on most pages.
    assert summarize_cell([True, True, False]) == "True"


def test_summarize_mixed_type_values_is_a_gap():
    # An unrecognized/mixed kind can't be summarized — gap, never crash (rule 02).
    assert summarize_cell(["stop", 1]) == GAP


# --- models / dimensions: both derived from the records, never hard-coded ---


def test_models_are_the_sorted_unique_model_ids():
    records = [{"model": "qwen_qwen3-vl-4b"}, {"model": "deepseek-ocr_8bit"}, {"model": "qwen_qwen3-vl-4b"}]
    assert models(records) == ["deepseek-ocr_8bit", "qwen_qwen3-vl-4b"]


def test_dimensions_exclude_the_identity_keys():
    # model/page/gold identify a row; they are not scored dimensions.
    records = [{"model": "qwen_qwen3-vl-4b", "page": "p02", "gold": True, "teds": 0.9}]
    assert dimensions(records) == ["teds"]


# --- render_scorecard: the models × dimensions table + a verdict per model ---


def _row(report: str, model: str) -> str:
    """The one Markdown table row whose first cell is ``model``."""
    return next(line for line in report.splitlines() if line.startswith(f"| {model} "))


def test_render_summarizes_a_models_dimension_cell():  # AC1
    # deepseek's dup_pct across its one reference-free page is 95.
    report = render_scorecard(_scores())
    cells = [cell.strip() for cell in _row(report, "deepseek-ocr_8bit").split("|")]
    assert "95" in cells


def test_render_shows_a_gap_for_an_unmeasured_cell():  # AC4
    # qwen's one gold page carries no table → its teds is not-applicable, a gap,
    # not a false 0 that would read as "reproduced no table correctly".
    report = render_scorecard(_scores())
    teds_col = dimensions(_scores()).index("teds") + 1  # +1 for the leading Model cell
    cells = [cell.strip() for cell in _row(report, "qwen_qwen3-vl-4b").split("|")[1:-1]]
    assert cells[teds_col] == GAP


def test_render_new_model_appears_as_its_own_row():  # AC3
    # A model only registered + scored (no code change) gets its own row.
    records = _scores() + [{"model": "unlimited-ocr_v3", "page": "p01", "dup_pct": 12.0}]
    report = render_scorecard(records)
    assert _row(report, "unlimited-ocr_v3")


def test_render_verdict_names_the_dimension_a_model_leads():
    # deepseek is the only model with a real teds (qwen dropped the table), so it
    # leads the table dimension — the verdict says so.
    report = render_scorecard(_scores())
    verdict = next(line for line in report.splitlines() if "deepseek-ocr_8bit" in line and "leads" in line)
    assert "teds" in verdict


def test_render_re_scored_page_counts_once_last_wins():
    # scores.jsonl is append-only (US21/US22 flag): re-scoring a page appends a
    # second row. The scorecard must count that page once — the last (newest) row
    # wins — so a re-run does not double-weight it. Here p01's dup_pct is re-scored
    # 90 → 0; the cell is the last value (0), not mean(90, 0) = 45.
    records = [
        {"model": "qwen_qwen3-vl-4b", "page": "p01", "dup_pct": 90.0},
        {"model": "qwen_qwen3-vl-4b", "page": "p01", "dup_pct": 0.0},
    ]
    cells = [cell.strip() for cell in _row(render_scorecard(records), "qwen_qwen3-vl-4b").split("|")]
    assert "0" in cells and "45" not in cells


# --- composite accuracy: a derived, higher-is-better roll-up of the two gold
# accuracy metrics (teds ↑ and 1 - text_edit_distance ↑) onto one 0–1 axis ---


def test_composite_accuracy_averages_teds_and_flipped_edit_distance():
    # deepseek's gold page: teds 0.91 (table) and text_edit_distance 0.4 (text).
    # accuracy = mean(0.91, 1 - 0.4) = mean(0.91, 0.6) = 0.755 — both halves on a
    # single higher-is-better axis.
    assert composite_accuracy(_scores(), "deepseek-ocr_8bit") == 0.755


def test_composite_accuracy_is_none_without_both_components():  # AC4-style gap
    # qwen's gold page has no table (teds null), so the table half is missing —
    # the composite is not-applicable (None → a gap), never a half-score.
    assert composite_accuracy(_scores(), "qwen_qwen3-vl-4b") is None


def test_render_shows_the_accuracy_column():
    # the derived roll-up appears as its own scorecard column (the header row).
    assert "accuracy" in render_scorecard(_scores()).splitlines()[2]


def test_render_accuracy_cell_is_the_composite_score():
    # deepseek's trailing accuracy cell is its composite 0.755.
    report = render_scorecard(_scores())
    cells = [cell.strip() for cell in _row(report, "deepseek-ocr_8bit").split("|")]
    assert "0.755" in cells


def test_render_accuracy_cell_is_a_gap_when_not_computable():  # AC4
    # qwen cannot form a composite (no table) → its accuracy cell is a gap, the
    # trailing column, not a false score.
    report = render_scorecard(_scores())
    cells = [cell.strip() for cell in _row(report, "qwen_qwen3-vl-4b").split("|")[1:-1]]
    assert cells[-1] == GAP


def test_render_verdict_ranks_accuracy():
    # deepseek is the only model with a computable accuracy, so it leads it — the
    # composite is ranked in the verdict like a real directional dimension.
    report = render_scorecard(_scores())
    verdict = next(line for line in report.splitlines() if "deepseek-ocr_8bit" in line and "leads" in line)
    assert "accuracy" in verdict


def test_render_accuracy_column_not_duplicated_by_a_stray_key():
    # The derived composite owns the "accuracy" column: a stray stored "accuracy"
    # key in scores.jsonl must not surface a *second* identical column (which would
    # also misalign every row's cells against the header).
    records = _scores() + [{"model": "deepseek-ocr_8bit", "page": "p09", "accuracy": 0.5}]
    header = render_scorecard(records).splitlines()[2]  # the header row
    assert header.count("accuracy") == 1


# --- ocr_report: read scores.jsonl, write the report, quarantine the unplaceable ---


def test_ocr_report_writes_the_scorecard_to_the_report_file(tmp_path: Path):
    scores = _write_scores(tmp_path, _scores())
    report = tmp_path / "report.md"
    ocr_report(scores, report_path=report, manifest_path=tmp_path / "manifest.jsonl")
    assert report.read_text(encoding="utf-8").startswith("# OCR Model Scorecard")


def test_ocr_report_is_byte_identical_on_regeneration(tmp_path: Path):  # AC2
    scores = _write_scores(tmp_path, _scores())
    report = tmp_path / "report.md"
    manifest = tmp_path / "manifest.jsonl"
    ocr_report(scores, report_path=report, manifest_path=manifest)
    first = report.read_bytes()
    ocr_report(scores, report_path=report, manifest_path=manifest)
    assert report.read_bytes() == first


def _only_manifest_record(manifest: Path) -> dict:
    """The single record in a one-line manifest.jsonl."""
    return json.loads(manifest.read_text(encoding="utf-8").strip())


def test_ocr_report_quarantines_a_record_with_no_model(tmp_path: Path):
    scores = _write_scores(tmp_path, [{"page": "p01", "dup_pct": 3.0}])
    manifest = tmp_path / "manifest.jsonl"
    ocr_report(scores, report_path=tmp_path / "report.md", manifest_path=manifest)
    assert _only_manifest_record(manifest)["stage"] == "ocr-report"


def test_ocr_report_quarantines_a_non_string_model_without_crashing(tmp_path: Path):
    # A null/typed model can't key a scorecard row — quarantine it, never let it
    # reach the sorted-models crash (Codex US23 review).
    scores = _write_scores(tmp_path, [{"model": None, "page": "p01", "dup_pct": 0.9}])
    manifest = tmp_path / "manifest.jsonl"
    ocr_report(scores, report_path=tmp_path / "report.md", manifest_path=manifest)
    assert _only_manifest_record(manifest)["stage"] == "ocr-report"


def test_ocr_report_quarantines_a_non_string_page_without_crashing(tmp_path: Path):
    # A list/typed page is unhashable in the last-wins dedup key — quarantine it,
    # never let it reach the unhashable-key crash (Codex US23 review).
    scores = _write_scores(tmp_path, [{"model": "qwen_qwen3-vl-4b", "page": ["p01"], "dup_pct": 0.9}])
    manifest = tmp_path / "manifest.jsonl"
    ocr_report(scores, report_path=tmp_path / "report.md", manifest_path=manifest)
    assert _only_manifest_record(manifest)["stage"] == "ocr-report"


def test_ocr_report_non_finite_value_renders_a_gap_not_nan(tmp_path: Path):
    # A NaN/inf from a corrupted scores file is not a measurement — the cell is a
    # gap, never the nonsense string "nan" (Codex US23 review).
    scores = _write_scores(tmp_path, [{"model": "qwen_qwen3-vl-4b", "page": "p01", "dup_pct": float("nan")}])
    report = tmp_path / "report.md"
    ocr_report(scores, report_path=report, manifest_path=tmp_path / "manifest.jsonl")
    body = report.read_text(encoding="utf-8")
    assert "nan" not in body and GAP in body


def test_ocr_report_rejects_a_non_utf8_file_with_a_clean_error(tmp_path: Path):
    # Pointing at the wrong file (a binary PDF) is a whole-file usage error, not a
    # per-record quarantine — it surfaces as a ValueError, never a decode traceback.
    scores = tmp_path / "not-scores.pdf"
    scores.write_bytes(b"%PDF-\xc4\xff binary")
    import pytest

    with pytest.raises(ValueError, match="UTF-8"):
        ocr_report(scores, report_path=tmp_path / "report.md", manifest_path=tmp_path / "manifest.jsonl")


def test_ocr_report_skips_a_malformed_line_without_crashing(tmp_path: Path):
    scores = tmp_path / "scores.jsonl"
    scores.write_text('{"model": "qwen_qwen3-vl-4b", "dup_pct": 1.0}\nnot json\n', encoding="utf-8")
    report = tmp_path / "report.md"
    ocr_report(scores, report_path=report, manifest_path=tmp_path / "manifest.jsonl")
    assert "qwen_qwen3-vl-4b" in report.read_text(encoding="utf-8")
