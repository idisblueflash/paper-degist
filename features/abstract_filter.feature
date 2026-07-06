Feature: US26 — abstract-filter narrows discover output by abstract similarity

  As a researcher triaging a wide-net candidate list
  I want the obviously-irrelevant candidates dropped and the rest ranked by how
  close their abstract is to my topic
  So that only a short, on-topic shortlist reaches fetch-one

  Scenario: The deterministic pass drops a duplicate and an abstract-less hit before embedding (AC1)
    Given the candidate list:
      | url     | doi                  | present | signal | abstract                                    |
      | u/first | 10.1038/nature24644  | true    | on     | A contrastive objective for speech units.   |
      | u/dup   | 10.1038/NATURE24644  | true    | on     | The same paper reached by a different link. |
      | u/noabs |                      | false   | on     |                                             |
    When abstract-filter narrows the list for topic "contrastive learning for speech representations"
    Then the kept candidate urls are exactly "u/first"
    And "u/dup" is filtered with reason "dedup-doi"
    And "u/noabs" is filtered with reason "no-abstract"
    And exactly 1 abstract was embedded

  Scenario: A topically close candidate is kept with its similarity attached (AC2)
    Given the candidate list:
      | url  | doi | present | signal | abstract                                     |
      | u/on | | true | on | Self-supervised contrastive speech encoders. |
    When abstract-filter narrows the list for topic "contrastive learning for speech representations"
    Then the kept candidate urls are exactly "u/on"
    And "u/on" is kept with a similarity score

  Scenario: A below-threshold candidate is dropped with an auditable record (AC3)
    Given the candidate list:
      | url   | doi | present | signal | abstract                                   |
      | u/off | | true | off | CRISPR base editing off-target prediction. |
    When abstract-filter narrows the list for topic "contrastive learning for speech representations"
    Then the shortlist is empty
    And "u/off" is filtered with reason "below-threshold"

  Scenario: The shortlist is ranked by descending similarity (AC4)
    Given the candidate list:
      | url    | doi | present | signal | abstract                                  |
      | u/far  | | true | far  | Loosely related representation learning.  |
      | u/near | | true | near | Contrastive speech representation models. |
    When abstract-filter narrows the list for topic "contrastive learning for speech representations"
    Then the kept candidate urls in order are "u/near, u/far"

  Scenario: One embed failure quarantines only that candidate; the batch completes (AC5)
    Given the candidate list:
      | url    | doi | present | signal | abstract                                 |
      | u/down | | true | down | The server is down for this abstract.    |
      | u/ok   | | true | on   | Contrastive learning of speech features. |
    When abstract-filter narrows the list for topic "contrastive learning for speech representations"
    Then the kept candidate urls are exactly "u/ok"
    And "u/down" is quarantined with reason "embed-unavailable"
