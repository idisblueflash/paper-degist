"""US21 — Score one saved OCR output on reference-free defect metrics.

The investigation report ranked models mostly **without a gold reference**: it
counted *defects* with cheap deterministic proxies, and those proxies caught the
real killers — ``unlimited-ocr`` degenerating into a 95 % duplicate-line loop,
``deepseek-ocr@8bit`` leaking hyphen-space artifacts (``"low- quality"``) and
dropping inline citation lists, a 4-bit model ignoring the image entirely. None
of those needs a reference to detect: they are computable from the output text
plus the per-call fields US20 already recorded in ``manifest.jsonl``
(``finish_reason`` / ``latency`` / ``completion_tokens``).

This step is the **everyday, offline tier** of the OCR bench: point it at any
model's saved Markdown for any page and get one ``scores.jsonl`` row, no
labeling. Each metric is one deterministic function = one scored **dimension** =
one branch (rule 02, rule 05). The gold-referenced accuracy tier (edit distance /
TEDS against OmniDocBench) is US22; aggregating across models is US23.

Classify-then-dispatch (rule 02): the panel of scorers each own one dimension of
a readable output; an output the step cannot read is **quarantined** to
``manifest.jsonl`` (``stage: "score-ocr"``) and skipped — never crashed over,
never sent to an LLM — so a batch still finishes.

Runnable from the command line (rule 03):

    uv run score-ocr out/qwen_qwen3-vl-4b/p02.md
    uv run score-ocr out/deepseek-ocr@8bit/p02.md --scores scores.jsonl
"""

import json
import re
from pathlib import Path
from typing import Annotated, Optional

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke
from paper_degist.ocr_page import _model_slug

# --- the reference-free scorers (each owns one dimension; rule 02) ---

# A markdown horizontal rule (`---`, `***`, `___`): legitimately repeated
# boilerplate that must NOT inflate the duplicate-line count (report false
# positive). Excluding it is encoded knowledge, not a per-run judgement.
_RULE_RE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")

# Sentence boundary — an end punctuation (`.?!`) followed by whitespace. Used
# only as the unlined-output fallback for `dup_pct`: a model that emits the whole
# page on one line (no newlines) has one substantive "line", so a line-based
# duplicate count is blind to an intra-line repetition loop (deepseek-ocr did
# this on a gold page — a real loop that scored 0). Segmenting that lone line
# into sentences restores the signal without touching line-structured output.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+")

# Abbreviations whose trailing `.` is NOT a sentence end. Splitting on them would
# turn repeated `See Fig.` fragments into false duplicate units and inflate
# `dup_pct` on a *distinct* single-line output (Codex review). Compared lowercase
# with the trailing dot stripped, so `Fig.`, `al.` (from `et al.`), `e.g.` match.
_ABBREVIATIONS = frozenset(
    {"fig", "eq", "no", "vol", "pp", "al", "e.g", "i.e", "cf", "vs",
     "dr", "mr", "ms", "prof", "ref", "sec", "ch", "etc", "approx"}
)

# A `word- word` dehyphenation artifact: a letter/digit, a hyphen, then a space
# before the next word (the `"low- quality"` / `"L1- Chinese"` leak that
# separated @8bit from qwen). The word chars are matched with zero-width
# look-around so adjacent breaks (`"a- b- c"`) each count — the following word
# char is not consumed by one match and hidden from the next (Codex review).
_HYPHEN_ARTIFACT_RE = re.compile(r"(?<=\w)-\s+(?=\w)")

# An inline numeric citation group: `[51]` or `[51,53,75,82]`. A model that
# *drops* citation lists scores lower on this dimension than one that keeps them.
_CITATION_RE = re.compile(r"\[\d+(?:\s*,\s*\d+)*\]")

# Any CJK ideograph or IPA-extensions codepoint — the "the model actually read
# the page's language" signal (a page that is Chinese/phonetic in the image but
# all-ASCII in the output ignored or hallucinated it). CJK Ext-A (U+3400–4DBF),
# CJK Unified (U+4E00–9FFF), IPA Extensions (U+0250–02AF).
_CJK_RE = re.compile(r"[㐀-䶿一-鿿ɐ-ʯ]")


def _substantive_lines(text: str) -> list[str]:
    """The lines that count toward duplication: non-blank, non-horizontal-rule.

    Blank lines and markdown rules (``---``) are legitimate repeated boilerplate;
    counting them as duplicates inflates ``dup_pct`` on clean output, so they are
    excluded before the ratio is taken (the report's known false positive).
    """
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or _RULE_RE.match(line):
            continue
        lines.append(stripped)
    return lines


def _dup_units(text: str) -> list[str]:
    """The units duplication is measured over: substantive lines, or — when the
    output is unlined (one substantive line for the whole page) — its sentences.

    Classify-then-dispatch (rule 02): line-structured output keeps the exact
    line-based behavior (no recalibration of existing scores); only the degenerate
    single-line blob falls back to sentence segmentation, so a repetition loop a
    model emitted without newlines is still caught instead of scoring 0.
    """
    lines = _substantive_lines(text)
    if len(lines) > 1:
        return lines
    return _sentences(text)


