Feature: US5 — convert-html converts a saved HTML paper into Markdown

  As a researcher
  I want to convert an HTML paper into an MD file
  So that I can process it with an LLM later

  Scenario: Convert an HTML paper, preserving its structure as Markdown
    Given a saved HTML file "paper.html" with a heading and body text
    When convert-html processes the file
    Then the Markdown file "paper.md" is saved under files/
    And the heading is preserved as Markdown

  Scenario: A hollow SPA shell is quarantined as too thin, not saved
    Given a saved HTML file "spa.html" that is a hollow SPA shell
    When convert-html processes the file
    Then no Markdown file is saved for it
    And the file is recorded in the manifest with reason "HTML too thin"
