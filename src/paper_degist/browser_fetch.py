"""US15 — fetch a bot-walled page through an already-running dev-mode Chrome.

US12 teaches ``fetch-one`` to *recognize* a bot-walled 403 (ResearchGate,
PubMed) — but recognizing a wall is not getting past it. Those hosts reject the
plain HTTP client precisely because it is not a browser; a real Chrome the
researcher started in dev-mode (``browser-up``, US18) is a genuine, logged-in
browser session and loads the page. This step **attaches** to that
already-running Chrome over the Chrome DevTools Protocol (CDP), navigates one
URL, waits for the DOM to settle, and saves the rendered HTML under ``files/`` —
the recovery *mechanism* that complements US9's ``resolve-oa`` DOI lane.

Classify-then-dispatch (rule 02) over one cheap signal: is a CDP endpoint
reachable? Reachable → open a tab, navigate, wait for network idle so
client-rendered pages are captured (not the raw initial shell), save the HTML
and record ``saved``. Not reachable → quarantine (a missing dev-mode browser)
and move on. Reachable but the navigation itself fails → quarantine with a
**distinct** reason, so the manifest separates "no browser" from "browser could
not load this page". Never crash, never launch or kill Chrome, never call an LLM.

Unlike ``browser-up`` (which owns Chrome's lifecycle and fails loudly), this step
has an item to carry forward, so an unreachable endpoint or a failed nav is a
manifest **quarantine**, not a raised error — mirroring ``fetch-one``'s save +
manifest contract so ``convert-html`` can consume the result.

Runnable from the command line (rule 03):

    uv run browser-fetch <url>                       # attach to :9222, save HTML
    uv run browser-fetch <url> --cdp http://localhost:9333
"""

import os
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Annotated, Callable, Iterator, Optional
from urllib.parse import urlsplit

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke

# Reuse browser-up's CDP reachability probe — the *same* classify signal, with
# its ``trust_env=False`` proxy fix — so the two steps never drift. Imported as a
# module attribute so a test (or the CLI) can monkeypatch it here too.
from paper_degist.browser_up import DEFAULT_CDP, _default_probe_cdp

# Injected collaborators (defaults are the real implementations below), so the
# dispatch is testable without a real Chrome — the browser_up / fetch_one shape.
CDPProbe = Callable[[str], bool]  # is a dev-mode Chrome answering at this CDP url?
RenderedFetcher = Callable[[str, str], str]  # (cdp_url, url) -> rendered HTML; raises on nav failure


def _target_path(url: str, files_dir: Path) -> Path:
    """Derive ``files/<basename>.html`` from the URL path basename.

    The rendered page is always HTML, so the extension is fixed — mirroring
    ``fetch_one._target_path`` but without the content-type dispatch. A basename
    that already ends ``.html``/``.htm`` is kept as-is (no double extension).
    """
    basename = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1] or "index"
    if basename.lower().endswith((".html", ".htm")):
        return Path(files_dir) / basename
    return Path(files_dir) / f"{basename}.html"


@contextmanager
def _no_proxy_for(host: str) -> Iterator[None]:
    """Bypass any ``HTTP(S)_PROXY`` for ``host`` for the duration of the block.

    The CDP endpoint is a loopback debug server, but playwright's
    ``connect_over_cdp`` respects ``HTTP_PROXY`` — so on a machine with a proxy
    set the localhost CDP connection is routed through it and 502s a perfectly
    reachable Chrome (the same trap ``browser_up._default_probe_cdp`` dodges with
    ``trust_env=False`` — surfaced by the US15 real E2E on a proxied machine).
    Adding ``host`` to ``NO_PROXY`` makes the driver hit the endpoint directly,
    without disabling the proxy for the page's own traffic. Restores the prior
    ``NO_PROXY``/``no_proxy`` on the way out.

    The two variables can each hold distinct entries, so we **union** both (plus
    ``host``) rather than picking one — dropping the other's hosts could route a
    connection through the proxy that was meant to bypass it.
    """
    keys = ("NO_PROXY", "no_proxy")
    saved = {k: os.environ.get(k) for k in keys}
    entries: list[str] = []
    for source in (os.environ.get("NO_PROXY", ""), os.environ.get("no_proxy", ""), host):
        entries.extend(part for part in source.split(",") if part)
    merged = ",".join(dict.fromkeys(entries))  # dedup, preserve order
    os.environ["NO_PROXY"] = merged
    os.environ["no_proxy"] = merged
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _teardown(page: object, context: object, *, created_context: bool) -> None:
    """Best-effort teardown of a CDP-attach session (close only what we opened).

    Closes the tab we opened, and a context **only if we created one** (never the
    researcher's reused default context). Each close is wrapped in ``suppress`` so
    a cleanup error never masks the real navigation result/error, and a context we
    created is still closed even if creating the page failed (``page`` is ``None``)
    or ``page.close()`` raises. We never call ``browser.close()`` — see
    ``_default_fetch_rendered``. (Codex review finding.)
    """
    if page is not None:
        with suppress(Exception):
            page.close()  # close only the tab we opened
    if created_context:
        with suppress(Exception):
            context.close()  # and a context only if we created it


