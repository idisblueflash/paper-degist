Feature: snowball — expand a seed paper into references and citers via OpenAlex (US33)

  Scenario: AC1 — refs direction emits papers the seed cites
    Given a seed paper "10.48550/arxiv.1706.03762" with references:
      | openalex_id | doi             | title                              | cited_by |
      | W200        | 10.5555/lstm    | Long Short-Term Memory             | 2800     |
      | W300        | 10.5555/seq2seq | Sequence to Sequence Learning      | 5100     |
    When snowball runs with direction "refs"
    Then the snowball output titles are:
      | title                              |
      | Long Short-Term Memory             |
      | Sequence to Sequence Learning      |

  Scenario: AC2 — citers direction emits papers that cite the seed
    Given a seed paper "10.18653/v1/N19-1423" with citers:
      | openalex_id | doi                    | title                                               | cited_by |
      | W400        | 10.5555/roberta        | RoBERTa: A Robustly Optimized BERT Pretraining Approach | 18000  |
    When snowball runs with direction "citers"
    Then the snowball output titles include "RoBERTa: A Robustly Optimized BERT Pretraining Approach"

  Scenario: AC3 — both direction emits refs then citers, deduplicating overlaps
    Given a seed paper "10.1162/tacl_a_00051" with references:
      | openalex_id | doi             | title                         | cited_by |
      | W200        | 10.5555/lstm    | Long Short-Term Memory        | 2800     |
    And the same seed has citers:
      | openalex_id | doi          | title                                               | cited_by |
      | W400        | 10.5555/bert | BERT: Pre-training of Deep Bidirectional Transformers | 42000   |
    When snowball runs with direction "both"
    Then the snowball output titles are:
      | title                                               |
      | Long Short-Term Memory                              |
      | BERT: Pre-training of Deep Bidirectional Transformers |

  Scenario: AC5 — unresolvable seed is quarantined, nothing emitted
    Given a seed "10.9999/does-not-exist-in-openalex" that raises a not-found error
    When snowball runs with direction "both"
    Then nothing is emitted by snowball
    And the snowball manifest has a quarantined row for the seed

  Scenario: AC6 — a work with no URL is filtered, the rest still emit
    Given a seed paper "10.48550/arxiv.2112.10741" with references:
      | openalex_id | doi           | title        | cited_by |
      |             |               |              |          |
      | W_good      | 10.5555/good  | Perceiver IO | 500      |
    When snowball runs with direction "refs"
    Then the snowball output titles include "Perceiver IO"
    And the snowball manifest has a filtered row with reason "no-url"
