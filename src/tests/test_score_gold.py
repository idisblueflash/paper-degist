"""Unit tests for US22 score_gold (pytest).

One logical assertion per test (rule 05): each fails for exactly one reason. The
gold-referenced metrics are pure deterministic functions of two strings (a
model output and a gold annotation), so they are offline and fast. Distinct
example values per case (rule 08) label what each exercises.
"""

import json
from pathlib import Path

from paper_degist.score_gold import (
    matches_subset,
    normalized_edit_distance,
    score_gold,
    score_gold_page,
    teds,
)


# A small gold table shared by the TEDS and orchestrator cases (rule 08 — one
# recognizable value, reused where the tests are about the *same* table).
_GOLD_TABLE = (
    "<table><tr><td>Model</td><td>Score</td></tr>"
    "<tr><td>qwen</td><td>0.91</td></tr></table>"
)


# --- matches_subset: the academic/double-column/en filter (AC1) ---


def _attrs(**overrides) -> dict:
    """A page_attribute dict that matches the subset, minus any overrides."""
    return {
        "data_source": "academic_literature",
        "layout": "double_column",
        "language": "english",
        **overrides,
    }


def test_matches_subset_selects_an_academic_double_column_english_page():
    assert matches_subset(_attrs()) is True


def test_matches_subset_rejects_a_newspaper_data_source():
    assert matches_subset(_attrs(data_source="newspaper")) is False


def test_matches_subset_rejects_a_single_column_layout():
    assert matches_subset(_attrs(layout="single_column")) is False


def test_matches_subset_rejects_a_chinese_only_language():
    assert matches_subset(_attrs(language="simplified_chinese")) is False


def test_matches_subset_selects_an_en_ch_mixed_page():
    # The embedded-CJK case the pipeline specifically targets is kept.
    assert matches_subset(_attrs(language="en_ch_mixed")) is True


# --- score_gold_page: classify a gold page, dispatch one metric per type ---


_TEXT_ONLY_PAGE = {
    "layout_dets": [
        {"category_type": "title", "text": "Spaced Repetition", "order": 0},
        {"category_type": "text_block", "text": "It improves long-term retention.", "order": 1},
    ]
}


def _score(page, model_output, **kwargs) -> dict:
    return score_gold_page(page, model_output, model="qwen_qwen3-vl-4b", page="p02", **kwargs)


def test_text_edit_distance_is_zero_for_a_faithful_transcription(): # AC2
    faithful = "Spaced Repetition\nIt improves long-term retention."
    assert _score(_TEXT_ONLY_PAGE, faithful)["text_edit_distance"] == 0.0


def test_teds_is_not_applicable_when_the_page_has_no_table(): # AC4
    # A text-only page skips the table metric: recorded null (not-applicable),
    # never a false 0.0 that would poison the model's average TEDS.
    assert _score(_TEXT_ONLY_PAGE, "some transcription")["teds"] is None


_TABLE_PAGE = {"layout_dets": [{"category_type": "table", "html": _GOLD_TABLE, "order": 0}]}


def test_teds_scores_a_faithful_model_table_as_one(): # AC3
    # The model reproduced the gold table verbatim (an HTML <table> in its
    # output) → a perfect TEDS.
    assert _score(_TABLE_PAGE, f"Some prose.\n\n{_GOLD_TABLE}\n\nMore.")["teds"] == 1.0


def test_teds_is_zero_when_the_model_omits_the_table(): # AC3
    # The gold page HAS a table but the model produced none → a real 0.0 (the
    # model failed to reproduce it), distinct from the not-applicable null above.
    assert _score(_TABLE_PAGE, "prose only, no table at all")["teds"] == 0.0


def test_text_edit_distance_ignores_the_models_table_html(): # AC2/AC3 separation
    # A page with both prose and a table: the model's <table> HTML is scored by
    # TEDS, so it must NOT also inflate the text edit distance — a faithful
    # transcription of the prose stays near zero even though the output embeds a
    # big table block (regression from the US22 real E2E: it read 0.52).
    page = {
        "layout_dets": [
            {"category_type": "text_block", "text": "We present a residual learning framework.", "order": 0},
            {"category_type": "table", "html": _GOLD_TABLE, "order": 1},
        ]
    }
    output = f"We present a residual learning framework.\n\n{_GOLD_TABLE}\n"
    assert _score(page, output)["text_edit_distance"] < 0.1


# --- normalized_edit_distance: text fidelity to gold (AC2) ---


def test_normalized_edit_distance_is_zero_for_identical_text():
    gold = "The keyword method links a cue to a target word."
    assert normalized_edit_distance(gold, gold) == 0.0


# --- teds: table structure fidelity to gold (AC3) ---


def test_teds_is_one_for_an_identical_table():
    assert teds(_GOLD_TABLE, _GOLD_TABLE) == 1.0


def test_teds_gives_partial_credit_for_a_wrong_cell():
    # Same structure, one cell misread ("0.91" -> "091"): scores below a perfect
    # 1.0 but well above 0 — the right structure is still worth most of the score.
    pred = (
        "<table><tr><td>Model</td><td>Score</td></tr>"
        "<tr><td>qwen</td><td>091</td></tr></table>"
    )
    assert 0.0 < teds(pred, _GOLD_TABLE) < 1.0


# --- score_gold: read a saved model output, score it, append the row (file IO) ---


