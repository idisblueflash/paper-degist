Feature: enrich-abstract — fill missing abstracts from OpenAlex (US34)

  Scenario: AC1 — candidate with missing abstract is enriched from OpenAlex
    Given a candidate "10.18653/v1/N19-1423" without an abstract
    And the OpenAlex work for "10.18653/v1/N19-1423" has abstract "We introduce BERT."
    When enrich-abstract runs
    Then the output contains the candidate with abstract "We introduce BERT."
    And the output candidate has abstract_present true

  Scenario: AC2 — candidate with abstract passes through unchanged
    Given a candidate "10.48550/arxiv.1706.03762" with abstract "Attention is all you need."
    When enrich-abstract runs
    Then the output contains the candidate with abstract "Attention is all you need."

  Scenario: AC3 — candidate with no DOI is quarantined
    Given a candidate without a doi or abstract
    When enrich-abstract runs
    Then nothing is emitted by enrich-abstract
    And the enrich-abstract manifest has a quarantined row with reason "no-doi"

  Scenario: AC4 — candidate whose DOI is not found in OpenAlex is quarantined
    Given a candidate "10.9999/does-not-exist-paper" without an abstract
    And the OpenAlex lookup for "10.9999/does-not-exist-paper" raises a not-found error
    When enrich-abstract runs
    Then nothing is emitted by enrich-abstract
    And the enrich-abstract manifest has a quarantined row with reason "doi-not-found"

  Scenario: AC5 — work with no abstract_inverted_index is quarantined
    Given a candidate "10.1162/tacl_a_00051" without an abstract
    And the OpenAlex work for "10.1162/tacl_a_00051" has no abstract on record
    When enrich-abstract runs
    Then nothing is emitted by enrich-abstract
    And the enrich-abstract manifest has a quarantined row with reason "no-abstract-on-record"

  Scenario: AC6 — non-JSON input line is quarantined, well-formed candidates run
    Given a candidate JSONL input with one garbage line and one valid candidate "10.48550/arxiv.2205.14135" with abstract "FlashAttention abstract."
    When enrich-abstract runs
    Then the output contains the candidate with abstract "FlashAttention abstract."
    And the enrich-abstract manifest has a quarantined row for the garbage line
