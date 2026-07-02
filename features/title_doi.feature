Feature: US10 — resolve a DOI from a title (Crossref)

  As a researcher
  I want to recover a paper's DOI from the title in a slug-only URL
  So that resolve-oa can check open access automatically instead of stopping at "no DOI"

  Scenario: A slug URL's title resolves to a DOI and an open-access PDF
    Given a slug URL "https://www.researchgate.net/publication/220320653_Attention_Is_All_You_Need" whose title Crossref resolves to a DOI, open at "https://oa.example.org/attention.pdf"
    When resolve-oa resolves it via title lookup
    Then resolve-oa outputs the OA PDF URL "https://oa.example.org/attention.pdf"

  Scenario: A title Crossref cannot confidently match is routed to the human/browser lane
    Given a slug URL "https://www.academia.edu/38547921/Deep_Residual_Learning_for_Image_Recognition" whose title Crossref cannot confidently match
    When resolve-oa resolves it via title lookup
    Then the input is quarantined with reason "title→DOI: no confident Crossref match (route to human/browser)"

  Scenario: A Crossref lookup error is quarantined, not raised
    Given a slug URL "https://www.researchgate.net/publication/328693788_BERT_Pre-training_of_Deep_Bidirectional_Transformers" whose Crossref lookup errors
    When resolve-oa resolves it via title lookup
    Then the input is quarantined with a reason mentioning "title→DOI lookup error"
