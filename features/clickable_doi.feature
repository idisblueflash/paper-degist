Feature: US11 — clickable DOI link in the resolve-oa quarantine record

  As a researcher reading manifest.jsonl by hand
  I want each resolve-oa quarantine that recovered a DOI to carry a clickable https://doi.org/… link
  So that I can click straight through to the paper instead of copy-pasting a bare DOI

  Scenario: A recovered DOI is quarantined with a clickable doi.org link
    Given a failed URL "https://doi.org/10.1016/j.learninstruc.2007.02.008" the OA index reports closed
    When resolve-oa looks it up
    Then the quarantine record carries a clickable link "https://doi.org/10.1016/j.learninstruc.2007.02.008"

  Scenario: A slug URL with no DOI carries no clickable link
    Given a failed URL "https://www.researchgate.net/publication/221605769_Generative_Adversarial_Networks" with no DOI
    When resolve-oa looks it up
    Then the quarantine record carries no clickable DOI link
