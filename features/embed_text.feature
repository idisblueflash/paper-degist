Feature: US24 — embed-text embeds one text with one registered model

  As a maintainer building the abstract filter
  I want to send one text to one named embedding model over the stable transport
  So that the filter has a cheap, offline, deterministic similarity signal and a
  flaky server never crashes it

  Scenario: A registered model returns a vector, saved under out/embeddings/<model>/
    Given a text to embed "Spaced repetition improves long-term retention."
    And an embedding server that returns a vector for a registered model
    When embed-text embeds the text with model "nomic-embed-text-v1.5" and role "document"
    Then the vector is saved under "out/embeddings/nomic-embed-text-v1.5/"
    And an embed record for "nomic-embed-text-v1.5" is written to the manifest

  Scenario: A re-run does not re-hit the flaky server
    Given a text to embed "Retrieval practice strengthens memory."
    And the text was already embedded by model "nomic-embed-text-v1.5" with role "document"
    When embed-text embeds the text with model "nomic-embed-text-v1.5" and role "document"
    Then the embedding server is not contacted

  Scenario: A flapping server returning 502 is quarantined after the retry budget
    Given a text to embed "Interleaving beats blocked practice."
    And an embedding server that always returns 502
    When embed-text embeds the text with model "nomic-embed-text-v1.5" and role "document"
    Then the text is quarantined with a "server unreachable" reason

  Scenario: An unregistered model is quarantined without touching the network
    Given a text to embed "Elaborative interrogation aids comprehension."
    When embed-text embeds the text with model "some-unregistered-embed" and role "document"
    Then the text is quarantined with a "unknown model" reason
    And the embedding server is not contacted
