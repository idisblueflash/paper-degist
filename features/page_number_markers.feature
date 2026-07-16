Feature: Page-number markers in converted PDF Markdown (US39)

  As a researcher feeding converted papers to an LLM wiki
  I want each page of the stitched Markdown to carry its page number
  So that an AI module can cite and locate content by page in the original PDF

  Background:
    Given a registered OCR model "deepseek-ocr-2"

  Scenario: Every page's content is preceded by its page marker
    Given a saved PDF file "files/Constitutional_AI.pdf"
    When I run convert-pdf on "files/Constitutional_AI.pdf"
    Then the saved Markdown marks page 1 before the first page's content
    And the saved Markdown marks page 2 before the second page's content

  Scenario: Frontmatter stays first — the page 1 marker follows it
    Given a saved PDF file "files/Chain_of_Thought_Prompting.pdf"
    And a provenance sidecar next to "files/Chain_of_Thought_Prompting.pdf"
    When I run convert-pdf on "files/Chain_of_Thought_Prompting.pdf"
    Then the frontmatter block precedes the page 1 marker

  Scenario: A failed-OCR page keeps its marker so numbering stays aligned
    Given a saved PDF file "files/Lost_in_the_Middle.pdf"
    And OCR will fail for a page of "files/Lost_in_the_Middle.pdf"
    When I run convert-pdf on "files/Lost_in_the_Middle.pdf"
    Then the failed page's placeholder is preceded by its page marker
    And the page after the failed one keeps its own marker
