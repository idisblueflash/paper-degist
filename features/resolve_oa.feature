Feature: US9 — resolve open access for a failed fetch

  As a researcher
  I want to verify whether a failed fetch has an open-access copy
  So that I can download it for free, or know precisely why I cannot

  Scenario: An open-access paper resolves to its PDF URL
    Given a failed URL "https://doi.org/10.1371/journal.pone.0000308" the OA index reports open at "https://oa.example.org/paper.pdf"
    When resolve-oa looks it up
    Then resolve-oa outputs the OA PDF URL "https://oa.example.org/paper.pdf"

  Scenario: A closed-access paper is quarantined with a precise reason
    Given a failed URL "https://doi.org/10.1191/1362168805lr151oa" the OA index reports closed
    When resolve-oa looks it up
    Then the input is quarantined with reason "no OA copy (closed access)"

  Scenario: A slug URL with no DOI is routed to the human/browser lane
    Given a failed URL "https://www.researchgate.net/publication/249870239_An_investigation" with no DOI
    When resolve-oa looks it up
    Then the input is quarantined with a reason mentioning "no DOI"

  # US30 — cross-check a closed Unpaywall verdict against OpenAlex

  Scenario: OpenAlex has an OA copy Unpaywall reported closed
    Given a failed URL "https://doi.org/10.1145/3292500.3330701" Unpaywall reports closed but OpenAlex has an OA PDF at "https://repository.example.org/openalex.pdf"
    When resolve-oa looks it up
    Then resolve-oa outputs the OA PDF URL "https://repository.example.org/openalex.pdf"

  Scenario: Both indexes agree the paper is closed
    Given a failed URL "https://doi.org/10.1038/s41586-021-03819-2" both Unpaywall and OpenAlex report closed
    When resolve-oa looks it up
    Then the input is quarantined with reason "no OA copy (closed access) — checked Unpaywall and OpenAlex"

  Scenario: Unpaywall already resolves, so OpenAlex is never consulted
    Given a failed URL "https://doi.org/10.1109/CVPR.2016.90" Unpaywall reports open at "https://oa.example.org/resnet.pdf" and OpenAlex must not be consulted
    When resolve-oa looks it up
    Then resolve-oa outputs the OA PDF URL "https://oa.example.org/resnet.pdf"

  Scenario: The OpenAlex fallback errors while Unpaywall reported closed
    Given a failed URL "https://doi.org/10.1162/neco.1997.9.8.1735" Unpaywall reports closed and the OpenAlex fallback errors
    When resolve-oa looks it up
    Then the input is quarantined with a reason mentioning "OpenAlex OA lookup error"
