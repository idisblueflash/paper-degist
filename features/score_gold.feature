Feature: US22 — score-gold scores a model against an OmniDocBench gold subset

  As a maintainer who wants a true accuracy ranking, not just a defect count
  I want each model scored against a curated subset of OmniDocBench's gold
  annotations using its official per-element metrics
  So that "which model is most faithful" is a reproducible number, with no
  hand-labeling

  Scenario: Only pages in the target distribution are selected
    Given a gold page whose data_source is "newspaper", layout "single_column", language "english"
    When score-gold filters the subset
    Then that page is excluded from scoring

  Scenario: A faithful transcription scores a low text edit distance
    Given a gold page "Attention_Is_All_You_Need" with gold text "The Transformer uses stacked self-attention."
    And a saved model output that transcribes it faithfully
    When score-gold scores it against the gold
    Then the text_edit_distance dimension is recorded near zero

  Scenario: A gold table is scored with TEDS as its own dimension
    Given a gold page "Deep_Residual_Learning" carrying a two-row results table
    And a saved model output reproducing that table verbatim
    When score-gold scores it against the gold
    Then the teds dimension is recorded as a perfect one

  Scenario: A text-only page skips the table metric as not-applicable
    Given a gold page "Spaced_Repetition_and_Long-Term_Retention" with only prose, no table
    And a saved model output transcribing that prose
    When score-gold scores it against the gold
    Then the teds dimension is recorded not-applicable, never a false zero
