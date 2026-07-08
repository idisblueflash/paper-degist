Feature: US 37 — provenance frontmatter on each collected paper

  As a researcher staging converted papers into a wiki
  I want each paper's .md to carry its doi/url/pdf_url/venue as frontmatter
  So that a paper's citation and download provenance travel with the file

  Scenario: fetch-batch writes a provenance sidecar next to each fetched paper
    Given a candidates file with a record for "https://arxiv.org/pdf/2602.00762.pdf" carrying doi "10.5555/smart"
    When fetch-batch runs over the candidates
    Then a sidecar carrying doi "10.5555/smart" is written next to the saved file

  Scenario: a candidate record with no url is quarantined and the batch continues
    Given a candidates file whose first record has no url and whose second is "https://arxiv.org/pdf/1706.03762.pdf"
    When fetch-batch runs over the candidates
    Then the url-less record is quarantined to stage "fetch-batch"
    And the second paper is still saved

  Scenario: convert stamps the frontmatter from the sidecar
    Given a fetched HTML paper whose sidecar carries venue "Cognition"
    When convert-html runs on it
    Then the .md begins with a YAML frontmatter block

  Scenario: a paper with no sidecar gets no frontmatter
    Given a fetched HTML paper with no sidecar
    When convert-html runs on it
    Then the .md has no frontmatter block
