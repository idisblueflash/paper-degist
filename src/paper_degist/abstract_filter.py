"""US26 — filter discover candidates by abstract similarity to a topic.

``discover`` (US25) casts a wide net and over-returns; this step narrows it into
a short, ranked shortlist for ``fetch-one`` — in **two passes, and no LLM** (the
criteria-aware judge on the ambiguous middle is a separate, later story):

1. **Deterministic** (pure, offline, free — runs first): dedup candidates by
   normalized DOI (reusing US14's ``normalize_doi``) and drop any candidate
   ``discover`` flagged ``abstract_present: false``. Each drop is a ``filtered``
   manifest record — thrown out *before* a single embedding call is spent.
2. **Embedding similarity** (offline, deterministic): embed the ``--topic`` once
   as a query and each surviving abstract as a document via ``embed-text``
   (US24), take the **cosine similarity**, and cut everything below a threshold
   measured against a real sample (see the US26 "Threshold calibration"). A
   below-threshold candidate is dropped with a ``filtered`` record carrying its
   similarity; a survivor is kept with its ``similarity`` attached.

The two manifest events are distinguished by an ``event`` field: a ``filtered``
record is a *deliberate* drop (no-abstract, dedup-doi, below-threshold); a
``quarantined`` record is an *unhandled failure* (``embed-text`` could not obtain
a vector — the server is down). Resilience (rule 02): one abstract's embed
quarantine takes out only that candidate; the rest of the batch still completes.
No LLM is ever called.

Runnable from the command line (rule 03):

    uv run abstract-filter candidates.jsonl --topic "contrastive learning for speech"
    uv run discover "…" --source arxiv | uv run abstract-filter --topic "…"
"""

import json
import math
import sys
from pathlib import Path
from typing import Annotated, Callable, Optional

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke
from paper_degist.dedup_inputs import normalize_doi
from paper_degist.embed_text import (
    DEFAULT_ATTEMPTS,
    DEFAULT_ENDPOINT,
    DEFAULT_GAP,
    embed_text,
)

# The cosine cutoff, measured against a real sample (rule 06 phase 2 — see the
# US26 "Threshold calibration": every off-topic candidate scored ≤ 0.6337, the
# on-topic body ≥ 0.72; 0.65 sits above the off-topic cluster with margin). A
# recall-biased shortlister — the finer intent judgment is the deferred LLM pass.
DEFAULT_THRESHOLD = 0.65

# The default embedding model (US24 registry id). A different model is a --model
# option, not a branch — one registry entry supplies its (query, doc) prefixes.
DEFAULT_MODEL = "nomic-embed-text-v1.5"

# An Embedder maps (text, role) -> vector, or None when the embedding call
# quarantines (server down). Injected in tests so the two passes stay offline;
# the default composes embed-text's curl-to-LM-Studio transport.
Embedder = Callable[[str, str], Optional[list[float]]]


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two vectors; 0.0 when either has no direction.

    A zero vector has no direction, so guard the division rather than crash
    (rule 02: never crash) — a degenerate embedding scores 0 (below any positive
    threshold), which drops it as off-topic. Two other degenerate inputs fold to
    0.0 for the same reason: **mismatched dimensions** (not comparable — return 0
    rather than let ``zip`` truncate to a false near-match) and a **non-finite**
    result (a ``NaN``/``inf`` component would otherwise emit ``similarity: NaN``,
    which is not valid JSON for the downstream shortlist).
    """
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    result = dot / (norm_a * norm_b)
    return result if math.isfinite(result) else 0.0


def candidate_doi_key(record: dict) -> Optional[str]:
    """The normalized DOI dedup key for a candidate, or ``None``.

    Prefers the candidate's explicit ``doi`` field (OpenAlex/S2 carry one),
    falling back to a DOI embedded in the landing ``url`` (a ``doi.org`` link or
    a publisher path). Reuses US14's ``normalize_doi`` (lowercase, prefix-strip)
    so ``https://doi.org/10.X`` and ``10.x`` fold to one key. ``None`` when no
    DOI is extractable (an arXiv url) — that candidate cannot be deduped offline.
    """
    doi = record.get("doi")
    if doi:
        return normalize_doi(doi)
    return normalize_doi(record.get("url") or "")


def _has_abstract(record: dict) -> bool:
    """Whether a candidate carries a usable abstract for the similarity filter.

    Drops on ``discover``'s ``abstract_present: false`` flag (AC1), and also
    guards a record whose flag *lies* — ``abstract_present: true`` with an empty
    or null ``abstract`` — by requiring the abstract text to be non-empty, so a
    malformed record is dropped as no-abstract rather than crashing pass 2 on
    ``embed(None)`` (rule 02: never crash).
    """
    if record.get("abstract_present") is False:
        return False
    abstract = record.get("abstract")
    # Require an actual non-empty *string*: a malformed source could carry
    # abstract as a list/number, which would pass a truthiness check but then
    # crash pass 2 on embed(non-str) — drop it as no-abstract instead.
    return isinstance(abstract, str) and bool(abstract.strip())


def _filtered(manifest_path: Path, *, url: str, reason: str, **fields: object) -> None:
    """Record a *deliberate* drop (no-abstract / dedup-doi / below-threshold)."""
    _manifest.append(
        manifest_path, stage="abstract-filter", event="filtered", url=url, reason=reason, **fields
    )


def _quarantine(manifest_path: Path, *, url: str, reason: str, **fields: object) -> None:
    """Record an *unhandled failure* — a malformed input line or an embed-text
    vector that could not be obtained. ``**fields`` carries the case-specific
    detail (e.g. the raw offending ``line``) so the manifest preserves the
    unknown case for a human, not just the parser's message."""
    _manifest.append(
        manifest_path, stage="abstract-filter", event="quarantined", url=url, reason=reason, **fields
    )


