Feature: US20 — ocr-page OCRs one page image with one registered model

  As a maintainer benchmarking OCR models
  I want to send one page image to one named model over the stable transport
  So that adding or re-testing a model is a single command and the flaky
  server never crashes the bench

  Scenario: A registered model returns Markdown, saved under out/<model>/
    Given a saved page image "p02.png"
    And a vision server that returns Markdown for a registered model
    When ocr-page OCRs the page with model "qwen/qwen3-vl-4b"
    Then the Markdown is saved as "out/qwen_qwen3-vl-4b/p02.md"
    And an ocr record for "qwen/qwen3-vl-4b" is written to the manifest

  Scenario: A re-run does not re-hit the flaky server
    Given a saved page image "p05.png"
    And the page was already OCR'd by model "qwen/qwen3-vl-4b"
    When ocr-page OCRs the page with model "qwen/qwen3-vl-4b"
    Then the vision server is not contacted

  Scenario: A flapping server returning 502 is quarantined after the retry budget
    Given a saved page image "p09.png"
    And a vision server that always returns 502
    When ocr-page OCRs the page with model "qwen/qwen3-vl-4b"
    Then the page and model are quarantined with a "server unreachable" reason

  Scenario: An unregistered model is quarantined without touching the network
    Given a saved page image "p12.png"
    When ocr-page OCRs the page with model "some-unregistered-ocr"
    Then the page and model are quarantined with a "unknown model" reason
    And the vision server is not contacted
