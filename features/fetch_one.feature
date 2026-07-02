Feature: US2 AC2 — fetch-one fetches a paper and saves it under files/

  As a researcher
  I want to fetch one paper from its URL
  So that I can handle the file later

  Scenario: Fetch a PDF and save it under files/
    Given a URL "https://arxiv.org/pdf/2602.00762" that returns a PDF
    When fetch-one processes the URL
    Then the file "2602.00762.pdf" is saved under files/

  Scenario: Fetch an HTML paper and save the raw HTML
    Given a URL "https://example.com/paper" that returns HTML
    When fetch-one processes the URL
    Then the file "paper.html" is saved under files/

  Scenario: A paywalled response is quarantined, not saved
    Given a URL "https://example.com/paywalled" that returns HTTP 403
    When fetch-one processes the URL
    Then no file is saved under files/
    And the URL is recorded in the manifest
