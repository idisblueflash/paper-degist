"""US22 — Score one model output against an OmniDocBench gold page.

Reference-free proxies (US21) rank models by *fewest defects*; they cannot settle
*accuracy* — whether a model really reconstructs a table or the author names
faithfully. That needs a **gold reference**. OmniDocBench (CVPR 2025;
``opendatalab/OmniDocBench``, 1651 annotated PDF pages) ships gold text, tables
(LaTeX + HTML), and reading order, stratified by page attributes. This step
scores a model's output against that gold using OmniDocBench's own per-element
scheme: **normalized edit distance** for text, **TEDS** for tables — each a
deterministic comparison, never an LLM judge.

We take the **subset filtered to our use case** — ``data_source =
academic_literature``, ``layout = double_column``, ``language ∈ {english,
en_ch_mixed}`` (the verified attribute field names / values) — so the gold pages
statistically match the two-column, embedded-CJK papers this pipeline targets.

Classify-then-dispatch (rule 02): each gold page is classified by which
annotation types it carries, and one metric is dispatched per present type —
text → normalized edit distance; table → TEDS. A page **missing** a type simply
skips that metric (recorded not-applicable, not zero — a false zero would poison
the average). An output the step cannot read is **quarantined** to
``manifest.jsonl`` (``stage: "score-gold"``) and skipped — never crashed over,
never sent to an LLM.

The OmniDocBench dataset is **research-only, non-commercial** and is *not*
vendored into this repo; the operator supplies the annotation JSON and page
images from their own local download. Tests run against a small synthetic
fixture that mirrors the schema.
"""

import json
import re
from pathlib import Path
from typing import Annotated, Optional

import typer
from apted import APTED, Config
from lxml import html as lxml_html
from rapidfuzz.distance import Levenshtein

from paper_degist import _manifest
from paper_degist._cli import invoke
from paper_degist.ocr_page import _model_slug

# --- the subset filter: the pipeline's target page distribution (AC1) ---
#
# OmniDocBench's *verified* page-attribute field names and values (confirmed
# against the dataset card, 2026-07): the filter keeps only academic-literature,
# double-column pages in English or English/Chinese-mixed — the two-column,
# embedded-CJK papers this pipeline targets — and drops newspapers, receipts,
# handwriting, and single-column pages. Widening or narrowing it is a config
# change here, not a code branch (rule 02).
_SUBSET_DATA_SOURCE = "academic_literature"
_SUBSET_LAYOUT = "double_column"
_SUBSET_LANGUAGES = frozenset({"english", "en_ch_mixed"})


def matches_subset(page_attribute: dict) -> bool:
    """Whether one page's ``page_attribute`` falls in our curated gold subset.

    ``True`` only when the page is academic literature, double-column, and in
    English or English/Chinese-mixed — so the scored gold set statistically
    matches the papers this pipeline actually converts.
    """
    return (
        page_attribute.get("data_source") == _SUBSET_DATA_SOURCE
        and page_attribute.get("layout") == _SUBSET_LAYOUT
        and page_attribute.get("language") in _SUBSET_LANGUAGES
    )


def normalized_edit_distance(pred: str, gold: str) -> float:
    """Normalized Levenshtein distance between a model's text and the gold text.

    ``0.0`` means a perfect transcription; ``1.0`` means no character in common.
    Lower is better — this is OmniDocBench's text metric (a *distance*, not a
    similarity), so a faithful model scores near 0 and a hallucinating one high.
    """
    return Levenshtein.normalized_distance(pred, gold)


# --- TEDS: Tree-Edit-Distance-based Similarity for tables (AC3) ---
#
# TEDS(a, b) = 1 - TreeEditDistance(a, b) / max(|a|, |b|), where each table is
# parsed to a tree of HTML nodes and |t| is its node count (the PubTabNet /
# OmniDocBench table metric). 1.0 is a perfect table; a wrong structure or wrong
# cell contents drives it toward 0. Higher is better — a *similarity*, opposite
# in direction to the text edit distance above.

