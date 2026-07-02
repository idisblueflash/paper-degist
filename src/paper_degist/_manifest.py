"""Shared manifest writer for the pipeline's quarantine path (rule 02).

Every step that faces an unhandled case appends one record to the same
``manifest.jsonl`` — the queue of cases the script does not yet know how to
handle. Consolidating the append here keeps the mechanics (create parent dirs,
open in append mode, one JSON object per line) in one place and stamps every
record with a ``stage`` discriminator, so a reader can tell a fetch-one
quarantine (``url``/``status``/``content_type``) from a convert-html one
(``path``) even though both steps write to the same file.
"""

import json
from pathlib import Path


def append(manifest_path: Path, *, stage: str, **fields: object) -> dict:
    """Append one ``{stage, **fields}`` record to ``manifest_path``; return it.

    ``stage`` names the step that quarantined the item (e.g. ``"fetch-one"``,
    ``"convert-html"``) so records stay distinguishable in the shared manifest.
    """
    record = {"stage": stage, **fields}
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record