def _sentences(text: str) -> list[str]:
    """Split one line into sentences, not breaking on abbreviation dots.

    A naive split on every `.?!` breaks `See Fig. 1` into `See Fig.` + `1 …`, so
    repeated `See Fig.` fragments read as duplicates and inflate `dup_pct`. When a
    fragment ends in a known abbreviation, it is re-joined to the next — the dot
    was not a sentence end.
    """
    out: list[str] = []
    for part in _SENTENCE_SPLIT_RE.split(text.strip()):
        part = part.strip()
        if not part:
            continue
        if out and out[-1].split()[-1].rstrip(".!?").lower() in _ABBREVIATIONS:
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def dup_pct(text: str) -> float:
    """Percentage of substantive units that repeat an earlier one.

    A degenerated repetition loop (``unlimited-ocr``'s 95 % loop) scores high; a
    clean page with distinct lines scores ~0. Boilerplate rules/blank lines are
    excluded (see ``_substantive_lines``) so legitimate repetition does not
    inflate the score. Units are substantive lines, falling back to sentences for
    unlined output (see ``_dup_units``) so a one-line blob's loop is not missed.
    """
    units = _dup_units(text)
    if not units:
        return 0.0
    return round(100 * (len(units) - len(set(units))) / len(units), 1)


def hyphen_artifacts(text: str) -> int:
    """Count of ``word- word`` dehyphenation artifacts in the output."""
    return len(_HYPHEN_ARTIFACT_RE.findall(text))


def citation_groups(text: str) -> int:
    """Count of inline numeric citation groups (``[51,53,75,82]``) in the output."""
    return len(_CITATION_RE.findall(text))


def cjk_present(text: str) -> bool:
    """Whether any CJK ideograph or IPA-extensions codepoint survived the OCR."""
    return _CJK_RE.search(text) is not None


# --- join the per-call fields US20 recorded in the manifest ---

_MANIFEST_FIELDS = ("finish_reason", "latency", "completion_tokens")


def _manifest_fields(manifest_path: Path, model_slug: str, page_stem: str) -> dict:
    """The ``finish_reason``/``latency``/``completion_tokens`` US20 recorded.

    Joins on the saved output's own coordinates: the ``out/<model_slug>/<page>``
    path maps back to the ocr-page *success* record whose ``model`` slugifies to
    ``model_slug`` and whose ``page`` stem is ``page_stem``. Quarantine records
    (no ``finish_reason``) are skipped; the last match wins so a re-OCR's newer
    row is preferred. Missing manifest / no match → all fields ``None``.
    """
    fields = {key: None for key in _MANIFEST_FIELDS}
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return fields
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        # A valid-JSON line that is not an object (`[]`, `null`, a bare string —
        # hand-edited or mis-shaped) is not a manifest record: skip it, never
        # let `.get()` raise (Codex review: hold the never-crash invariant).
        if not isinstance(record, dict):
            continue
        if record.get("stage") != "ocr-page" or "finish_reason" not in record:
            continue
        if _model_slug(str(record.get("model", ""))) != model_slug:
            continue
        if Path(str(record.get("page", ""))).stem != page_stem:
            continue
        fields = {key: record.get(key) for key in _MANIFEST_FIELDS}
    return fields


def _append_score(scores_path: Path, record: dict) -> None:
    """Append one ``scores.jsonl`` record (one line of JSON) to ``scores_path``."""
    scores_path = Path(scores_path)
    scores_path.parent.mkdir(parents=True, exist_ok=True)
    with scores_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _quarantine(manifest_path: Path, *, page: str, model: str, reason: str) -> None:
    """Append one unhandled-case record to the manifest, so the batch finishes."""
    _manifest.append(manifest_path, stage="score-ocr", page=page, model=model, reason=reason)


def score_ocr(
    output_path: Path,
    *,
    scores_path: Path = Path("scores.jsonl"),
    manifest_path: Path = Path("manifest.jsonl"),
) -> Optional[dict]:
    """Score one saved ``out/<model>/<page>.md``; append its ``scores.jsonl`` row.

    Returns the scored record on success, or ``None`` when the output cannot be
    read (quarantined to ``manifest.jsonl`` with ``stage="score-ocr"``). The
    ``(model, page)`` key is read straight from the path — ``out/<model>/<page>.md``
    → ``model`` = the slug dir, ``page`` = the stem — and the reference-free
    dimensions are joined with the manifest-sourced per-call fields. Never
    crashes, never calls an LLM (rule 02).
    """
    output_path = Path(output_path)
    scores_path = Path(scores_path)
    manifest_path = Path(manifest_path)

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

    record = {
        "model": model,
        "page": page,
        "dup_pct": dup_pct(text),
        "hyphen_artifacts": hyphen_artifacts(text),
        "citation_groups": citation_groups(text),
        "cjk_present": cjk_present(text),
        **_manifest_fields(manifest_path, model, page),
    }
    _append_score(scores_path, record)
    return record


app = typer.Typer(
    add_completion=False,
    help="Score one saved OCR output on reference-free defect metrics (US21).",
)


@app.command()
def run(
    output: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="a saved OCR Markdown output, e.g. out/qwen_qwen3-vl-4b/p02.md",
        ),
    ],
    scores: Annotated[
        Path,
        typer.Option("--scores", help="the scores.jsonl to append the row to"),
    ] = Path("scores.jsonl"),
    manifest: Annotated[
        Path,
        typer.Option(help="manifest to join US20 per-call fields from / quarantine to"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Score the output; print the (model, page) it scored, or a quarantine note."""
    record = score_ocr(output, scores_path=scores, manifest_path=manifest)
    if record is None:
        typer.echo(f"quarantined (see {manifest}): {output}", err=True)
        return
    typer.echo(f"{record['model']}/{record['page']} -> {scores}")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run score-ocr`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
