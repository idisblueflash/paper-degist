Feature: rank-cited — rank candidates by citation count, keep the top N (US32)

  Scenario: AC1 — candidates ranked by descending cited_by, records unchanged
    Given a rank-cited candidate pool:
      | title                                                               | url                                           | cited_by |
      | Longformer: The Long-Document Transformer                           | https://arxiv.org/abs/2004.05150              | 187      |
      | Attention Is All You Need                                           | https://arxiv.org/abs/1706.03762              | 9041     |
      | Big Bird: Transformers for Longer Sequences                         | https://arxiv.org/abs/2007.14062              | 512      |
    When rank-cited runs with top 20
    Then the ranked output titles in order are:
      | title                                             |
      | Attention Is All You Need                         |
      | Big Bird: Transformers for Longer Sequences       |
      | Longformer: The Long-Document Transformer         |

  Scenario: AC2 — top-N cut emits only N and logs beyond-top filtered rows
    Given a rank-cited candidate pool:
      | title                                                  | url                                           | cited_by |
      | GShard: Scaling Giant Models with MoE                  | https://arxiv.org/abs/2006.16668              | 1450     |
      | Sparsely-Gated Mixture-of-Experts                      | https://arxiv.org/abs/1701.06538              | 3120     |
      | GLaM: Efficient Scaling of Language Models with MoE   | https://arxiv.org/abs/2112.06905              | 690      |
      | Switch Transformers: Scaling to Trillion Parameter     | https://arxiv.org/abs/2101.03961              | 2205     |
    When rank-cited runs with top 2
    Then exactly 2 candidates are emitted
    And the rank-cited manifest has a filtered row with reason "beyond-top" for "https://arxiv.org/abs/2006.16668"

  Scenario: AC3 — candidate without cited_by is dropped; zero cited_by ranks
    Given a rank-cited candidate pool:
      | title                                           | url                                           | cited_by |
      | xLSTM: Extended Long Short-Term Memory          | https://arxiv.org/abs/2405.04517              | 0        |
      | H3: Language Modeling with State Space Models   | https://arxiv.org/abs/2212.14052              | 402      |
      | Mamba: Linear-Time Sequence Modeling            | https://arxiv.org/abs/2312.00752              |          |
    When rank-cited runs with top 20
    Then the ranked output titles in order are:
      | title                                           |
      | H3: Language Modeling with State Space Models   |
      | xLSTM: Extended Long Short-Term Memory          |
    And the rank-cited manifest has a filtered row with reason "no-cited-by" for "https://arxiv.org/abs/2312.00752"

  Scenario: AC4 — tied cited_by keeps input order (stable sort)
    Given a rank-cited candidate pool:
      | title                                                        | url                                                | cited_by |
      | Compressive Transformers for Long-Range Sequence Modelling   | https://arxiv.org/abs/1911.05507                   | 764      |
      | Transformer-XL: Attentive Language Models Beyond Fixed-Length| https://arxiv.org/abs/1901.02860                   | 764      |
    When rank-cited runs with top 20
    Then the ranked output titles in order are:
      | title                                                        |
      | Compressive Transformers for Long-Range Sequence Modelling   |
      | Transformer-XL: Attentive Language Models Beyond Fixed-Length|

  Scenario: AC5 — malformed input line is quarantined, rest continue
    Given a rank-cited input with a garbage line among valid candidates:
      | title                                           | url                                           | cited_by |
      | Hyena Hierarchy: Towards Larger Convolutional   | https://arxiv.org/abs/2302.10866              | 381      |
    When rank-cited runs on the mixed input with top 20
    Then the garbage line is quarantined with stage "rank-cited"
    And the valid candidate is still emitted

  Scenario: AC6 — nothing rankable quarantines with empty-rank reason, prints nothing
    Given a rank-cited candidate pool:
      | title                              | url                              | cited_by |
      | Griffin: Mixing Gated Linear Rec   | https://arxiv.org/abs/2402.19427 |          |
    When rank-cited runs with top 20
    Then nothing is printed to stdout
    And the rank-cited manifest has an empty-rank quarantine row
