Feature: US1 AC1 — parse-url extracts URLs from a text blob

  As a researcher
  I want to parse a text blob into a list of URLs
  So that I can fetch each one later

  Scenario: Extract every URL from a text blob
    Given the text blob "src/tests/samples/mnemonic-method-bayesian-analysis.md"
    When parse-url processes the text
    Then we get a list of 9 URLs
    And the list contains "https://arxiv.org/pdf/2602.00762"
    And the list contains "https://rdw.rowan.edu/cgi/viewcontent.cgi?article=1080&context=etd"
    And no URL appears more than once
