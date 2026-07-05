Feature: US23 — ocr-report aggregates the stored scores into one scorecard

  As a maintainer deciding which OCR model the PDF path should adopt
  I want a step that aggregates all per-page scores into one Markdown scorecard
  of models × dimensions
  So that comparing models — including a newly added one — is a single
  regenerated report, not a manual re-read of raw outputs

  Scenario: The scorecard summarizes a model's dimension across its pages
    Given a scores.jsonl with dup_pct 0.0 and 20.0 on two pages for "qwen_qwen3-vl-4b"
    When ocr-report aggregates it
    Then the scorecard cell for "qwen_qwen3-vl-4b" dup_pct summarizes both pages

  Scenario: Regenerating with no new scores is byte-identical
    Given a scores.jsonl with a gold row for "deepseek-ocr_8bit"
    When ocr-report aggregates it twice
    Then the two reports are byte-identical

  Scenario: A newly scored model appears without a code change
    Given a scores.jsonl that also carries a new model "unlimited-ocr_v3"
    When ocr-report aggregates it
    Then the scorecard has a row for "unlimited-ocr_v3"

  Scenario: A not-applicable cell shows an explicit gap, never a false zero
    Given a scores.jsonl whose "qwen_qwen3-vl-4b" gold page has no table
    When ocr-report aggregates it
    Then the "qwen_qwen3-vl-4b" teds cell is an explicit gap, not a zero