def load_candidates(
    text: str,
    *,
    manifest_path: Path = Path("manifest.jsonl"),
    stage: str = "abstract-filter",
) -> list[dict]:
    """Parse candidate JSONL into records, quarantining any line that is not a
    JSON **object**.

    The input is ``discover`` output, but a pipe can be interrupted mid-write or
    hand-edited, leaving a truncated/garbage line. Rule 02 says never crash: a
    line that does not parse, or parses to a non-object (a bare scalar/array that
    ``candidate.get(...)`` would ``AttributeError`` on), is skipped to the
    manifest with a distinct reason, and the well-formed candidates still run.
    Every candidate-JSONL consumer shares this loader; ``stage`` names the
    calling step on the quarantine rows (``rank-cited`` reuses it, US32).
    """
    manifest_path = Path(manifest_path)
    candidates: list[dict] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            _manifest.append(
                manifest_path,
                stage=stage,
                event="quarantined",
                url="",
                reason=f"unparseable candidate line {lineno}: {exc}",
                line=line[:500],
            )
            continue
        if not isinstance(record, dict):
            _manifest.append(
                manifest_path,
                stage=stage,
                event="quarantined",
                url="",
                reason=f"non-object candidate line {lineno}: got {type(record).__name__}",
                line=line[:500],
            )
            continue
        candidates.append(record)
    return candidates


def abstract_filter(
    candidates: list[dict],
    topic: str,
    *,
    embed: Embedder,
    threshold: float = DEFAULT_THRESHOLD,
    manifest_path: Path = Path("manifest.jsonl"),
) -> list[dict]:
    """Narrow ``candidates`` to a ranked shortlist about ``topic`` (US26).

    Returns the kept candidate records (each with a ``similarity`` field),
    ordered by **descending** similarity — a drop-in to ``fetch-one``. Every
    dropped candidate leaves an auditable manifest record; nothing is dropped
    silently, nothing crashes, no LLM is called.
    """
    manifest_path = Path(manifest_path)

    # Pass 1 — deterministic (offline, free), before any embedding call is spent.
    survivors: list[dict] = []
    seen: dict[str, str] = {}
    for candidate in candidates:
        url = candidate.get("url", "")
        if not _has_abstract(candidate):
            _filtered(manifest_path, url=url, reason="no-abstract")
            continue
        key = candidate_doi_key(candidate)
        if key is not None:
            if key in seen:
                _filtered(manifest_path, url=url, reason="dedup-doi", doi=key, duplicate_of=seen[key])
                continue
            seen[key] = url
        survivors.append(candidate)

    # Pass 2 — embedding similarity. Embed the topic once as the query; if even
    # that fails, the server is down for the whole run — record it and emit an
    # empty shortlist rather than crash.
    query_vec = embed(topic, "query")
    if query_vec is None:
        _quarantine(
            manifest_path,
            url="",
            reason=f"embed-unavailable: could not embed the topic query {topic!r}",
        )
        return []

    kept: list[dict] = []
    for candidate in survivors:
        url = candidate.get("url", "")
        vec = embed(candidate["abstract"], "document")
        if vec is None:
            # AC5: only this candidate is quarantined; the batch continues.
            _quarantine(
                manifest_path,
                url=url,
                reason="embed-unavailable: could not embed the candidate abstract",
            )
            continue
        similarity = round(cosine(query_vec, vec), 6)
        if similarity < threshold:
            _filtered(manifest_path, url=url, reason="below-threshold", similarity=similarity)
            continue
        record = dict(candidate)
        record["similarity"] = similarity
        kept.append(record)

    kept.sort(key=lambda r: r["similarity"], reverse=True)
    return kept


