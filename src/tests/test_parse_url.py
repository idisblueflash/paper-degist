"""Unit tests for US1 AC1 parse_url (pytest)."""

from pathlib import Path

from paper_degist.parse_url import parse_url

SAMPLE = Path(__file__).parent / "samples" / "mnemonic-method-bayesian-analysis.md"


def test_empty_text_returns_empty_list():
    assert parse_url("") == []


def test_no_urls_returns_empty_list():
    assert parse_url("just some prose with no links") == []


def test_extracts_a_bare_url():
    assert parse_url("see https://example.com/paper.pdf here") == [
        "https://example.com/paper.pdf"
    ]


def test_extracts_url_from_markdown_link_without_trailing_paren():
    assert parse_url("[paper](https://example.com/a.pdf)") == [
        "https://example.com/a.pdf"
    ]


def test_strips_trailing_sentence_punctuation():
    assert parse_url("read https://example.com/a.pdf.") == [
        "https://example.com/a.pdf"
    ]


def test_deduplicates_preserving_first_seen_order():
    text = "https://b.com https://a.com https://b.com"
    assert parse_url(text) == ["https://b.com", "https://a.com"]


def test_sample_blob_has_nine_unique_urls():
    urls = parse_url(SAMPLE.read_text(encoding="utf-8"))
    assert len(urls) == 9
    assert len(urls) == len(set(urls))
    assert "https://arxiv.org/pdf/2602.00762" in urls
