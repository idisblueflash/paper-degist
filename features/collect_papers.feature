Feature: US 36 — collect-papers copies converted MDs to a target folder

  As a researcher who has run the full convert pipeline for a topic
  I want all converted Markdown files under files/<topic>/ copied to my workspace
  So that my research folder always receives a clean, complete set of paper MDs

  Scenario: Copy all .md files from a topic folder to the target
    Given a topic folder "mnemonic-method" containing converted .md papers
    When collect-papers runs for topic "mnemonic-method" with a dest folder
    Then all .md files are present in the dest folder

  Scenario: Topic folder with no .md files exits cleanly with a warning
    Given a topic folder "spaced-repetition" with no .md files
    When collect-papers runs for topic "spaced-repetition" with a dest folder
    Then no files are copied and the step exits 0

  Scenario: Re-running collect-papers overwrites existing files (idempotent)
    Given a topic folder "mnemonic-method" containing converted .md papers
    And a stale copy of one .md already exists in the dest folder
    When collect-papers runs for topic "mnemonic-method" with a dest folder
    Then the dest file contains the fresh content from the topic folder

  Scenario: Non-existent topic folder exits non-zero with a clear error
    Given no topic folder named "does-not-exist" under files/
    When collect-papers runs for topic "does-not-exist" with a dest folder
    Then the step exits non-zero
    And an error message is printed to stderr
