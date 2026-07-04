Feature: US20 — ocr-page OCRs one page with one registered model

  As a maintainer benchmarking OCR models
  I want to send one page image to one named model over the stable transport
  So that adding or re-testing a model is a single command and the flaky server
  never crashes the bench

  Scenario: A registered model's answer is post-processed and saved with an ocr record
    Given a page image "p02.png" and the registered model "qwen/qwen3-vl-4b"
    And the server answers 200 with the Markdown "# WordCraft\n\nBody."
    When ocr-page sends the page over the transport
    Then the Markdown is saved as "out/qwen_qwen3-vl-4b/p02.md"
    And an ocr record for "qwen/qwen3-vl-4b" is written to the manifest

  Scenario: A page already OCR'd for that model is skipped without hitting the server
    Given a page image "p03.png" already OCR'd by "qwen/qwen3-vl-4b" in a prior run
    When ocr-page sends the page over the transport
    Then the server is not hit again
    And no new record is written to the manifest

  Scenario: A flapping server is retried, then the page is quarantined
    Given a page image "p04.png" and the registered model "deepseek-ocr-2"
    And the server keeps returning 502
    When ocr-page sends the page over the transport
    Then the page is quarantined with reason naming "server unreachable after retries"
    And no Markdown is saved for it

  Scenario: An unregistered model is quarantined distinctly, without the network
    Given a page image "p05.png" and the unregistered model "some-unregistered-ocr"
    When ocr-page sends the page over the transport
    Then the server is not hit at all
    And the page is quarantined with reason naming "unknown model"