_WS_RE = re.compile(r"\s+")
_CELL_TAGS = frozenset({"td", "th"})


class _TableNode:
    """One HTML element in a parsed table tree (the unit APTED edits).

    Carries the tag, the cell span (``colspan``/``rowspan``, so a merged cell is
    structurally distinct), and the normalized cell text — the three things the
    TEDS cost model compares.
    """

    __slots__ = ("tag", "colspan", "rowspan", "content", "children")

    def __init__(self, tag: str, colspan: int, rowspan: int, content: str):
        self.tag = tag
        self.colspan = colspan
        self.rowspan = rowspan
        self.content = content
        self.children: list["_TableNode"] = []


def _int_attr(element, name: str) -> int:
    """A cell-span attribute (``colspan``/``rowspan``) as an int, default 1."""
    try:
        return int(element.get(name, "1"))
    except (TypeError, ValueError):
        return 1


def _build_tree(element) -> _TableNode:
    """Convert one lxml element (and its subtree) into a ``_TableNode`` tree.

    Cell text is whitespace-collapsed so cosmetic spacing never counts as a
    content difference; only ``td``/``th`` cells carry content (structural nodes
    like ``tr`` compare on tag alone).
    """
    tag = element.tag if isinstance(element.tag, str) else "?"
    content = ""
    if tag in _CELL_TAGS:
        content = _WS_RE.sub(" ", element.text_content()).strip()
    node = _TableNode(tag, _int_attr(element, "colspan"), _int_attr(element, "rowspan"), content)
    node.children = [_build_tree(child) for child in element if isinstance(child.tag, str)]
    return node


def _parse_table(table_html: str) -> _TableNode:
    """Parse a table HTML fragment into a ``_TableNode`` tree."""
    return _build_tree(lxml_html.fragment_fromstring(table_html, create_parent="div"))


def _node_count(node: _TableNode) -> int:
    """Total nodes in a ``_TableNode`` tree (the TEDS normalizer ``|t|``)."""
    return 1 + sum(_node_count(child) for child in node.children)


class _TedsConfig(Config):
    """APTED cost model for TEDS: structure by tag/span, cell content by string.

    Insert/delete cost 1 per node. Rename cost 1 when tags or cell spans differ;
    for two same-span cells the cost is the normalized edit distance of their
    text (in ``[0, 1]``); a non-cell tag match costs 0.
    """

    valuecls = float

    def rename(self, node1: _TableNode, node2: _TableNode) -> float:
        if node1.tag != node2.tag:
            return 1.0
        if node1.tag in _CELL_TAGS:
            if (node1.colspan, node1.rowspan) != (node2.colspan, node2.rowspan):
                return 1.0
            return normalized_edit_distance(node1.content, node2.content)
        return 0.0

    def children(self, node: _TableNode) -> list:
        return node.children


def teds(pred_html: str, gold_html: str) -> float:
    """Tree-Edit-Distance-based Similarity between a model table and the gold.

    Both tables are parsed to node trees and compared with APTED under the TEDS
    cost model; the edit distance is normalized by the larger tree's node count
    and subtracted from 1, so an identical table scores ``1.0`` and an unrelated
    one approaches ``0.0``.
    """
    pred_tree = _parse_table(pred_html)
    gold_tree = _parse_table(gold_html)
    distance = APTED(pred_tree, gold_tree, _TedsConfig()).compute_edit_distance()
    denom = max(_node_count(pred_tree), _node_count(gold_tree))
    if denom == 0:
        return 1.0
    return round(1.0 - distance / denom, 4)


# --- classify a gold page by its annotation types; dispatch one metric each ---


def _gold_text(page: dict) -> str:
    """The page's gold text, concatenated in reading order.

    Every ``layout_dets`` block carrying a ``text`` recognition field
    contributes one line, ordered by its ``order`` (reading order); blocks
    without text (tables, figures) do not. This is the reference the model's
    transcription is compared against.
    """
    blocks = [det for det in page.get("layout_dets", []) if isinstance(det.get("text"), str)]
    blocks.sort(key=lambda det: det.get("order", 0))
    return "\n".join(det["text"] for det in blocks)


