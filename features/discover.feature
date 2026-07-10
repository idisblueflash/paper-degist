Feature: US25 — discover finds candidate papers by topic from a scholarly API

  As a researcher starting a topic review
  I want a step that searches a scholarly API for a topic and emits each
  candidate paper with its abstract as one JSONL record
  So that the pipeline has a wide-net list to filter, instead of me pasting URLs
  by hand — and a zero-result or a rate-limited API never crashes it

  Scenario: An arXiv search with hits emits one JSONL record per candidate (AC1)
    Given a topic query "sparse mixture-of-experts routing"
    And an "arxiv" source that returns 2 candidates
    When discover searches the "arxiv" source
    Then 2 candidate records are emitted
    And a discover record with result_count 2 is written to the manifest

  Scenario: A Semantic Scholar search carries the tldr pre-filter signal (AC2)
    Given a topic query "CRISPR base editing off-target effects"
    And an "s2" source whose candidate carries a tldr "A one-line summary of the paper."
    When discover searches the "s2" source
    Then the emitted record carries the tldr "A one-line summary of the paper."

  Scenario: A hit with no abstract is kept and flagged, not dropped (AC3)
    Given a topic query "graph neural network expressivity"
    And an "arxiv" source whose candidate has no abstract
    When discover searches the "arxiv" source
    Then the emitted record has a null abstract flagged abstract_present false

  Scenario: A zero-result query is quarantined with a distinct empty-result reason (AC4)
    Given a topic query "qwertyuiop nonexistent topic zzzz"
    And an "arxiv" source that returns no candidates
    When discover searches the "arxiv" source
    Then the query is quarantined with a "empty-result" reason

  Scenario: A hard API error is quarantined with a distinct api-error reason (AC4)
    Given a topic query "protein language models for structure prediction"
    And an "s2" source that errors
    When discover searches the "s2" source
    Then the query is quarantined with a "api-error" reason

  # --- US38: a rate-limit (HTTP 429) is a distinct, retriable case ---

  Scenario: A source that rate-limits once recovers on retry (US38 AC1)
    Given a topic query "mixture of experts routing stability"
    And an "arxiv" source that rate-limits once then returns 2 candidates
    When discover searches the "arxiv" source with a retry budget of 3
    Then 2 candidate records are emitted

  Scenario: A source that stays rate-limited quarantines as rate-limited-exhausted (US38 AC2)
    Given a topic query "retrieval augmented generation latency"
    And an "s2" source that always rate-limits
    When discover searches the "s2" source with a retry budget of 1
    Then the query is quarantined with a "rate-limited-exhausted" reason

  Scenario: An unknown source is quarantined without touching the network (AC5)
    Given a topic query "single-cell RNA sequencing batch correction"
    When discover searches the "pubmed" source
    Then the query is quarantined with a "unknown source" reason
    And the scholarly API is not contacted

  # --- US29: the OpenAlex adapter (keyless, mailto polite pool) ---

  Scenario: OpenAlex reconstructs the abstract from its inverted index (US29 AC2)
    Given a topic query "graph neural networks for molecular property prediction"
    And an "openalex" work whose abstract arrives as an inverted index
    When discover searches the "openalex" source
    Then the emitted record abstract reads "Graph neural networks predict molecular properties"

  Scenario: An OpenAlex hit carries its open-access pdf_url up front (US29 AC3)
    Given a topic query "neural message passing for quantum chemistry"
    And an "openalex" source whose candidate carries a pdf_url "https://arxiv.org/pdf/1704.01212"
    When discover searches the "openalex" source
    Then the emitted record carries the pdf_url "https://arxiv.org/pdf/1704.01212"

  Scenario: OpenAlex with no contact email warns but still searches (US29 AC4)
    Given a topic query "sparse mixture-of-experts routing"
    When discover runs the openalex CLI with no contact email
    Then a polite-pool warning is emitted
    And the openalex search is still run

  # --- US27: the two SerpAPI Google Scholar sources ---

  Scenario: A Scholar organic hit carries its open-access pdf_url up front (US27 AC2)
    Given a topic query "retrieval-augmented generation for code"
    And a "scholar" organic hit whose open resource is a pdf "https://arxiv.org/pdf/2108.11601"
    When discover searches the "scholar" source
    Then the emitted record carries the pdf_url "https://arxiv.org/pdf/2108.11601"

  Scenario: A Scholar organic hit carries its cited_by count (US27 AC1)
    Given a topic query "sparse retrieval for open-domain question answering"
    And a "scholar" organic hit cited 214 times
    When discover searches the "scholar" source
    Then the emitted record carries the cited_by count 214

  Scenario: A Scholar author article is bibliographic with a null abstract (US27 AC3)
    Given an author id "JicYPdAAAAAJ"
    And a "scholar-author" profile with one bibliographic article
    When discover searches the "scholar-author" source
    Then the emitted record has a null abstract flagged abstract_present false

  Scenario: A Scholar source with no SerpAPI key is quarantined offline (US27 AC4)
    Given a topic query "diffusion models for protein backbone generation"
    And a "scholar" source with no SerpAPI key
    When discover searches the "scholar" source
    Then the query is quarantined with a "missing-key" reason
