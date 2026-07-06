Feature: US31 — discover-batch fans queries across sources and merges the union

  As a researcher opening a topic review
  I want a driver that runs several topic queries across several discover
  sources and emits one merged, deduplicated candidate list
  So that one command casts the whole net instead of me running discover once
  per (query, source) pair and hand-merging the JSONL

  Scenario: Two queries fan across two sources and merge into one stream (AC1)
    Given the batch queries "state space models for long sequences" and "linear attention transformers"
    And a batch "arxiv" source returning one candidate
    And a batch "openalex" source returning one candidate
    When discover-batch runs
    Then every batch source saw both queries
    And the merged stream carries the arxiv and the openalex candidate
    And a discover-batch summary record is written to the manifest

  Scenario: The same paper under one normalized DOI is emitted once (AC2)
    Given the batch query "liquid time-constant networks"
    And two batch sources returning the same paper under DOI spellings "10.1016/j.neunet.2024.106789" and "https://doi.org/10.1016/J.NEUNET.2024.106789"
    When discover-batch runs
    Then only one merged candidate is emitted
    And the duplicate is filtered with reason "dedup-doi"

  Scenario: A DOI-less paper hit by both queries is emitted once (AC3)
    Given the batch queries "recurrent transformer language models" and "linear attention RNN hybrids"
    And a batch "arxiv" source returning the same DOI-less paper for every query
    When discover-batch runs
    Then only one merged candidate is emitted
    And the duplicate is filtered with reason "dedup-source-id"

  Scenario: An abstract-carrying duplicate replaces the bibliographic stub (AC4)
    Given the batch query "IO-aware exact attention kernels"
    And a batch "scholar-author" stub and a batch "openalex" duplicate carrying the abstract
    When discover-batch runs
    Then the merged candidate is the "openalex" copy

  Scenario: A rate-limited pair takes out only itself (AC5)
    Given the batch query "test-time training layers"
    And a batch "s2" source that rate-limits
    And a batch "arxiv" source returning one candidate
    When discover-batch runs
    Then the surviving batch candidates are still emitted

  Scenario: A batch where every pair returns nothing is quarantined (AC6)
    Given the batch query "qwertyuiop nonexistent retrieval zzzz"
    And a batch "arxiv" source returning no candidates
    When discover-batch runs
    Then the batch is quarantined with a "empty-batch" reason

  Scenario: Consecutive arXiv calls honor the etiquette interval (AC7)
    Given the batch queries "hardware-aware attention kernels" and "fused softmax implementations"
    And a batch "arxiv" source returning one candidate
    When discover-batch runs
    Then the batch waited the arXiv etiquette interval between the arXiv calls