def _default_fetch_rendered(cdp_url: str, url: str, *, timeout_ms: int = 30000) -> str:
    """Attach to the running Chrome over CDP, navigate ``url``, return its HTML.

    Connects to the *already-running* dev-mode Chrome (``connect_over_cdp`` — it
    never launches or kills a browser), opens a fresh tab in the existing logged-in
    context so the researcher's session cookies apply, navigates and waits for
    ``networkidle`` so a client-rendered page is captured (not the initial shell),
    then reads the rendered DOM. Any failure (connect refused, nav timeout, load
    error) propagates so the caller quarantines with the distinct nav-failed
    reason — this step never crashes the batch itself.

    **Teardown closes only what we opened.** We never call ``browser.close()``:
    Playwright's own docs say that for a CDP *attach* it is "similar to
    force-quitting the browser" and clears the browser's contexts — which would
    disturb the researcher's live logged-in session (spec: this step never kills
    Chrome, and the profile must carry the login forward). Instead we close just
    the tab we opened (and a context only if we had to create one), then let
    ``sync_playwright()`` exit disconnect the driver, leaving the real Chrome and
    the researcher's tabs untouched.

    ``_no_proxy_for`` wraps the whole session so the loopback CDP connection
    bypasses any ``HTTP_PROXY`` (see its docstring — a US15 E2E finding).
    """
    from playwright.sync_api import sync_playwright

    host = urlsplit(cdp_url).hostname or "localhost"
    with _no_proxy_for(host), sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        reuse_context = bool(browser.contexts)  # the researcher's existing session
        context = browser.contexts[0] if reuse_context else browser.new_context()
        page = None
        try:
            page = context.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            return page.content()
        finally:
            _teardown(page, context, created_context=not reuse_context)


def browser_fetch(
    url: str,
    *,
    cdp_url: str = DEFAULT_CDP,
    files_dir: Path = Path("files"),
    manifest_path: Path = Path("manifest.jsonl"),
    probe_cdp: Optional[CDPProbe] = None,
    fetch_rendered: Optional[RenderedFetcher] = None,
) -> Optional[Path]:
    """Fetch ``url`` through a dev-mode Chrome, save the rendered HTML, return its path.

    Classify-then-dispatch (rule 02) on one cheap signal — is the CDP endpoint
    reachable? Reachable → navigate, save the rendered HTML and record ``saved``.
    Not reachable → quarantine (a missing dev-mode browser). Reachable but the
    navigation fails → quarantine with a **distinct** nav-failed reason. Returns
    the saved (or already-present) path on success, or ``None`` when the item is
    quarantined. A pre-existing target is left untouched so re-runs are idempotent
    (AC4) — and a skip appends no record, so re-runs stay quiet.

    Each collaborator defaults to its module-level ``_default_*`` implementation,
    resolved here so a test (or the CLI) can monkeypatch the module attribute.
    """
    probe_cdp = probe_cdp or _default_probe_cdp
    fetch_rendered = fetch_rendered or _default_fetch_rendered
    files_dir = Path(files_dir)
    manifest_path = Path(manifest_path)

    target = _target_path(url, files_dir)
    if target.exists():
        return target  # idempotent skip (AC4) — never re-fetch, overwrite, or re-record

    if not probe_cdp(cdp_url):
        # No dev-mode browser to attach to (AC2). The item waits for a run with
        # Chrome up — never launch one here, never crash.
        _manifest.append(
            manifest_path,
            stage="browser-fetch",
            url=url,
            cdp_url=cdp_url,
            reason=(
                f"no dev-mode browser endpoint reachable at {cdp_url} — "
                f"bring one up with browser-up, then re-run"
            ),
        )
        return None

    try:
        html = fetch_rendered(cdp_url, url)
    except Exception as exc:  # nav timeout/error — a *distinct* reason from "no browser" (AC3)
        _manifest.append(
            manifest_path,
            stage="browser-fetch",
            url=url,
            cdp_url=cdp_url,
            reason=f"navigation failed: {exc}",
        )
        return None

    files_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    _manifest.append(
        manifest_path,
        stage="browser-fetch",
        url=url,
        cdp_url=cdp_url,
        result="saved",
        path=str(target),
    )
    return target


app = typer.Typer(
    add_completion=False,
    help="Fetch a bot-walled page through a dev-mode Chrome over CDP (US15).",
)


@app.command()
def run(
    url: Annotated[str, typer.Argument(help="the bot-walled URL to fetch through the browser")],
    cdp: Annotated[
        str,
        typer.Option(help="CDP endpoint of the already-running dev-mode Chrome"),
    ] = DEFAULT_CDP,
    files_dir: Annotated[
        Path,
        typer.Option(help="directory to save the rendered HTML into"),
    ] = Path("files"),
    manifest: Annotated[
        Path,
        typer.Option(help="manifest of saved and quarantined records"),
    ] = Path("manifest.jsonl"),
) -> None:
    """Fetch the URL through the browser; print the saved path, or a quarantine note."""
    target = browser_fetch(url, cdp_url=cdp, files_dir=files_dir, manifest_path=manifest)
    if target is None:
        # Quarantine is an expected outcome, not a crash: the item waits for a run
        # with Chrome up. Note it on stderr and exit cleanly.
        typer.echo(f"quarantined (see {manifest}): {url}", err=True)
        return
    typer.echo(str(target))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run browser-fetch`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
