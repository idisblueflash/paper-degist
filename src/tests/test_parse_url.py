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


# --- [MAJOR] URLs containing parentheses are not truncated (PR thread 3509869118) ---


def test_keeps_balanced_parentheses_inside_url():
    assert parse_url("see https://example.org/paper_(v2).pdf here") == [
        "https://example.org/paper_(v2).pdf"
    ]


def test_strips_unbalanced_markdown_wrapper_paren():
    assert parse_url("[paper](https://example.com/a.pdf)") == [
        "https://example.com/a.pdf"
    ]


# --- [MAJOR] trailing-punctuation cleanup is delimiter-aware (PR thread 3509869214) ---


def test_strips_trailing_prose_punctuation_but_keeps_balanced_parens():
    assert parse_url("(ref: https://example.org/a_(b).pdf).") == [
        "https://example.org/a_(b).pdf"
    ]


def test_strips_trailing_comma_and_semicolon():
    assert parse_url("a https://example.com/x, b https://example.com/y;") == [
        "https://example.com/x",
        "https://example.com/y",
    ]


# --- [MINOR] mixed-case schemes are extracted, original text preserved (PR thread 3509869403) ---


def test_extracts_mixed_case_scheme_preserving_original_text():
    assert parse_url("HTTP://example.com and Https://example.org") == [
        "HTTP://example.com",
        "Https://example.org",
    ]


# --- [MINOR] embedded schemes are not false positives (PR thread 3509869497) ---


def test_embedded_scheme_is_not_matched():
    assert parse_url("abchttps://example.com") == []


def test_scheme_after_punctuation_is_matched():
    assert parse_url("(https://example.com)") == ["https://example.com"]


# --- [MINOR] dedup policy pinned: exact post-cleanup string, no normalization (PR thread 3509869664) ---


def test_dedup_treats_scheme_case_slash_query_and_fragment_as_distinct():
    text = "http://x HTTP://x http://x/ http://x?a=1 http://x#frag http://x"
    assert parse_url(text) == [
        "http://x",
        "HTTP://x",
        "http://x/",
        "http://x?a=1",
        "http://x#frag",
    ]
