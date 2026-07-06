Feature: US14 — dedup-inputs collapses inputs that point at the same DOI

  As a researcher assembling a list of papers to fetch
  I want inputs that reach the same DOI collapsed to one
  So that a paper reached three ways is fetched once, not three times

  Scenario: Fold a doi.org link and its bare DOI to one paper (AC1)
    Given the input list:
      | input                                                   |
      | https://doi.org/10.1016/j.learninstruc.2007.02.008      |
      | 10.1016/j.learninstruc.2007.02.008                      |
    When dedup-inputs processes the list
    Then the kept inputs are exactly:
      | input                                              |
      | https://doi.org/10.1016/j.learninstruc.2007.02.008 |
    And "10.1016/j.learninstruc.2007.02.008" is recorded in the manifest as a duplicate of "https://doi.org/10.1016/j.learninstruc.2007.02.008"

  Scenario: Recognize a DOI embedded in a publisher URL path (AC2)
    Given the input list:
      | input                                                        |
      | https://journals.sagepub.com/doi/10.1177/002221949002300203  |
      | 10.1177/002221949002300203                                   |
    When dedup-inputs processes the list
    Then the kept inputs are exactly:
      | input                                                       |
      | https://journals.sagepub.com/doi/10.1177/002221949002300203 |

  Scenario: Pass through an input carrying no extractable DOI (AC3)
    Given the input list:
      | input                                    |
      | https://pubmed.ncbi.nlm.nih.gov/2303742/ |
      | https://pubmed.ncbi.nlm.nih.gov/2303742/ |
    When dedup-inputs processes the list
    Then the kept inputs are exactly:
      | input                                    |
      | https://pubmed.ncbi.nlm.nih.gov/2303742/ |
      | https://pubmed.ncbi.nlm.nih.gov/2303742/ |
