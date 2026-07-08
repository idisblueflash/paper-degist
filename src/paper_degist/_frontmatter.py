"""US37 — provenance frontmatter carried by a per-paper sidecar.

``fetch-batch`` writes a ``<stem>.meta.json`` sidecar next to each fetched source
file; the convert steps (US3/US5) read it and stamp a YAML frontmatter block onto
the ``.md`` so a paper's ``doi``/``url``/``pdf_url``/``venue`` travel with the file
rather than only its body text. Consolidating the representation here (rule 02)
keeps both convert steps and ``fetch-batch`` on one definition of the block, the
sidecar name, and the field set.
"""

import json
from pathlib import Path
from typing import Optional

import yaml

# The frontmatter always carries these four keys in this order, so the block has
# a uniform shape across papers; a field the record lacked is emitted as ``null``.
FIELDS = ("doi", "url", "pdf_url", "venue")

# The sidecar sits next to the source file, sharing its stem (``paper.pdf`` →
# ``paper.meta.json``), so the convert step finds it from the source path alone.
SIDECAR_SUFFIX = ".meta.json"

# A frontmatter block opens on the very first line with this fence.
_FENCE = "---\n"


def render(meta: dict) -> str:
    """Render ``meta`` as a YAML frontmatter block (all four keys, null-filled).

    Only the four :data:`FIELDS` are emitted, in order; any other key in ``meta``
    is ignored and a missing one becomes ``null``. Values are serialized with
    ``yaml.safe_dump`` so a venue with a colon or a URL is quoted correctly.
    """
    ordered = {key: meta.get(key) for key in FIELDS}
    body = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"{_FENCE}{body}{_FENCE}\n"


def sidecar_path(source: Path) -> Path:
    """The sidecar path for a source file (``paper.pdf`` → ``paper.meta.json``)."""
    source = Path(source)
    return source.with_name(source.stem + SIDECAR_SUFFIX)


def write_sidecar(source: Path, meta: dict) -> Path:
    """Write ``{FIELDS}`` (null-filled) as the source's sidecar JSON; return it."""
    ordered = {key: meta.get(key) for key in FIELDS}
    target = sidecar_path(source)
    target.write_text(json.dumps(ordered) + "\n", encoding="utf-8")
    return target


def load_sidecar(source: Path) -> Optional[dict]:
    """The sidecar mapping for a source file, or ``None`` when absent/unreadable.

    A missing or corrupt sidecar is not an error — the paper simply gets no
    frontmatter (the pre-US37 behaviour), so the convert step never crashes.
    """
    target = sidecar_path(source)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    # A well-formed but non-object sidecar (a stray list/number) is not usable
    # as a field map — treat it like an absent sidecar rather than crash later.
    return data if isinstance(data, dict) else None


def has_frontmatter(text: str) -> bool:
    """Whether ``text`` already begins with a frontmatter block (idempotency)."""
    return text.startswith(_FENCE)


def apply(markdown: str, meta: Optional[dict]) -> str:
    """Prepend the frontmatter to ``markdown`` unless one is already present.

    ``meta`` is ``None`` (no sidecar) → ``markdown`` unchanged. Already stamped
    → unchanged (no double-stamp). Otherwise the rendered block is prepended.
    """
    if meta is None:
        return markdown
    if has_frontmatter(markdown):
        return markdown
    return render(meta) + markdown
