"""Unit tests for US21 score_ocr (pytest).

One logical assertion per test (rule 05): each fails for exactly one reason. The
reference-free scorers are pure text functions, so most tests are offline and
fast; the manifest join and the quarantine path use a temp ``out/`` tree.
Distinct example outputs per case (rule 08) label what each exercises.
"""

import json
from pathlib import Path

from paper_degist.score_ocr import (
    citation_groups,
    cjk_present,
    dup_pct,
    hyphen_artifacts,
    score_ocr,
)


# --- dup_pct: duplicate substantive-line ratio (AC2 — the degeneration metric) ---


def test_dup_pct_is_zero_for_all_distinct_lines():
    text = "# Vocabulary Acquisition\n\nThe keyword method links a cue to a target.\n\nResults follow."
    assert dup_pct(text) == 0.0


def test_dup_pct_flags_a_repetition_loop_high():
    # A degenerated loop: one line repeated across 20 substantive lines → 95%
    # duplicates (19 of the 20 repeat the first).
    text = "\n".join(["the same looping line"] * 20)
    assert dup_pct(text) == 95.0


def test_dup_pct_flags_a_loop_emitted_on_a_single_line():
    # A model that emits the whole page on one line (no newlines) defeats
    # line-based duplication detection; the loop must still be caught by falling
    # back to sentence segmentation. 20 identical sentences on one line → 95%.
    text = " ".join(["The model looped this sentence."] * 20)
    assert dup_pct(text) == 95.0


def test_dup_pct_excludes_repeated_horizontal_rules():
    # `---` rules are legitimate repeated boilerplate: repeating them must NOT
    # inflate the score (the report's known false positive).
    text = "First distinct paragraph.\n\n---\n\nSecond distinct paragraph.\n\n---\n\nThird distinct."
    assert dup_pct(text) == 0.0


# --- hyphen_artifacts: `word- word` dehyphenation leaks (AC3) ---


def test_hyphen_artifacts_counts_word_space_breaks():
    text = "The low- quality scan of the L1- Chinese glossary was hard to read."
    assert hyphen_artifacts(text) == 2


def test_hyphen_artifacts_ignores_a_clean_hyphenated_compound():
    # A real hyphenated compound (no space after the hyphen) is not an artifact.
    assert hyphen_artifacts("a well-formed state-of-the-art result") == 0


def test_hyphen_artifacts_counts_adjacent_breaks_independently():
    # Two artifacts sharing a word ("b") must both count — the match must not
    # consume the following word char (Codex review: overlapping undercount).
    assert hyphen_artifacts("a- b- c") == 2


# --- citation_groups: inline numeric citation lists (AC4) ---


def test_citation_groups_counts_bracketed_number_lists():
    text = "semantic maps [51,53,75,82] and spaced practice [12] both help retention."
    assert citation_groups(text) == 2


def test_citation_groups_ignores_non_numeric_brackets():
    assert citation_groups("see the appendix [A] and the figure [Fig. 3]") == 0


# --- cjk_present: the reads-the-language signal (case handling) ---


def test_cjk_present_true_when_chinese_survives():
    assert cjk_present("The L1 gloss 记忆 was transcribed faithfully.") is True


def test_cjk_present_false_for_ascii_only_output():
    assert cjk_present("An all-English transcription with no CJK codepoints.") is False


# --- orchestrator: shared arrange/act (rule 05 — factor setup into a helper) ---


def _save_output(tmp_path: Path, text: str, *, model="qwen_qwen3-vl-4b", page="p02.md") -> Path:
    """Save a Markdown output under out/<model>/<page>, the ocr-page save shape."""
    out = tmp_path / "out" / model
    out.mkdir(parents=True)
    target = out / page
    target.write_text(text, encoding="utf-8")
    return target


def _run(tmp_path: Path, text="# Clean page\n\nDistinct body text.", **save_kwargs):
    """Score a saved output; return (record, scores_path, manifest_path)."""
    output = _save_output(tmp_path, text, **save_kwargs)
    scores = tmp_path / "scores.jsonl"
    manifest = tmp_path / "manifest.jsonl"
    record = score_ocr(output, scores_path=scores, manifest_path=manifest)
    return record, scores, manifest


def _only_score(scores: Path) -> dict:
    (line,) = scores.read_text(encoding="utf-8").splitlines()
    return json.loads(line)


# --- AC1: one scores.jsonl record keyed by (model, page) with every dimension ---


def test_score_record_keys_model_from_the_slug_dir(tmp_path: Path):
    record, _, _ = _run(tmp_path, model="deepseek-ocr_8bit")
    assert record["model"] == "deepseek-ocr_8bit"


