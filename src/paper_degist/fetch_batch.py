"""US37 — fetch a candidate batch and capture each paper's provenance.

The convert stage stamps a YAML frontmatter block (doi/url/pdf_url/venue) onto
each ``.md`` from a ``<stem>.meta.json`` sidecar. Only the discover candidate
record (US25) still holds that provenance by fetch time — ``fetch_one`` saves the
file by URL basename and discards the URL. ``fetch-batch`` closes that gap: it
reads a candidates JSONL, drives ``fetch_one`` over each record's URL, and writes
the sidecar next to the file ``fetch_one`` returned — so the sidecar stem always
matches the source stem, with no re-derivation.

Classify-then-dispatch (rule 02): a record with a URL is fetched and its sidecar
written; a URL that ``fetch_one`` quarantines (a bot wall, an HTTP error) simply
gets no sidecar and the batch moves on; a malformed record (bad JSON, or no URL)
is quarantined to ``manifest.jsonl`` with ``stage: fetch-batch`` — the batch never
crashes and never calls an LLM.

Runnable from the command line (rule 03):

    uv run fetch-batch candidates.jsonl --files-dir files/mnemonic-method
"""

import json
from pathlib import Path
from typing import Annotated, Optional

import typer

from paper_degist import _frontmatter, _manifest
from paper_degist._cli import invoke
from paper_degist.fetch_one import Fetcher, _default_fetch, fetch_one


def _quarantine(manifest_path: Path, *, reason: str, line: str) -> None:
    """Append one unhandled-case record to the manifest, so the batch finishes."""
    _manifest.append(manifest_path, stage="fetch-batch", record=line, reason=reason)


def fetch_batch(
    candidates_path: Path,
    *,
    files_dir: Path = Path("files"),
    manifest_path: Path = Path("manifest.jsonl"),
    fetch: Fetcher = _default_fetch,
) -> list[Path]:
    """Fetch every candidate URL under ``files_dir`` and write its provenance sidecar.

    Returns the saved source paths (one per successfully fetched record). A record
    with no URL, or a malformed JSON line, is quarantined and skipped; a URL that
    ``fetch_one`` quarantines yields no sidecar and no entry in the returned list.
    """
    candidates_path = Path(candidates_path)
    files_dir = Path(files_dir)
    manifest_path = Path(manifest_path)

    saved: list[Path] = []
    for line in candidates_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            _quarantine(manifest_path, reason=f"malformed JSON line: {exc}", line=line)
            continue

        url = record.get("url") if isinstance(record, dict) else None
        if not (isinstance(url, str) and url.strip()):
            # No url, or a non-string url (a list/number) that would crash the
            # fetch/path handling — quarantine as malformed rather than crash.
            _quarantine(manifest_path, reason="candidate record has no usable url", line=line)
            continue

        source = fetch_one(url, files_dir=files_dir, manifest_path=manifest_path, fetch=fetch)
        if source is None:
            # fetch_one already wrote its own quarantine record — no sidecar,
            # move on to the next candidate.
            continue

        _frontmatter.write_sidecar(source, record)
        saved.append(source)
    return saved


app = typer.Typer(
    add_completion=False,
    help="Fetch a candidate batch and write each paper's provenance sidecar (US37).",
)


@app.command()
def run(
    candidates: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="the candidates JSONL (one discover/rank record per line)",
        ),
    ],
    files_dir: Annotated[
        Path,
        typer.Option(help="directory to save fetched files under (files/<topic>/)"),
    ] = Path("files"),
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of quarantined records/URLs"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Fetch the batch; print each saved path, or a quarantine note on stderr."""
    saved = fetch_batch(candidates, files_dir=files_dir, manifest_path=manifest)
    for path in saved:
        typer.echo(str(path))
    if not saved:
        typer.echo(f"no files saved (see {manifest})", err=True)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run fetch-batch`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
