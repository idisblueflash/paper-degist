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

  Scenario: A rate-limited API is quarantined with a distinct api-error reason (AC4)
    Given a topic query "protein language models for structure prediction"
    And an "s2" source that rate-limits the search
    When discover searches the "s2" source
    Then the query is quarantined with a "api-error" reason

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
