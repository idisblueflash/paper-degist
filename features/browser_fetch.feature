Feature: US15 — browser-fetch captures a bot-walled page through a dev-mode Chrome

  As a researcher recovering a paper that 403s a plain fetch
  I want a step that drives a dev-mode Chrome to fetch one URL's rendered HTML
  So that a bot-walled page is captured through a real browser session, not lost to the wall

  Scenario: A reachable dev-mode Chrome renders the page and saves the HTML
    Given a dev-mode Chrome reachable at "http://localhost:9222"
    And a bot-walled URL "https://www.researchgate.net/publication/220320021_Spaced_Repetition_and_Long-Term_Retention"
    When browser-fetch navigates to it and the DOM settles
    Then the rendered HTML "220320021_Spaced_Repetition_and_Long-Term_Retention.html" is saved under files/
    And a "saved" record is appended to the manifest with stage "browser-fetch"

  Scenario: No dev-mode Chrome reachable — the URL is quarantined, not lost
    Given no dev-mode Chrome is reachable at "http://localhost:9222"
    And a bot-walled URL "https://www.researchgate.net/publication/234567890_Retrieval_Practice_Produces_More_Learning"
    When browser-fetch cannot connect
    Then no HTML file is saved under files/
    And the URL is recorded in the manifest with reason mentioning "browser-up"

  Scenario: Chrome is reachable but the navigation fails — a distinct reason
    Given a dev-mode Chrome reachable at "http://localhost:9222"
    And a bot-walled URL "https://www.researchgate.net/publication/319012693_The_Testing_Effect_in_the_Classroom" whose navigation fails
    When browser-fetch cannot render the page
    Then no HTML file is saved under files/
    And the URL is recorded in the manifest with reason mentioning "navigation failed"

  Scenario: A URL already saved by a prior run is skipped
    Given the HTML "200000001_Interleaving_Improves_Mathematics_Learning.html" was already saved under files/
    And a bot-walled URL "https://www.researchgate.net/publication/200000001_Interleaving_Improves_Mathematics_Learning"
    When browser-fetch runs again on the same URL
    Then the saved HTML file is left unchanged
    And no new record is appended to the manifest