def _gold_tables(page: dict) -> list[str]:
    """The page's gold table HTML annotations, in reading order.

    Each ``layout_dets`` block carrying an ``html`` field is a table; a page with
    none is text-only and skips the table metric entirely (AC4).
    """
    tables = [det for det in page.get("layout_dets", []) if isinstance(det.get("html"), str)]
    tables.sort(key=lambda det: det.get("order", 0))
    return [det["html"] for det in tables]


_MODEL_TABLE_RE = re.compile(r"<table\b.*?</table>", re.DOTALL | re.IGNORECASE)


def _model_tables(model_output: str) -> list[str]:
    """The HTML tables the model emitted in its Markdown output, in order.

    Document-parse OCR models render a table as an inline HTML ``<table>`` block;
    those are extracted here to compare against the gold via TEDS. (GFM
    pipe-table output is not yet converted — see DEVLOG.)
    """
    return _MODEL_TABLE_RE.findall(model_output)


def score_gold_page(gold_page: dict, model_output: str, *, model: str, page: str) -> dict:
    """Score one model output against one gold page; return its ``scores`` record.

    Classify-then-dispatch (rule 02): the page is classified by which annotation
    types it carries and one metric is dispatched per present type — text →
    ``normalized_edit_distance`` against the gold text; table → ``teds``. A type
    the page lacks is recorded not-applicable (``None``), never a false ``0.0``
    that would poison the model's average (AC4). The record is keyed by
    ``(model, page)`` and tagged ``gold`` so it is distinguishable from US21's
    reference-free rows in the shared ``scores.jsonl``.
    """
    gold_tables = _gold_tables(gold_page)
    # The gold *text* excludes tables (a table block carries no ``text`` field),
    # so the model's table HTML must be stripped before the text compare — the
    # table is scored separately by TEDS, and leaving it in double-counts it and
    # balloons a faithful page's edit distance (caught by the US22 real E2E).
    model_text = _MODEL_TABLE_RE.sub("", model_output)
    return {
        "model": model,
        "page": page,
        "gold": True,
        "text_edit_distance": round(normalized_edit_distance(model_text, _gold_text(gold_page)), 4),
        "teds": _score_table(model_output, gold_tables),
    }


def _score_table(model_output: str, gold_tables: list[str]) -> float | None:
    """The page's TEDS, or ``None`` when the gold page carries no table (AC4).

    A gold table with no matching model table scores a real ``0.0`` — the model
    failed to reproduce it — distinct from the not-applicable ``None`` of a
    text-only page. Only the first table is scored today; multi-table pairing is
    deferred (see DEVLOG).
    """
    if not gold_tables:
        return None
    model_tables = _model_tables(model_output)
    if not model_tables:
        return 0.0
    return teds(model_tables[0], gold_tables[0])


# --- file-level orchestrator: read a saved output, score it, append the row ---


def _append_score(scores_path: Path, record: dict) -> None:
    """Append one ``scores.jsonl`` record (one line of JSON) to ``scores_path``."""
    scores_path = Path(scores_path)
    scores_path.parent.mkdir(parents=True, exist_ok=True)
    with scores_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _quarantine(manifest_path: Path, *, page: str, model: str, reason: str) -> None:
    """Append one unhandled-case record to the manifest, so the batch finishes."""
    _manifest.append(manifest_path, stage="score-gold", page=page, model=model, reason=reason)


