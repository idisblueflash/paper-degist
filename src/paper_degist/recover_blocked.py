"""US17 — route bot-walled records into the browser lane (recover-blocked).

US12 teaches ``fetch-one`` to *tag* a bot-walled 403 with a ``blocked_by`` host;
US15/16 can fetch those URLs through a dev-mode Chrome. This step is the **join**
US12 deferred ("a future orchestrator could read a ``blocked_by`` record and
dispatch it"): it reads the append-only ``manifest.jsonl``, selects the records
that carry a ``blocked_by`` host and are not yet recovered, and hands their URLs
to ``browser-fetch``'s warm-batch path (US16, one Chrome).

It is a **second recovery lane, parallel to ``resolve-oa``** (US9's DOI lane):
this one recovers by *rendering the walled page itself*. recover-blocked is
deterministic, offline routing — it filters the manifest and delegates the
actual fetching. It holds no browser logic and makes no judgement of its own, so
there is no LLM in the loop (rule 02).

Classify-then-dispatch over cheap fields per record: is it a ``fetch-one`` record
carrying a ``blocked_by`` host (the routing key, fetch-one-only by US12's
contract), and has that URL already been recovered in a later ``browser-fetch``
record? **No fetch-one ``blocked_by``** → skip (a generic quarantine, or another
stage's record — not this lane). **Present, not yet recovered** → add its URL to
the retry set. **Present but already recovered** → skip (idempotent across runs).
The retry set is dispatched
wholesale to ``browser_fetch_batch`` (US16), which owns the connect / navigate /
quarantine decisions — recover-blocked adds none of its own and writes no
manifest record itself (the new recovery record is browser-fetch's ``saved``
one). Reading ``blocked_by`` as the routing key is the encoded knowledge: a new
walled host becomes routable the moment US12's table tags it, with no change here.
"""

import json
from pathlib import Path
from typing import Annotated, Callable, Iterable, Optional

import typer

from paper_degist._cli import invoke
from paper_degist.browser_fetch import DEFAULT_CDP, browser_fetch_batch

# The batch fetcher recover-blocked delegates to (default: the real US16
# warm-batch path). Injected so the routing is testable without a real Chrome.
BatchFetcher = Callable[..., list[Path]]


def _read_records(manifest_path: Path) -> list[dict]:
    """Read the append-only manifest into a list of records; tolerate its absence.

    A missing manifest means nothing has been fetched yet — return no records
    (never crash). Blank lines are skipped; a malformed line is skipped too, and a
    valid-JSON but non-object line (a bare array/string/number) is skipped as well
    — so no stray hand-appended line ever reaches the classifier's ``.get`` and
    aborts the routing (rule 02: never crash).
    """
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return []
    records: list[dict] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):  # a record is a JSON object; skip arrays/scalars
            records.append(record)
    return records


def select_retry_urls(records: Iterable[dict]) -> list[str]:
    """The ``blocked_by`` URLs not yet recovered, in first-seen order.

    Classify each record on cheap fields (rule 02): a ``fetch-one`` record with a
    truthy ``blocked_by`` host marks a wall to route into the browser lane; a
    ``browser-fetch`` ``saved`` record marks a URL already recovered in a later run
    (AC5 idempotency). A wall URL with no later recovery is the retry set;
    everything else — a generic quarantine (no ``blocked_by``, AC1), a
    ``blocked_by`` tag on some *other* stage's record (blocked_by is fetch-one-only
    by US12's contract), or an already-recovered wall — is skipped. First-seen
    order so the dispatched batch is deterministic. A record whose ``url`` is not a
    string is ignored, so a stray hand-appended value never reaches the browser
    lane (never crash).
    """
    blocked: list[str] = []  # blocked_by URLs, unique, first-seen order
    seen: set[str] = set()
    recovered: set[str] = set()  # URLs a later browser-fetch already saved
    for record in records:
        url = record.get("url")
        if not isinstance(url, str) or not url:
            continue
        stage = record.get("stage")
        if stage == "fetch-one" and record.get("blocked_by") and url not in seen:
            seen.add(url)
            blocked.append(url)
        if stage == "browser-fetch" and record.get("result") == "saved":
            recovered.add(url)
    return [url for url in blocked if url not in recovered]


def recover_blocked(
    manifest_path: Path = Path("manifest.jsonl"),
    *,
    cdp_url: str = DEFAULT_CDP,
    files_dir: Path = Path("files"),
    fetch_batch: Optional[BatchFetcher] = None,
) -> list[Path]:
    """Read the manifest, select the not-yet-recovered walled URLs, dispatch them.

    Filters the append-only manifest (``select_retry_urls``) and hands the whole
    retry set to ``browser_fetch_batch`` (US16) in **one** call, so the list
    rides a single warm Chrome (AC2) — recover-blocked never drives Chrome or
    writes a manifest record itself; the new recovery record is browser-fetch's
    own ``saved`` one (AC3). An empty retry set dispatches nothing (no browser is
    opened for an empty list). Returns the saved paths browser-fetch reports, in
    first-seen order, ready to pipe into ``convert-html``. When no dev-mode Chrome
    is reachable, browser-fetch quarantines each URL with its own missing-endpoint
    reason (US15 AC2) and this step still returns cleanly (AC4) — never crashes.

    ``fetch_batch`` defaults to the real ``browser_fetch_batch`` and is injected
    so the routing is testable without a real Chrome (the browser_fetch shape).
    """
    fetch_batch = fetch_batch or browser_fetch_batch
    manifest_path = Path(manifest_path)

    urls = select_retry_urls(_read_records(manifest_path))
    if not urls:
        return []  # nothing walled and unrecovered — never open a browser for nothing
    return fetch_batch(
        urls, cdp_url=cdp_url, files_dir=Path(files_dir), manifest_path=manifest_path
    )


app = typer.Typer(
    add_completion=False,
    help="Retry the manifest's bot-walled URLs through a dev-mode Chrome (US17).",
)


@app.command()
def run(
    manifest: Annotated[
        Path,
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="the manifest to scan for blocked_by records (default manifest.jsonl)",
        ),
    ] = Path("manifest.jsonl"),
    cdp: Annotated[
        str,
        typer.Option(help="CDP endpoint of the already-running dev-mode Chrome"),
    ] = DEFAULT_CDP,
    files_dir: Annotated[
        Path,
        typer.Option(help="directory browser-fetch saves the rendered HTML into"),
    ] = Path("files"),
) -> None:
    """Route the manifest's not-yet-recovered blocked_by URLs through browser-fetch.

    Selects the ``blocked_by`` records that no later run has recovered and hands
    their URLs to browser-fetch's warm-batch path (one Chrome, US16). Prints each
    recovered path to stdout in first-seen order — a drop-in to pipe into
    ``convert-html``. Anything not recovered (no dev-mode Chrome, or a nav that
    failed) is quarantined by browser-fetch in the same ``manifest`` with its own
    reason; recover-blocked never drives Chrome or crashes. When there is nothing
    to recover, stdout stays empty and a note lands on stderr.
    """
    paths = recover_blocked(manifest, cdp_url=cdp, files_dir=files_dir)
    for path in paths:
        typer.echo(str(path))
    # Keep stdout paths-only for piping; report the outcome on stderr so a run
    # that recovered nothing (nothing walled, or no browser) is never silent —
    # the manifest carries the per-URL reasons.
    if paths:
        typer.echo(f"recovered {len(paths)} blocked page(s)", err=True)
    else:
        typer.echo(
            f"no blocked pages recovered — nothing walled to retry, or no dev-mode "
            f"Chrome reachable (see {manifest})",
            err=True,
        )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run recover-blocked`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
