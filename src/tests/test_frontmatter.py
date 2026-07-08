"""Tests for _frontmatter (US37) — driven one test at a time (rule 05)."""

import json
from pathlib import Path

import yaml

from paper_degist import _frontmatter


# ---------------------------------------------------------------------------
# render — the YAML block carries all four keys, null when missing
# ---------------------------------------------------------------------------

def _parse_block(block: str) -> dict:
    """Parse a rendered frontmatter block back into its mapping."""
    inner = block.split("---\n", 2)[1]
    return yaml.safe_load(inner)


def test_render_carries_all_four_keys():
    block = _frontmatter.render({"doi": "10.1/x", "url": "u", "pdf_url": "p", "venue": "v"})
    assert set(_parse_block(block)) == {"doi", "url", "pdf_url", "venue"}


def test_render_missing_field_is_null():
    block = _frontmatter.render({"url": "https://arxiv.org/abs/2602.00762"})
    assert _parse_block(block)["doi"] is None


# ---------------------------------------------------------------------------
# sidecar — write/load roundtrip, absent is not an error
# ---------------------------------------------------------------------------

def test_sidecar_path_shares_source_stem(tmp_path):
    assert _frontmatter.sidecar_path(tmp_path / "paper.pdf").name == "paper.meta.json"


def test_write_then_load_sidecar_roundtrips(tmp_path):
    source = tmp_path / "attention.html"
    _frontmatter.write_sidecar(source, {"doi": "10.5555/attn", "url": "u", "pdf_url": "p", "venue": "NeurIPS"})
    assert _frontmatter.load_sidecar(source)["venue"] == "NeurIPS"


def test_load_absent_sidecar_is_none(tmp_path):
    assert _frontmatter.load_sidecar(tmp_path / "no-such.pdf") is None


def test_load_non_dict_sidecar_is_none(tmp_path):
    source = tmp_path / "corrupt.pdf"
    _frontmatter.sidecar_path(source).write_text("[1, 2, 3]", encoding="utf-8")
    assert _frontmatter.load_sidecar(source) is None


# ---------------------------------------------------------------------------
# apply — no meta / fresh stamp / already stamped
# ---------------------------------------------------------------------------

def test_apply_without_meta_leaves_body_unchanged():
    assert _frontmatter.apply("# Body\n", None) == "# Body\n"


def test_apply_prepends_block_ahead_of_body():
    out = _frontmatter.apply("# Body\n", {"url": "u"})
    assert out.startswith("---\n") and out.endswith("# Body\n")


def test_apply_is_idempotent_when_already_stamped():
    stamped = _frontmatter.render({"url": "u"}) + "# Body\n"
    assert _frontmatter.apply(stamped, {"url": "different"}) == stamped
