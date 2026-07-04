Feature: US19 — render-pdf renders a PDF into one PNG per page

  As a maintainer benchmarking OCR models on paper-style PDFs
  I want to render a PDF into one deterministic PNG per page
  So that every model sees the same page bitmaps and results are reproducible

  Scenario: Render a two-page PDF to one PNG per page under pages/<stem>/
    Given a saved PDF "WordCraft.pdf" with 2 pages
    When render-pdf renders the PDF
    Then one PNG per page is saved under pages/WordCraft/
    And the render is recorded in the manifest with 2 pages

  Scenario: A non-PDF input is quarantined, not rendered
    Given a saved non-PDF file "Residual_Networks.html"
    When render-pdf renders the PDF
    Then no page images are saved for it
    And the PDF is recorded in the manifest with reason "not a PDF (no %PDF header)"
