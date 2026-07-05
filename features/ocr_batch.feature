Feature: US28 — batch-OCR a page directory across the model registry

  As a maintainer running the OCR bench
  I want a step that walks a directory of rendered page images and OCRs every
  page with every registered model, spacing the calls with the recovery gap
  So that one command lays down the whole out/<model>/<page>.md grid the scorers
  and report already consume, instead of invoking ocr-page per pair by hand

  Scenario: Every page is OCR'd with every registered model
    Given a page directory "pages/SpacedRepetition" with pages:
      | page      |
      | p0001.png |
      | p0002.png |
    And the registered models "qwen/qwen3-vl-4b" and "deepseek-ocr"
    When ocr-batch runs over the directory
    Then ocr-page is called for every page and model pair
    And each saved Markdown path is returned

  Scenario: The recovery gap spaces consecutive server-hitting pairs
    Given a page directory "pages/TestingEffect" with pages:
      | page      |
      | p0001.png |
      | p0002.png |
    And the registered models "qwen/qwen3-vl-4b" and "deepseek-ocr"
    When ocr-batch runs over the directory
    Then a recovery gap is waited before each pair after the first

  Scenario: A pair already OCR'd is skipped with no server hit and no gap
    Given a page directory "pages/Interleaving" with pages:
      | page      |
      | p0001.png |
    And the registered models "qwen/qwen3-vl-4b"
    And the pair "p0001.png" + "qwen/qwen3-vl-4b" was already OCR'd in a prior run
    When ocr-batch runs over the directory
    Then ocr-page is not called for that pair
    And no recovery gap is waited

  Scenario: One quarantined pair never aborts the batch
    Given a page directory "pages/DesirableDifficulties" with pages:
      | page      |
      | p0001.png |
      | p0002.png |
    And the registered models "qwen/qwen3-vl-4b"
    And ocr-page quarantines the pair "p0001.png" + "qwen/qwen3-vl-4b"
    When ocr-batch runs over the directory
    Then the remaining pairs are still OCR'd
    And the quarantined pair is absent from the returned paths

  Scenario: Restricting the models runs only the named one
    Given a page directory "pages/SpacingRetention" with pages:
      | page      |
      | p0001.png |
    And the registered models "qwen/qwen3-vl-4b" and "deepseek-ocr"
    When ocr-batch runs restricted to model "deepseek-ocr"
    Then only "deepseek-ocr" is used across the grid
