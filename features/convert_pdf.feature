Feature: Convert PDF to Markdown via OCR (US3)

  As a researcher
  I want to convert a PDF paper into a Markdown file
  So that I can process it with an LLM later

  Background:
    Given a registered OCR model "deepseek-ocr-2"

  Scenario: Happy path — PDF is rendered, OCR'd, and stitched to Markdown
    Given a saved PDF file "files/Attention_Is_All_You_Need.pdf"
    When I run convert-pdf on "files/Attention_Is_All_You_Need.pdf"
    Then "files/Attention_Is_All_You_Need.md" is saved with stitched page content
    And the pages appear in order in the saved Markdown

  Scenario: Idempotent re-run — existing Markdown is not overwritten
    Given a saved PDF file "files/Deep_Residual_Learning.pdf"
    And "files/Deep_Residual_Learning.md" already exists
    When I run convert-pdf on "files/Deep_Residual_Learning.pdf"
    Then "files/Deep_Residual_Learning.md" is returned unchanged

  Scenario: OCR failure — failed page gets a placeholder, Markdown is still saved
    Given a saved PDF file "files/GPT4_Technical_Report.pdf"
    And OCR will fail for a page of "files/GPT4_Technical_Report.pdf"
    When I run convert-pdf on "files/GPT4_Technical_Report.pdf"
    Then "files/GPT4_Technical_Report.md" is saved with a placeholder for the failed page
