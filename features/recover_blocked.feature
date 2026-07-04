Feature: US17 — recover bot-walled records through the browser lane

  As a researcher who just ran fetch-one over a list
  I want a step that reads the bot-walled records fetch-one quarantined and feeds
  their URLs to browser-fetch
  So that the papers blocked by a wall are retried through my real browser
  automatically, instead of me copying each blocked URL out of the manifest by hand

  Scenario: Only the blocked_by records are routed; generic quarantines are ignored
    Given a manifest of fetch-one quarantines:
      | url                                                                                  | blocked_by                |
      | https://www.researchgate.net/publication/287147155_The_Mnemonic_Keyword_Method       | researchgate.net          |
      | https://example.edu/papers/some-closed-paper                                         |                           |
      | https://pubmed.ncbi.nlm.nih.gov/2303742/                                             | pubmed.ncbi.nlm.nih.gov   |
    And a warm dev-mode Chrome for the recovery lane
    When recover-blocked routes the blocked records
    Then only the blocked_by URLs are dispatched to browser-fetch
    And the generic quarantine URL is not dispatched

  Scenario: The blocked URLs are fetched over browser-fetch's one warm session
    Given a manifest of fetch-one quarantines:
      | url                                                                                  | blocked_by                |
      | https://www.researchgate.net/publication/220320021_Spaced_Repetition               | researchgate.net          |
      | https://pubmed.ncbi.nlm.nih.gov/9911554/                                             | pubmed.ncbi.nlm.nih.gov   |
    And a warm dev-mode Chrome for the recovery lane
    When recover-blocked routes the blocked records
    Then the browser lane opens exactly one warm connection for the batch

  Scenario: A recovered URL gains a new manifest record, leaving the original untouched
    Given a manifest of fetch-one quarantines:
      | url                                                                                  | blocked_by                |
      | https://www.researchgate.net/publication/319012693_The_Testing_Effect               | researchgate.net          |
    And a warm dev-mode Chrome for the recovery lane
    When recover-blocked routes the blocked records
    Then a new browser-fetch recovery record is appended for that URL
    And the original blocked_by record is still present unchanged

  Scenario: With no dev-mode Chrome the blocked URLs wait, and the step exits cleanly
    Given a manifest of fetch-one quarantines:
      | url                                                                                  | blocked_by                |
      | https://www.researchgate.net/publication/331004374_Desirable_Difficulties           | researchgate.net          |
    And no dev-mode Chrome for the recovery lane
    When recover-blocked routes the blocked records
    Then that URL stays quarantined with a missing-browser reason
    And recover-blocked recovers nothing and does not crash

  Scenario: A URL already recovered in a prior run is not dispatched again
    Given a manifest of fetch-one quarantines:
      | url                                                                                  | blocked_by                |
      | https://www.researchgate.net/publication/200000001_Interleaving_Improves_Maths      | researchgate.net          |
    And that URL was already recovered by browser-fetch in a prior run
    And a warm dev-mode Chrome for the recovery lane
    When recover-blocked routes the blocked records
    Then that URL is not dispatched to browser-fetch again