def score_gold(
    output_path: Path,
    gold_page: dict,
    *,
    scores_path: Path = Path("scores.jsonl"),
    manifest_path: Path = Path("manifest.jsonl"),
) -> Optional[dict]:
    """Score one saved ``out/<model>/<page>.md`` against its gold page.

    Reads the model output the same way US20 saved it — ``(model, page)`` come
    straight from the ``out/<model>/<page>.md`` path — scores it against
    ``gold_page`` and appends the row to ``scores.jsonl``. Returns the record, or
    ``None`` when the output cannot be read (quarantined to ``manifest.jsonl``
    with ``stage="score-gold"``). Never crashes, never calls an LLM (rule 02).
    """
    output_path = Path(output_path)
    model = output_path.parent.name
    page = output_path.stem

    try:
        text = output_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _quarantine(
            manifest_path,
            page=page,
            model=model,
            reason=f"unreadable output ({type(exc).__name__}): {exc}",
        )
        return None

    record = score_gold_page(gold_page, text, model=model, page=page)
    _append_score(scores_path, record)
    return record


def score_gold_batch(
    annotations_path: Path,
    model_id: str,
    *,
    out_dir: Path = Path("out"),
    scores_path: Path = Path("scores.jsonl"),
    manifest_path: Path = Path("manifest.jsonl"),
) -> int:
    """Score ``model_id`` against every in-subset page of an OmniDocBench file.

    Loads the operator-supplied annotation JSON (the research-only dataset is not
    vendored), keeps only the pages the subset filter selects (AC1), and scores
    each against the model's saved OCR output at ``out/<model>/<page-stem>.md``
    (US20's idempotent cache — a re-run re-scores from the stored output, never
    re-hitting the flaky server). A selected page whose output has not been OCR'd
    yet is quarantined (``stage="score-gold"``) rather than crashing the batch.
    Returns the count of pages scored.
    """
    annotations_path = Path(annotations_path)
    out_dir = Path(out_dir)
    model_slug = _model_slug(model_id)
    pages = json.loads(annotations_path.read_text(encoding="utf-8"))
    if not isinstance(pages, list):
        # A whole-file shape error is not a per-item quarantine (there are no
        # items) — fail with an actionable message, not a cryptic AttributeError
        # from iterating a dict's keys (rule 02 — never crash on bad input).
        raise ValueError(
            f"annotations file must be a JSON list of page objects, got {type(pages).__name__}"
        )

    scored = 0
    for gold_page in pages:
        page_info = gold_page.get("page_info", {})
        if not matches_subset(page_info.get("page_attribute", {})):
            continue
        stem = Path(str(page_info.get("image_path", ""))).stem
        output_path = out_dir / model_slug / f"{stem}.md"
        if not output_path.exists():
            _quarantine(
                manifest_path,
                page=stem,
                model=model_slug,
                reason=f"no model output at {output_path} (run ocr-page first)",
            )
            continue
        if score_gold(output_path, gold_page, scores_path=scores_path, manifest_path=manifest_path):
            scored += 1
    return scored


app = typer.Typer(
    add_completion=False,
    help="Score a model against an OmniDocBench gold subset (US22).",
)


@app.command()
def run(
    annotations: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="the OmniDocBench annotation JSON (operator-supplied; not vendored)",
        ),
    ],
    model: Annotated[
        str,
        typer.Argument(help="a registered model id, e.g. qwen/qwen3-vl-4b"),
    ],
    out_dir: Annotated[
        Path,
        typer.Option("--out-dir", help="where US20 saved the OCR output (out/<model>/)"),
    ] = Path("out"),
    scores: Annotated[
        Path,
        typer.Option("--scores", help="the scores.jsonl to append gold rows to"),
    ] = Path("scores.jsonl"),
    manifest: Annotated[
        Path,
        typer.Option(help="manifest to quarantine un-OCR'd / unreadable pages to"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Score the in-subset gold pages; print how many were scored."""
    try:
        scored = score_gold_batch(
            annotations, model, out_dir=out_dir, scores_path=scores, manifest_path=manifest
        )
    except ValueError as exc:
        # A malformed annotations file surfaces as a clean usage error (exit 2,
        # no traceback), the way Typer's standalone mode renders bad parameters.
        raise typer.BadParameter(str(exc), param_hint="ANNOTATIONS") from exc
    typer.echo(f"scored {scored} gold page(s) for {model} -> {scores}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run score-gold`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