def make_embedder(
    model_id: str = DEFAULT_MODEL,
    *,
    out_dir: Path = Path("out"),
    manifest_path: Path = Path("manifest.jsonl"),
    endpoint: str = DEFAULT_ENDPOINT,
    attempts: int = DEFAULT_ATTEMPTS,
    gap: float = DEFAULT_GAP,
) -> Embedder:
    """The real embedder: compose ``embed-text`` (US24) and read back its vector.

    ``embed-text`` owns the flaky-transport discipline (curl, sequential, retry
    with a recovery gap, content-addressed idempotent cache) and returns the
    saved vector's path — or ``None`` on quarantine, which this surfaces as a
    ``None`` vector so ``abstract_filter`` records the per-candidate failure.
    """

    def embed(text: str, role: str) -> Optional[list[float]]:
        path = embed_text(
            text,
            model_id,
            role=role,
            out_dir=out_dir,
            manifest_path=manifest_path,
            endpoint=endpoint,
            attempts=attempts,
            gap=gap,
        )
        if path is None:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["embedding"]
        except (json.JSONDecodeError, KeyError, OSError):
            # embed_text saves atomically, so this is rare — but a corrupt or
            # hand-edited cache file must not crash the batch (rule 02): surface
            # it as None so abstract_filter quarantines this candidate.
            return None

    return embed


app = typer.Typer(
    add_completion=False,
    help="Filter candidates by abstract similarity to a topic (US26).",
)


@app.command()
def run(
    candidates_file: Annotated[
        Optional[Path],
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="candidate JSONL (discover output); reads stdin when omitted",
        ),
    ] = None,
    topic: Annotated[
        str,
        typer.Option("--topic", help="the topic query to rank abstracts against"),
    ] = ...,
    threshold: Annotated[
        float,
        typer.Option(help="cosine cutoff; below it a candidate is dropped"),
    ] = DEFAULT_THRESHOLD,
    model: Annotated[
        str,
        typer.Option(help="a registered embedding model id (embed-text registry)"),
    ] = DEFAULT_MODEL,
    out_dir: Annotated[
        Path,
        typer.Option("--out-dir", help="directory embed-text caches vectors under"),
    ] = Path("out"),
    endpoint: Annotated[
        str,
        typer.Option(help="embeddings endpoint of the local model server"),
    ] = DEFAULT_ENDPOINT,
    attempts: Annotated[int, typer.Option(help="max POST attempts before quarantine")] = DEFAULT_ATTEMPTS,
    gap: Annotated[float, typer.Option(help="recovery gap (seconds) between retries")] = DEFAULT_GAP,
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of filtered/quarantined candidates and embed records"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Print the kept candidates as JSONL, ranked by descending similarity."""
    text = candidates_file.read_text(encoding="utf-8") if candidates_file else sys.stdin.read()
    candidates = load_candidates(text, manifest_path=manifest)
    embed = make_embedder(
        model,
        out_dir=out_dir,
        manifest_path=manifest,
        endpoint=endpoint,
        attempts=attempts,
        gap=gap,
    )
    kept = abstract_filter(
        candidates, topic, embed=embed, threshold=threshold, manifest_path=manifest
    )
    for record in kept:
        typer.echo(json.dumps(record, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run abstract-filter`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
