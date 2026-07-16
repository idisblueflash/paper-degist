"""Steps for US39 — page-number markers (features/page_number_markers.feature).

The given/when arrangement is shared with convert_pdf_steps (behave keeps one
step registry across all step files); only the marker-specific phrases live
here. The fake OCR content is "page content from pNNNN.png", so the page name
strings locate each page's content in the stitched output.
"""

from behave import given, then

from paper_degist import _frontmatter

_SIDECAR_META = {
    "doi": "10.48550/arxiv.2212.08073",
    "url": "https://doi.org/10.48550/arxiv.2212.08073",
    "pdf_url": "https://arxiv.org/pdf/2212.08073.pdf",
    "venue": None,
}


@given('a provenance sidecar next to "{name}"')
def step_sidecar_next_to(context, name):
    _frontmatter.write_sidecar(context.pdf, _SIDECAR_META)


def _saved_text(context):
    assert context.result is not None, "convert-pdf quarantined instead of saving"
    return context.result.read_text(encoding="utf-8")


@then("the saved Markdown marks page 1 before the first page's content")
def step_page_1_marked(context):
    text = _saved_text(context)
    assert text.index("<!-- page: 1 -->") < text.index("p0001"), (
        f"page 1 marker does not precede page 1 content in:\n{text}"
    )


@then("the saved Markdown marks page 2 before the second page's content")
def step_page_2_marked(context):
    text = _saved_text(context)
    assert text.index("<!-- page: 2 -->") < text.index("p0002"), (
        f"page 2 marker does not precede page 2 content in:\n{text}"
    )


@then("the frontmatter block precedes the page 1 marker")
def step_frontmatter_before_marker(context):
    text = _saved_text(context)
    assert text.index("pdf_url:") < text.index("<!-- page: 1 -->"), (
        f"frontmatter does not precede the page 1 marker in:\n{text}"
    )


@then("the failed page's placeholder is preceded by its page marker")
def step_failed_page_marked(context):
    text = _saved_text(context)
    assert text.index("<!-- page: 1 -->") < text.index("<!-- OCR FAILED: p0001.png -->"), (
        f"failed page placeholder is not preceded by its marker in:\n{text}"
    )


@then("the page after the failed one keeps its own marker")
def step_page_after_failure_marked(context):
    text = _saved_text(context)
    assert text.index("<!-- page: 2 -->") < text.index("p0002"), (
        f"the page after the failure lost its marker in:\n{text}"
    )