def _save_output(tmp_path: Path, text: str, *, model="qwen_qwen3-vl-4b", page="p02.md") -> Path:
    """Save a Markdown output under out/<model>/<page> — the ocr-page save shape."""
    out = tmp_path / "out" / model
    out.mkdir(parents=True)
    target = out / page
    target.write_text(text, encoding="utf-8")
    return target


def test_score_gold_appends_one_record_keyed_by_model_and_page(tmp_path: Path):
    output = _save_output(tmp_path, "Spaced Repetition\nIt improves long-term retention.")
    scores = tmp_path / "scores.jsonl"
    record = score_gold(output, _TEXT_ONLY_PAGE, scores_path=scores, manifest_path=tmp_path / "manifest.jsonl")
    assert (record["model"], record["page"]) == ("qwen_qwen3-vl-4b", "p02")


def test_score_gold_writes_the_row_to_scores_jsonl(tmp_path: Path):
    output = _save_output(tmp_path, "some text")
    scores = tmp_path / "scores.jsonl"
    score_gold(output, _TEXT_ONLY_PAGE, scores_path=scores, manifest_path=tmp_path / "manifest.jsonl")
    assert len(scores.read_text(encoding="utf-8").splitlines()) == 1


def _score_unreadable(tmp_path: Path):
    """Save a non-UTF-8 output and gold-score it; return (result, manifest_path)."""
    out = tmp_path / "out" / "deepseek-ocr"
    out.mkdir(parents=True)
    target = out / "p09.md"
    target.write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")
    manifest = tmp_path / "manifest.jsonl"
    result = score_gold(target, _TEXT_ONLY_PAGE, scores_path=tmp_path / "scores.jsonl", manifest_path=manifest)
    return result, manifest


def test_unreadable_output_returns_none(tmp_path: Path): # AC4-adjacent: never crash
    result, _ = _score_unreadable(tmp_path)
    assert result is None


def test_unreadable_output_quarantines_with_score_gold_stage(tmp_path: Path):
    _, manifest = _score_unreadable(tmp_path)
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["stage"] == "score-gold"


def test_unreadable_output_writes_no_scores_row(tmp_path: Path):
    _score_unreadable(tmp_path)
    assert not (tmp_path / "scores.jsonl").exists()


# --- score_gold_batch: load annotations, filter to the subset, score each page ---


def _annotations(tmp_path: Path, pages: list) -> Path:
    path = tmp_path / "OmniDocBench.json"
    path.write_text(json.dumps(pages), encoding="utf-8")
    return path


def _gold_page(image: str, *, attribute: dict, layout_dets: list) -> dict:
    return {
        "page_info": {"image_path": image, "page_attribute": attribute},
        "layout_dets": layout_dets,
    }


def test_batch_scores_a_matching_page_with_a_saved_output(tmp_path: Path):
    from paper_degist.score_gold import score_gold_batch

    _save_output(tmp_path, "Faithful transcription.", model="qwen_qwen3-vl-4b", page="acad01.md")
    page = _gold_page(
        "acad01.jpg",
        attribute=_attrs(),
        layout_dets=[{"category_type": "text_block", "text": "Faithful transcription.", "order": 0}],
    )
    scores = tmp_path / "scores.jsonl"
    score_gold_batch(
        _annotations(tmp_path, [page]), "qwen/qwen3-vl-4b",
        out_dir=tmp_path / "out", scores_path=scores, manifest_path=tmp_path / "manifest.jsonl",
    )
    assert len(scores.read_text(encoding="utf-8").splitlines()) == 1


def test_batch_skips_a_page_outside_the_subset(tmp_path: Path):
    from paper_degist.score_gold import score_gold_batch

    _save_output(tmp_path, "text", model="qwen_qwen3-vl-4b", page="news01.md")
    page = _gold_page(
        "news01.jpg",
        attribute=_attrs(data_source="newspaper"),
        layout_dets=[{"category_type": "text_block", "text": "text", "order": 0}],
    )
    scores = tmp_path / "scores.jsonl"
    score_gold_batch(
        _annotations(tmp_path, [page]), "qwen/qwen3-vl-4b",
        out_dir=tmp_path / "out", scores_path=scores, manifest_path=tmp_path / "manifest.jsonl",
    )
    assert not scores.exists()


def test_batch_quarantines_a_matching_page_with_no_saved_output(tmp_path: Path):
    from paper_degist.score_gold import score_gold_batch

    page = _gold_page(
        "acad02.jpg",
        attribute=_attrs(),
        layout_dets=[{"category_type": "text_block", "text": "unocr'd", "order": 0}],
    )
    manifest = tmp_path / "manifest.jsonl"
    score_gold_batch(
        _annotations(tmp_path, [page]), "qwen/qwen3-vl-4b",
        out_dir=tmp_path / "out", scores_path=tmp_path / "scores.jsonl", manifest_path=manifest,
    )
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["stage"] == "score-gold"


def test_batch_rejects_a_non_list_annotations_file(tmp_path: Path):
    # A malformed annotations file (a JSON object, not the expected list of page
    # objects) must fail with a clear message, not a cryptic AttributeError from
    # iterating a dict's keys (rule 02 — never crash on unexpected input).
    import pytest

    from paper_degist.score_gold import score_gold_batch

    bad = tmp_path / "OmniDocBench.json"
    bad.write_text(json.dumps({"page1": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="list of page"):
        score_gold_batch(bad, "qwen/qwen3-vl-4b", out_dir=tmp_path / "out",
                         scores_path=tmp_path / "s.jsonl", manifest_path=tmp_path / "m.jsonl")
