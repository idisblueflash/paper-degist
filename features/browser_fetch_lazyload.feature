Feature: US40 — browser-fetch captures lazy-loaded full-text through an interactive wall

  As a researcher recovering an open-access paper from a JavaScript-heavy publisher
  I want browser-fetch to wait on a settle signal, clear a wall by hand once, and save only a loaded body
  So that the full-text HTML is captured cleanly instead of a "Loading…" stub or a false navigation timeout

  Scenario: A body still showing the "Loading…" placeholder is quarantined, not saved as a header-only stub
    Given a dev-mode Chrome that renders a lazy-load stub for "https://doi.org/10.1016/j.artmed.2021.102083"
    When browser-fetch classifies the rendered capture
    Then no HTML file is saved under files/
    And the URL is recorded in the manifest with reason mentioning "not loaded"

  Scenario: Once the lazy-loaded body fills above the readiness threshold, the full-text HTML is saved
    Given a dev-mode Chrome that renders the fully loaded ScienceDirect body for "https://doi.org/10.1016/j.jbi.2018.12.005"
    When browser-fetch classifies the rendered capture
    Then the rendered full-text HTML is saved under files/
    And a "saved" record is appended to the manifest with stage "browser-fetch"

  Scenario: A DOI URL is not mistaken for a wall by the title-slug mismatch check
    Given a dev-mode Chrome that renders the fully loaded ScienceDirect body for "https://doi.org/10.1016/j.jbi.2018.12.005"
    When browser-fetch classifies the rendered capture
    Then the rendered full-text HTML is saved under files/

  Scenario: In the default unattended mode a detected wall is quarantined and the batch never blocks
    Given a dev-mode Chrome that renders a Cloudflare challenge for the DOI "https://doi.org/10.1016/j.jbi.2018.12.005"
    When browser-fetch classifies the rendered capture in unattended mode
    Then no HTML file is saved under files/
    And the URL is recorded in the manifest with reason mentioning "wall"

  Scenario: In interactive mode the operator clears the wall by hand once and the capture auto-resumes
    Given a walled page that the operator clears between polls, then loads the full body
    When browser-fetch polls the page in interactive mode
    Then the operator is notified once to clear the wall by hand
    And the captured HTML is the fully loaded body, never the wall
