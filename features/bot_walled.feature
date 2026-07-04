Feature: US12 — fetch-one recognizes a bot-walled 403 and names the recovery lane

  As a researcher reading manifest.jsonl by hand
  I want a 403 from a known bot-walling source to say so and name the lane
  So that I know to route around it via resolve-oa, not retry or fix my URL

  Scenario: A ResearchGate 403 is tagged as a bot-wall pointing at resolve-oa
    Given a URL "https://www.researchgate.net/publication/287147155_The_Mnemonic_Keyword_Method" that returns HTTP 403
    When fetch-one processes the URL
    Then the manifest tags the URL blocked_by "researchgate.net"
    And the manifest reason names a bot-walled source pointing at resolve-oa

  Scenario: A PubMed 403 is flagged as bot-walled and abstract-only
    Given a URL "https://pubmed.ncbi.nlm.nih.gov/2303742/" that returns HTTP 403
    When fetch-one processes the URL
    Then the manifest tags the URL blocked_by "pubmed.ncbi.nlm.nih.gov"
    And the manifest reason flags an abstract-only page

  Scenario: A 403 from an unknown host keeps the generic record
    Given a URL "https://example.edu/papers/some-closed-paper" that returns HTTP 403
    When fetch-one processes the URL
    Then the manifest record carries no blocked_by host
