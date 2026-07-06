"""Unit tests for the shared OpenAlex client bits (pytest).

One logical assertion per test. ``pdf_url_from_work`` reads the open-access PDF
out of an OpenAlex Work; these tests pin the location precedence against the
**current** API shape, where every location lives under ``locations`` (each with
an ``is_oa`` flag) — the legacy ``oa_locations`` array is honored too for records
that still carry it.
"""

from paper_degist._openalex import pdf_url_from_work


def test_best_oa_location_pdf_is_preferred():
    work = {"best_oa_location": {"pdf_url": "https://oa.example/best.pdf"}}
    assert pdf_url_from_work(work) == "https://oa.example/best.pdf"


def test_falls_back_to_an_oa_entry_in_locations():
    # Real case (arXiv 1412.6980): best_oa_location has no pdf_url, but an OA
    # entry under `locations` points at the arXiv PDF. The current API exposes
    # no `oa_locations`, so the fallback must read `locations`.
    work = {
        "best_oa_location": {"pdf_url": None, "landing_page_url": "https://openreview.net/x"},
        "locations": [
            {"is_oa": False, "pdf_url": None},
            {"is_oa": True, "pdf_url": "https://arxiv.org/pdf/1412.6980"},
        ],
    }
    assert pdf_url_from_work(work) == "https://arxiv.org/pdf/1412.6980"


def test_a_non_oa_location_pdf_is_never_returned():
    # A paywalled publisher PDF (is_oa False) is not a free copy — skip it.
    work = {"locations": [{"is_oa": False, "pdf_url": "https://publisher/paywalled.pdf"}]}
    assert pdf_url_from_work(work) is None


def test_legacy_oa_locations_array_is_still_honored():
    # Records that still carry the older `oa_locations` array keep working.
    work = {"oa_locations": [{"pdf_url": "https://repo.example/legacy.pdf"}]}
    assert pdf_url_from_work(work) == "https://repo.example/legacy.pdf"


def test_no_oa_pdf_anywhere_is_none():
    work = {"best_oa_location": {"pdf_url": None}, "locations": [{"is_oa": True, "pdf_url": None}]}
    assert pdf_url_from_work(work) is None
