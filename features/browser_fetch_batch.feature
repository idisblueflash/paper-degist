Feature: US16 — browser-fetch reuses one warm browser across a batch of URLs

  As a researcher checking many bot-walled URLs in one run
  I want browser-fetch to reuse a single long-running Chrome across the whole list
  So that every URL rides the same warm, authenticated session instead of paying a
  cold browser and a fresh login per URL

  Scenario: One warm connection serves the whole list, in order
    Given a warm dev-mode Chrome reachable at "http://localhost:9222"
    And a batch of bot-walled URLs:
      | url                                                                                        |
      | https://www.researchgate.net/publication/220320021_Spaced_Repetition_and_Long-Term_Retention |
      | https://www.researchgate.net/publication/234567890_Retrieval_Practice_Produces_More_Learning |
    When browser-fetch processes the whole batch
    Then the CDP connection is opened exactly once
    And every URL's rendered HTML is saved under files/
    And the saved paths are returned in first-seen order

  Scenario: The batch detaches at the end, leaving the warm browser for the next run
    Given a warm dev-mode Chrome reachable at "http://localhost:9222"
    And a batch of bot-walled URLs:
      | url                                                                              |
      | https://www.researchgate.net/publication/200000001_Interleaving_Improves_Mathematics_Learning |
    When browser-fetch processes the whole batch
    Then the warm browser is left running after the batch detaches

  Scenario: One URL's navigation failure never aborts the batch
    Given a warm dev-mode Chrome reachable at "http://localhost:9222"
    And a batch of bot-walled URLs:
      | url                                                                                     |
      | https://www.researchgate.net/publication/319012693_The_Testing_Effect_in_the_Classroom  |
      | https://www.researchgate.net/publication/331004374_Desirable_Difficulties_in_Learning   |
    And the URL "https://www.researchgate.net/publication/319012693_The_Testing_Effect_in_the_Classroom" whose navigation fails
    When browser-fetch processes the whole batch
    Then the URL "https://www.researchgate.net/publication/319012693_The_Testing_Effect_in_the_Classroom" is quarantined with a navigation reason
    And the other URLs are still saved under files/
