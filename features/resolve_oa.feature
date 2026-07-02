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
