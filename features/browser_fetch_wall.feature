Feature: US35 — browser-fetch detects a wall captured instead of the paper

  As a researcher recovering a bot-walled paper through the browser lane
  I want browser-fetch to recognize when it rendered a login / consent / Cloudflare wall
  So that a wall is quarantined for me to log in and retry, not silently saved as the paper

  Scenario: A Cloudflare challenge is quarantined before it can be saved
    Given a dev-mode Chrome that renders a Cloudflare challenge for "https://www.researchgate.net/publication/221609650_Retrieval_Practice_Produces_More_Learning"
    When browser-fetch classifies the rendered capture
    Then no HTML file is saved under files/
    And the URL is recorded in the manifest with reason mentioning "wall"

  Scenario: A page that renders a different paper is quarantined as a wall
    Given a dev-mode Chrome that renders a different paper for "https://www.academia.edu/38654201/Distributed_Practice_in_Verbal_Recall_Tasks"
    When browser-fetch classifies the rendered capture
    Then no HTML file is saved under files/
    And the URL is recorded in the manifest with reason mentioning "wall"

  Scenario: A genuine paper page whose title reflects the URL is saved as before
    Given a dev-mode Chrome that renders the genuine paper titled "The Testing Effect in the Classroom" for "https://www.researchgate.net/publication/319012693_The_Testing_Effect_in_the_Classroom"
    When browser-fetch classifies the rendered capture
    Then the rendered HTML "319012693_The_Testing_Effect_in_the_Classroom.html" is saved under files/
    And a "saved" record is appended to the manifest with stage "browser-fetch"