def test_score_record_keys_page_from_the_stem(tmp_path: Path):
    record, _, _ = _run(tmp_path, page="p07.md")
    assert record["page"] == "p07"


def test_score_appends_one_record_to_scores_jsonl(tmp_path: Path):
    _, scores, _ = _run(tmp_path)
    assert len(scores.read_text(encoding="utf-8").splitlines()) == 1


def test_score_record_carries_every_reference_free_dimension(tmp_path: Path):
    _, scores, _ = _run(tmp_path)
    got = set(_only_score(scores))
    assert {"dup_pct", "hyphen_artifacts", "citation_groups", "cjk_present"} <= got


# --- AC1: joins the manifest-sourced per-call fields (finish_reason/latency/tokens) ---


def _write_ocr_record(manifest: Path, *, model, page, **fields) -> None:
    record = {"stage": "ocr-page", "model": model, "page": page, **fields}
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def test_score_joins_finish_reason_from_the_manifest(tmp_path: Path):
    output = _save_output(tmp_path, "# Doc", model="qwen_qwen3-vl-4b", page="p02.md")
    manifest = tmp_path / "manifest.jsonl"
    _write_ocr_record(
        manifest, model="qwen/qwen3-vl-4b", page="pages/WordCraft/p02.png",
        finish_reason="length", latency=20.8, completion_tokens=167,
    )
    record = score_ocr(output, scores_path=tmp_path / "scores.jsonl", manifest_path=manifest)
    assert record["finish_reason"] == "length"


def test_score_joins_completion_tokens_from_the_manifest(tmp_path: Path):
    output = _save_output(tmp_path, "# Doc", model="qwen_qwen3-vl-4b", page="p02.md")
    manifest = tmp_path / "manifest.jsonl"
    _write_ocr_record(
        manifest, model="qwen/qwen3-vl-4b", page="pages/WordCraft/p02.png",
        finish_reason="stop", latency=20.8, completion_tokens=167,
    )
    record = score_ocr(output, scores_path=tmp_path / "scores.jsonl", manifest_path=manifest)
    assert record["completion_tokens"] == 167


def test_score_manifest_fields_are_none_when_no_ocr_record_matches(tmp_path: Path):
    # No manifest at all: the per-call fields are present but null, not missing.
    _, scores, _ = _run(tmp_path)
    assert _only_score(scores)["finish_reason"] is None


def test_score_survives_a_non_object_manifest_line(tmp_path: Path):
    # A valid-JSON but non-object line (`[]`, hand-edited / mis-shaped) must be
    # skipped, not crash the join (Codex review: never-crash invariant).
    output = _save_output(tmp_path, "# Doc", model="qwen_qwen3-vl-4b", page="p02.md")
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("[]\n", encoding="utf-8")
    record = score_ocr(output, scores_path=tmp_path / "scores.jsonl", manifest_path=manifest)
    assert record is not None


def test_score_ignores_a_quarantine_record_for_the_join(tmp_path: Path):
    # An ocr-page *quarantine* row (no finish_reason) must not satisfy the join.
    output = _save_output(tmp_path, "# Doc", model="qwen_qwen3-vl-4b", page="p02.md")
    manifest = tmp_path / "manifest.jsonl"
    _write_ocr_record(
        manifest, model="qwen/qwen3-vl-4b", page="pages/WordCraft/p02.png",
        reason="server unreachable after 3 attempts",
    )
    record = score_ocr(output, scores_path=tmp_path / "scores.jsonl", manifest_path=manifest)
    assert record["finish_reason"] is None


# --- AC5: an unreadable output quarantines to manifest, skips, never crashes ---


def _score_unreadable(tmp_path: Path):
    """Save a non-UTF-8 output and score it; return (result, manifest_path)."""
    out = tmp_path / "out" / "qwen_qwen3-vl-4b"
    out.mkdir(parents=True)
    target = out / "p02.md"
    target.write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")
    manifest = tmp_path / "manifest.jsonl"
    result = score_ocr(target, scores_path=tmp_path / "scores.jsonl", manifest_path=manifest)
    return result, manifest


def test_unreadable_output_returns_none(tmp_path: Path):
    result, _ = _score_unreadable(tmp_path)
    assert result is None


def test_unreadable_output_writes_no_scores_row(tmp_path: Path):
    _score_unreadable(tmp_path)
    assert not (tmp_path / "scores.jsonl").exists()


def test_unreadable_output_quarantines_with_score_ocr_stage(tmp_path: Path):
    _, manifest = _score_unreadable(tmp_path)
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["stage"] == "score-ocr"


def test_unreadable_output_quarantine_names_the_model(tmp_path: Path):
    _, manifest = _score_unreadable(tmp_path)
    (line,) = manifest.read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["model"] == "qwen_qwen3-vl-4b"
