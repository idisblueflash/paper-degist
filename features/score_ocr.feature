Feature: US21 — score-ocr scores a saved OCR output on reference-free metrics

  As a maintainer comparing OCR models on a brand-new paper
  I want to score a saved Markdown output on deterministic defect metrics
  So that I can rank models on any page instantly and offline, without
  hand-correcting a gold reference first

  Scenario: A clean output is scored and joined with its manifest per-call fields
    Given a saved OCR output "out/qwen_qwen3-vl-4b/p02.md" transcribing a clean page
    And an ocr-page manifest record for that output with finish_reason "stop"
    When score-ocr scores it
    Then a scores record keyed by "qwen_qwen3-vl-4b" and "p02" is appended
    And that record carries the manifest finish_reason "stop"

  Scenario: A line-level repetition loop is flagged by dup_pct
    Given a saved OCR output "out/unlimited-ocr-mlx/p02.md" degenerated into a repeated line
    When score-ocr scores it
    Then the dup_pct dimension is scored high

  Scenario: Dehyphenation artifacts are counted independently of duplication
    Given a saved OCR output "out/deepseek-ocr_8bit/p02.md" full of "low- quality" breaks
    When score-ocr scores it
    Then the hyphen_artifacts dimension reports the count

  Scenario: Inline citation groups are counted
    Given a saved OCR output "out/qwen_qwen3-vl-4b/p05.md" carrying "semantic maps [51,53,75,82]"
    When score-ocr scores it
    Then the citation_groups dimension reports the count

  Scenario: An unreadable output is quarantined, never crashes
    Given a saved OCR output "out/deepseek-ocr_4bit/p09.md" whose bytes are not valid UTF-8
    When score-ocr scores it
    Then the output is quarantined with a "score-ocr" stage
    And no scores record is written
