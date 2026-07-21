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

US16 lifts this to a **batch**: ``browser_fetch_batch`` reads a *list* of URLs,
connects to the CDP endpoint **once**, fetches each on its own tab against that
one warm session, and detaches at the end **without closing Chrome** — so the
whole list rides a single authenticated session (and, via Chrome's persistent
profile, the next run reuses it too). Each URL keeps US15's per-URL save,
idempotency, and quarantine behaviour; one URL's failure never aborts the run.

Runnable from the command line (rule 03):

    uv run browser-fetch urls.txt                    # one URL per line, one warm session
    cat urls.txt | uv run browser-fetch              # or from stdin
    uv run browser-fetch urls.txt --cdp http://localhost:9333
"""

import os
import re
import sys
from contextlib import AbstractContextManager, contextmanager, suppress
from pathlib import Path
from typing import Annotated, Callable, Iterable, Iterator, Optional
from urllib.parse import urlsplit

import typer

from paper_degist import _manifest
from paper_degist._cli import invoke

# Reuse fetch_one's slug tokenizer (US13) — the *same* lowercase-alphanumeric
# token comparison, so the wall's title/slug check never drifts from the
# filename↔title check. Imported as a module attribute for the shared shape.
from paper_degist.fetch_one import _slug_tokens

# Reuse browser-up's CDP reachability probe — the *same* classify signal, with
# its ``trust_env=False`` proxy fix — so the two steps never drift. Imported as a
# module attribute so a test (or the CLI) can monkeypatch it here too.
from paper_degist.browser_up import DEFAULT_CDP, _default_probe_cdp

# Injected collaborators (defaults are the real implementations below), so the
# dispatch is testable without a real Chrome — the browser_up / fetch_one shape.
CDPProbe = Callable[[str], bool]  # is a dev-mode Chrome answering at this CDP url?
RenderedFetcher = Callable[[str, str], str]  # (cdp_url, url) -> rendered HTML; raises on nav failure
TabFetcher = Callable[[str], str]  # (url) -> rendered HTML on a fresh tab; raises on nav failure
# A batch session: connect once, yield a per-URL TabFetcher, detach on exit (US16).
SessionOpener = Callable[[str], "AbstractContextManager[TabFetcher]"]


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


# Known wall signatures (US35): markup a bot-wall / challenge page carries that a
# real paper page does not. Deliberately specific — a bare "cloudflare" would
# false-positive on the huge fraction of legitimate paper hosts served *via*
# Cloudflare's CDN. A newly-seen signature is one entry here (rule 02: the
# manifest of wall captures is the queue of cases), never a new code path.
#
# Split by *where* it is safe to match (Codex review): the structural challenge
# tokens live in a script src / challenge blob a real paper page never carries,
# so they are matched anywhere in the HTML; the interstitial *phrases* ("just a
# moment…") are ordinary English that could appear in a paper's body prose, so
# they are matched only against the rendered ``<title>``.
# NB: NOT "challenge-platform". That /cdn-cgi/challenge-platform/ path also serves
# Cloudflare's generic JS-Detections telemetry script (.../scripts/jsd/main.js),
# which Cloudflare injects into *ordinary cleared pages*, not only interstitials.
# A live US40 QA run proved it false-positives on a fully-loaded ScienceDirect
# article — keeping the --interactive loop polling forever after the human cleared
# the wall. The markers below are challenge-widget-specific (absent once cleared);
# the genuine interstitial is still caught by them plus the title markers.
_WALL_BODY_MARKERS = (
    "cf-chl-",  # Cloudflare challenge widget id prefix
    "cf_chl_opt",  # Cloudflare challenge options blob (window._cf_chl_opt)
)
_WALL_TITLE_MARKERS = (
    "just a moment",  # the classic CF interstitial title
    "attention required!",  # CF block page title ("Attention Required! | Cloudflare")
    "checking your browser",  # CF anti-bot interstitial title
)

# Stop-words dropped from a URL's slug before the title comparison: a shared
# *content* word (not "and"/"the") is what signals the rendered title reflects
# the requested paper. Pure-digit tokens (a publication id like ``220320021``)
# are dropped too, so an id-only slug (arXiv's ``1706.03762``) is unjudgeable and
# never flagged — the safe direction (a missed wall, never a false quarantine).
_SLUG_STOPWORDS = frozenset(
    {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"}
)

# Generic path / repository furniture that identifies no paper. A basename built
# only from these (``viewcontent.cgi``, ``download/pdf``) carries no title token
# to compare, so the title check must abstain rather than treat "viewcontent" as
# a word the paper's title should echo (Codex review — false-positive on
# CGI/repository basenames). Dropped alongside digits and stop-words.
_GENERIC_SLUG_TOKENS = frozenset(
    {
        "abs", "article", "cgi", "content", "doi", "download", "file", "fulltext",
        "full", "get", "htm", "html", "index", "paper", "pdf", "view", "viewcontent",
    }
)


# US40: the lazy-loaded body container of a JavaScript-heavy publisher (a
# ScienceDirect / Elsevier SPA). The body renders *after* a scroll nudge, so the
# container first holds a ``"Loading…"`` placeholder and only later fills. A new
# host's body selector is a one-line addition here (rule 02: the manifest of
# stubbed captures is the queue of cases), never a new code path.
_BODY_SELECTORS = ("#body", "section.Body", ".Body", ".article-text")

# Sample-measured readiness threshold (US40 PoC): the unloaded body reads **1**
# word (``"Loading…"``) and the fully-loaded body **10 312**, so 800 cleanly
# separates a stub from a real body. Pinned by ``sd-fulltext-lazyload.html`` in
# ``src/tests/samples/``.
READY_WORDS = 800

# Stable markers of a known lazy-load publisher (ScienceDirect / Elsevier). Present
# even in the *unrendered* SPA shell — before any article container exists — so a
# capture that carries one but has no filled body is "still loading", not "an
# ordinary page with nothing to wait for". Surfaced by the US40 live QA run, which
# saved an empty ScienceDirect shell (title "ScienceDirect", 0 body words) because
# the gate abstained on "no container". A new host is one entry here (rule 02).
_LAZYLOAD_PUBLISHER_MARKERS = (
    "sciencedirectassets",  # the els-cdn static-asset host, in every SD page's <head>
    "tdmrep-policy",  # the Elsevier TDM-policy <meta>, present in the bare shell
)


def _is_lazyload_publisher(html: str) -> bool:
    """Does ``html`` carry a known lazy-load publisher marker (ScienceDirect)?

    Used to disambiguate "no lazy-load container" (US40): on a recognized publisher
    an absent/empty body means *still loading* (keep polling / quarantine), whereas
    on any other host it means *an ordinary page* the gate abstains on (US15 saves).
    """
    lowered = html.lower()
    return any(marker in lowered for marker in _LAZYLOAD_PUBLISHER_MARKERS)


def _body_word_count(html: str) -> int:
    """Real word count of the lazy-load body container, or ``-1`` if there is none.

    Reads the first element matching ``_BODY_SELECTORS`` and counts the words of
    its rendered text. Three outcomes drive the readiness gate (US40):

    - **no container** (``-1``) — the page has no known lazy-load body, so the gate
      *abstains*: an ordinary paper page (US15/US35) is saved exactly as before.
    - **placeholder** (``0``) — the container is present but still shows the
      ``"Loading…"`` stub (or is empty), so the body has not loaded yet.
    - **real count** (``N``) — the body has filled; compare against ``READY_WORDS``.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    el = soup.select_one(", ".join(_BODY_SELECTORS))
    if el is None:
        return -1
    text = el.get_text(separator=" ", strip=True)
    if not text or text.lower().startswith("loading"):
        return 0  # the lazy-load placeholder is still showing
    return len(text.split())


def _readiness_reason(html: str) -> Optional[str]:
    """A quarantine reason if the lazy-load body has not filled, else ``None`` (US40).

    The content-readiness gate (rule 02): between "the DOM settled" and "save",
    classify whether the publisher's lazy-loaded body actually loaded.

    - **filled** (``≥ READY_WORDS``) — pass (``None``).
    - **stub / below threshold** — a **distinct** reason so the caller quarantines
      the ``"Loading…"`` header-only stub instead of saving it (never a partial
      capture that convert-html would turn into a header-only fragment).
    - **no container** — depends on the host: on a recognized lazy-load publisher
      (``_is_lazyload_publisher``) an absent body is an *unrendered shell*, so it is
      **not ready** (the live QA run saved an empty ScienceDirect shell this way);
      on any other host the gate **abstains** (``None``), so an ordinary page
      (US15/US35) with no lazy-load body still saves exactly as before.
    """
    words = _body_word_count(html)
    if words >= READY_WORDS:
        return None
    if words >= 0:
        return (
            f"body not loaded: lazy-load container holds {words} word(s), below the "
            f"{READY_WORDS}-word readiness threshold (a 'Loading…' stub, not the full body)"
        )
    # words == -1: no recognized lazy-load container.
    if _is_lazyload_publisher(html):
        return (
            "body not loaded: recognized lazy-load publisher page rendered no article "
            "body yet (an unrendered SPA shell, not the full text)"
        )
    return None  # ordinary page (US15/US35) — abstain and save


def _rendered_title(html: str) -> Optional[str]:
    """The text of the rendered HTML's ``<title>``, or ``None`` if it has none.

    Reads the title from an in-memory HTML *string* (the check runs before the
    save, so there is no file yet) — the string-input twin of ``fetch_one``'s
    path-based ``_html_title``.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    if soup.title is None:
        return None
    title = soup.title.get_text().strip()
    return title or None


def _is_doi_url(url: str) -> bool:
    """Is ``url`` a DOI (its path carries a ``10.NNNN`` registrant prefix)?

    A DOI URL (``doi.org/10.1016/j.jbi.2018.12.005``, or a publisher ``/doi/…``
    permalink) has a path *segment* matching ``10.<digits>`` — the DOI registrant
    prefix — and its remaining segment is a journal-abbreviation + numeric id
    (``j.jbi.2018.12.005``), **not** the paper's title words. So a DOI slug is
    unjudgeable for the title-mismatch heuristic, exactly like an id-only slug.
    """
    segments = urlsplit(url).path.split("/")
    return any(re.fullmatch(r"10\.\d{4,}", seg) for seg in segments)


def _url_content_tokens(url: str) -> frozenset[str]:
    """Content tokens of the URL's paper slug — digits and stop-words removed.

    The requested paper's identity lives in the path basename
    (``220320021_Spaced_Repetition_and_Long-Term_Retention``); the numeric
    publication id and stop-words are noise, so the remaining tokens
    (``spaced``, ``repetition``, ``long``, ``term``, ``retention``) are what a
    genuine rendered ``<title>`` should echo. Empty ⇒ the slug carries no
    judgeable content (an id-only slug, or a DOI whose slug is a journal
    abbreviation — US40), so the title check abstains — the safe direction is a
    missed wall, never a false quarantine of a real capture.
    """
    if _is_doi_url(url):
        return frozenset()  # a DOI slug is a journal-abbrev + id, not title words
    basename = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    tokens = _slug_tokens(basename)
    return frozenset(
        t
        for t in tokens
        if not t.isdigit()
        and t not in _SLUG_STOPWORDS
        and t not in _GENERIC_SLUG_TOKENS
    )


def _wall_reason(url: str, html: str) -> Optional[str]:
    """Classify a rendered page: a wall reason if it is not the paper, else ``None``.

    Two cheap, deterministic signals (US35): a **known wall marker** in the body
    (a Cloudflare challenge/interstitial), or a rendered ``<title>`` that **shares
    no content token** with the requested URL's paper slug (the page is *some*
    paper, but not the one we asked for). Either ⇒ a distinct "looks like a wall,
    not the paper" reason so the caller quarantines **before** saving; neither ⇒
    ``None`` (save it). No LLM, no judgement beyond these markers.
    """
    lowered = html.lower()
    for marker in _WALL_BODY_MARKERS:
        if marker in lowered:
            return f"looks like a wall, not the paper: bot-wall marker {marker!r}"

    title = _rendered_title(html)
    if title is not None:
        lowered_title = title.lower()
        for marker in _WALL_TITLE_MARKERS:
            if marker in lowered_title:
                return f"looks like a wall, not the paper: interstitial title {marker!r}"

    url_tokens = _url_content_tokens(url)
    if url_tokens and title is not None and not (url_tokens & _slug_tokens(title)):
        # A rendered title that echoes *no* content word of the requested slug is
        # some other page (a wall's own title, an unrelated paper), not the paper
        # we asked for. Abstain when the slug has no content tokens (id-only) or
        # the page has no <title> — the safe direction is a missed wall, never a
        # false quarantine of a real capture (AC3).
        return (
            f"looks like a wall, not the paper: rendered title {title!r} "
            f"does not reflect the requested URL"
        )
    return None


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


# US40 pacing constants. The settle signal a heavy publisher SPA actually reaches
# is ``domcontentloaded`` (``networkidle`` never fires — blocker #1). After it, the
# lazy-loaded body still needs a scroll nudge and a bounded poll to fill:
#  - **unattended** waits only long enough for the lazy body to fill once the DOM
#    settled (it never waits on a *human* — a wall quarantines at once, so the
#    batch never blocks, US16 AC5);
#  - **interactive** waits long enough for the operator to clear the wall by hand,
#    then auto-resumes (US40 AC3).
# A bounded settle after ``domcontentloaded`` before the first readiness probe:
# it lets the DOI→publisher redirect chain land and early client-side JS run, so a
# page with no lazy-load container (US15) is not captured as an under-rendered shell
# the way ``networkidle`` used to guard against — AC1's "domcontentloaded + a
# bounded settle" (the PoC measured ~2 s). Injected ``sleep`` makes it free in tests.
_SETTLE_S = 2.0
_POLL_S = 3.0
_UNATTENDED_MAX_WAIT_S = 30
_INTERACTIVE_MAX_WAIT_S = 240


def _scroll_nudge(page: object) -> None:
    """Scroll to the bottom and back to trigger a lazy-loaded body (US40 blocker #3).

    Best-effort: a failed ``evaluate`` (the page navigated mid-scroll, the context
    is momentarily destroyed) never aborts the poll — the next probe simply retries.
    """
    with suppress(Exception):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.evaluate("window.scrollTo(0, 0)")


def _await_ready_body(
    page: object,
    url: str,
    *,
    interactive: bool,
    notify: Callable[[str], None],
    sleep: Callable[[float], None],
    poll_s: float,
    max_wait_s: float,
) -> str:
    """Drive an already-navigated ``page`` to a ready capture; return its HTML (US40).

    Each poll reads ``page.content()`` and classifies on cheap deterministic signals
    (rule 02): a **wall** (``_wall_reason``) and whether the **body loaded**
    (``_readiness_reason`` — the *same* gate the caller applies before the save, so
    the loop and the dispatch never disagree on what "ready" means). Dispatch:

    - **ready** (no wall, body loaded/absent) → return the HTML to save.
    - **wall**, *interactive* → notify the operator **once** on the first sighting
      and keep polling until they clear it by hand (never solve it in-script).
    - **wall**, *unattended* → return the wall HTML immediately so the caller
      quarantines it — never wait on a human, so the batch never blocks (AC4).
    - **body not yet loaded** → scroll-nudge the lazy-loader and poll again.

    On exceeding ``max_wait_s`` it returns the last HTML it has (a stub or an
    uncleared wall); the caller's ``_wall_reason`` / ``_readiness_reason`` then
    quarantines it with the right distinct reason. A **transient** ``page.content()``
    error (Playwright's "execution context was destroyed" while a redirect is in
    flight, or while the operator navigates to clear the wall) is treated as
    still-loading and polled through — only a *persistent* one that outlasts the
    bound propagates, so the caller quarantines it as a navigation failure rather
    than the loop returning an empty capture. ``sleep``/``notify`` are injected so
    the loop is exercised instantly and silently in tests. Never calls an LLM.
    """
    waited = 0.0
    notified = False
    while True:
        try:
            html = page.content()
        except Exception:
            # A redirect in flight (or the operator navigating to clear the wall)
            # momentarily destroys the execution context; treat it as still-loading
            # and keep polling. Only re-raise once the bound is exhausted, so a page
            # that never yields content is quarantined as a nav failure, never saved
            # as an empty capture (PoC's navigation-resilient pattern).
            if waited >= max_wait_s:
                raise
            sleep(poll_s)
            waited += poll_s
            continue
        wall = _wall_reason(url, html)
        if wall is None and _readiness_reason(html) is None:
            return html  # ready: no wall and the body loaded (or an ordinary page)
        if wall is not None:
            if not interactive:
                return html  # unattended: never wait on a human — quarantine now
            if not notified:
                notify(
                    f">>> ACTION NEEDED: a bot-wall is showing for {url}\n"
                    f">>> Clear it by hand in the Chrome window; polling every "
                    f"{poll_s:g}s and will auto-resume."
                )
                notified = True
        else:
            _scroll_nudge(page)  # no wall — nudge the lazy-loaded body to fill
        if waited >= max_wait_s:
            return html  # bound exceeded — hand the stub/wall back for quarantine
        sleep(poll_s)
        waited += poll_s


def _fetch_on_new_tab(
    context: object,
    url: str,
    *,
    timeout_ms: int,
    interactive: bool = False,
    notify: Optional[Callable[[str], None]] = None,
    sleep: Optional[Callable[[float], None]] = None,
) -> str:
    """Open a fresh tab on ``context``, navigate ``url``, return its ready HTML.

    Waits on ``domcontentloaded`` — the settle signal a heavy publisher SPA
    actually reaches (``networkidle`` never fires — US40 blocker #1) — then hands
    the live page to ``_await_ready_body`` to scroll-nudge the lazy-loaded body and
    poll until it fills (and, in ``interactive`` mode, until the operator clears a
    wall). Closes **only the tab it opened** on the way out (US16 AC2), via
    ``_teardown(page, context, created_context=False)``; the ``context`` is left to
    the caller (``_cdp_context``), so a warm session can open the next URL on the
    same connection. Any navigation failure (nav timeout, load error) propagates so
    the caller quarantines that one URL — so one URL's failure never aborts a batch.
    """
    import time

    notify = notify or (lambda msg: print(msg, file=sys.stderr, flush=True))
    sleep = sleep or time.sleep
    max_wait_s = _INTERACTIVE_MAX_WAIT_S if interactive else _UNATTENDED_MAX_WAIT_S
    page = None
    try:
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        sleep(_SETTLE_S)  # bounded settle before the first probe (AC1) — see _SETTLE_S
        return _await_ready_body(
            page,
            url,
            interactive=interactive,
            notify=notify,
            sleep=sleep,
            poll_s=_POLL_S,
            max_wait_s=max_wait_s,
        )
    finally:
        _teardown(page, context, created_context=False)  # close the tab, keep the context


@contextmanager
def _cdp_context(cdp_url: str) -> Iterator[object]:
    """Connect to the already-running Chrome over CDP **once**; yield a context.

    Connects to the *already-running* dev-mode Chrome (``connect_over_cdp`` — it
    never launches or kills a browser) and selects the researcher's existing
    logged-in context (or creates one if the browser has none) so session cookies
    apply. On exit it **detaches without closing Chrome** (US16 AC3): it closes a
    context only if we created it and **never** calls ``browser.close()`` —
    Playwright's own docs say that for a CDP *attach* it is "similar to
    force-quitting the browser" and would clear the researcher's live contexts.
    Exiting ``sync_playwright()`` merely disconnects the driver, leaving the real
    Chrome and the researcher's tabs untouched, so the same warm browser serves
    the next run. ``_no_proxy_for`` wraps the session so the loopback CDP
    connection bypasses any ``HTTP_PROXY`` (see its docstring — a US15 E2E finding).
    """
    from playwright.sync_api import sync_playwright

    host = urlsplit(cdp_url).hostname or "localhost"
    with _no_proxy_for(host), sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        reuse_context = bool(browser.contexts)  # the researcher's existing session
        context = browser.contexts[0] if reuse_context else browser.new_context()
        try:
            yield context
        finally:
            # Detach: close a context only if we created it — never the browser.
            _teardown(None, context, created_context=not reuse_context)


def _default_fetch_rendered(
    cdp_url: str, url: str, *, timeout_ms: int = 30000, interactive: bool = False
) -> str:
    """Attach over CDP, navigate ``url`` on a fresh tab, return its ready HTML.

    The single-URL path (US15). Built on the same primitives the batch session
    reuses — ``_cdp_context`` (connect-once + detach-not-close) and
    ``_fetch_on_new_tab`` (tab-per-URL, domcontentloaded + readiness poll). When
    ``interactive`` it lets the operator clear a wall by hand and auto-resumes
    (US40 AC3); otherwise a wall or an unfilled body is handed back for quarantine.
    Any failure (connect refused, nav timeout, load error) propagates so the caller
    quarantines with the distinct nav-failed reason; this step never crashes.
    """
    with _cdp_context(cdp_url) as context:
        return _fetch_on_new_tab(context, url, timeout_ms=timeout_ms, interactive=interactive)


@contextmanager
def _default_open_session(
    cdp_url: str, *, timeout_ms: int = 30000, interactive: bool = False
) -> Iterator[TabFetcher]:
    """Open **one** warm CDP connection and yield a per-URL tab fetcher (US16).

    The batch primitive: connect once (``_cdp_context``) and hand back a
    ``fetch_tab(url) -> html`` that opens and closes a *tab* per URL against that
    single connection (``_fetch_on_new_tab``) — so every URL in the batch rides
    the same warm, authenticated session, each captured through US40's
    domcontentloaded + readiness poll (``interactive`` threaded through). On block
    exit ``_cdp_context`` detaches without closing Chrome, leaving the warm browser
    for the next run.
    """
    with _cdp_context(cdp_url) as context:
        yield lambda url: _fetch_on_new_tab(
            context, url, timeout_ms=timeout_ms, interactive=interactive
        )


def _quarantine_no_endpoint(manifest_path: Path, url: str, cdp_url: str) -> None:
    """Record the missing-dev-mode-browser quarantine for ``url`` (AC2).

    Shared by the single fetch (US15) and the batch (US16): when the CDP endpoint
    is unreachable the item cannot be fetched now, so it waits — with a reason
    **distinct** from a navigation failure — for a run with Chrome up. Never
    launch one here, never crash.
    """
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


def _dispatch_url(
    url: str,
    fetch_tab: TabFetcher,
    *,
    cdp_url: str,
    files_dir: Path,
    manifest_path: Path,
) -> Optional[Path]:
    """Fetch one URL via ``fetch_tab``, save it, or quarantine — return its path or None.

    The per-URL classify shared by the single fetch (US15) and the batch (US16),
    so both behave identically per URL. An already-saved target is skipped
    (idempotent, appends no record); ``fetch_tab(url)`` raising quarantines that
    one URL with the **distinct** nav-failed reason (so one failure never aborts
    a batch); a filesystem write failure quarantines with a distinct ``save
    failed`` reason (never mislabelled as a browser/session error); success saves
    the rendered HTML and records ``saved``. No exception from a per-URL fetch or
    save escapes — only a session open/teardown failure reaches the batch guard.
    """
    target = _target_path(url, files_dir)
    if target.exists():
        return target  # idempotent skip (AC4) — never re-fetch, overwrite, or re-record

    try:
        html = fetch_tab(url)
    except Exception as exc:  # nav timeout/error — a *distinct* reason from "no browser" (AC3)
        _manifest.append(
            manifest_path,
            stage="browser-fetch",
            url=url,
            cdp_url=cdp_url,
            reason=f"navigation failed: {exc}",
        )
        return None

    wall = _wall_reason(url, html)
    if wall is not None:
        # The render succeeded but returned a wall (login/consent/Cloudflare), not
        # the paper (US35). Quarantine with a **distinct** reason **before** the
        # save, so the wall never becomes the sticky idempotent artifact (AC4) —
        # a later logged-in run can recapture the same URL. Never crash.
        _manifest.append(
            manifest_path,
            stage="browser-fetch",
            url=url,
            cdp_url=cdp_url,
            reason=wall,
        )
        return None

    unready = _readiness_reason(html)
    if unready is not None:
        # The render succeeded and is not a wall, but the publisher's lazy-loaded
        # body never filled — the container still holds a ``"Loading…"`` stub (US40
        # blocker #3). Quarantine with a **distinct** reason **before** the save, so
        # a header-only fragment never becomes the sticky idempotent artifact (AC4)
        # nor reaches convert-html; a later scroll-nudged run can capture the full
        # body. The live capture loop scroll-nudges and polls to *avoid* this; this
        # gate is the final guard when even that did not fill the body in time (AC4,
        # unattended). Never crash, never call an LLM.
        _manifest.append(
            manifest_path,
            stage="browser-fetch",
            url=url,
            cdp_url=cdp_url,
            reason=unready,
        )
        return None

    try:
        files_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
    except Exception as exc:  # a filesystem write failure is this URL's own, not the browser's
        # Quarantine with a **distinct** reason so a data-integrity problem
        # (unwritable dir, files_dir is a file, disk full) is not masked as a
        # navigation or a browser-session failure by the batch handler (Codex
        # review). Keeping it inside _dispatch_url means only true session
        # open/teardown errors ever reach browser_fetch_batch's guard.
        _manifest.append(
            manifest_path,
            stage="browser-fetch",
            url=url,
            cdp_url=cdp_url,
            reason=f"save failed: {exc}",
        )
        return None

    _manifest.append(
        manifest_path,
        stage="browser-fetch",
        url=url,
        cdp_url=cdp_url,
        result="saved",
        path=str(target),
    )
    return target


def browser_fetch(
    url: str,
    *,
    cdp_url: str = DEFAULT_CDP,
    files_dir: Path = Path("files"),
    manifest_path: Path = Path("manifest.jsonl"),
    interactive: bool = False,
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
    # Bind ``interactive`` into the *default* fetcher only; an injected
    # ``fetch_rendered`` keeps its ``(cdp_url, url) -> html`` shape (US40).
    if fetch_rendered is None:
        fetch_rendered = lambda cdp, one_url: _default_fetch_rendered(
            cdp, one_url, interactive=interactive
        )
    files_dir = Path(files_dir)
    manifest_path = Path(manifest_path)

    target = _target_path(url, files_dir)
    if target.exists():
        return target  # idempotent skip (AC4) — never re-fetch, overwrite, or re-record

    if not probe_cdp(cdp_url):
        _quarantine_no_endpoint(manifest_path, url, cdp_url)  # no dev-mode browser (AC2)
        return None

    # One tab on a fresh single-URL connection; the batch swaps in a warm session.
    return _dispatch_url(
        url,
        lambda one_url: fetch_rendered(cdp_url, one_url),
        cdp_url=cdp_url,
        files_dir=files_dir,
        manifest_path=manifest_path,
    )


def browser_fetch_batch(
    urls: Iterable[str],
    *,
    cdp_url: str = DEFAULT_CDP,
    files_dir: Path = Path("files"),
    manifest_path: Path = Path("manifest.jsonl"),
    interactive: bool = False,
    probe_cdp: Optional[CDPProbe] = None,
    open_session: Optional[SessionOpener] = None,
) -> list[Path]:
    """Fetch a **list** of URLs over **one** warm CDP connection (US16).

    The classify-then-dispatch from US15 lifts to the batch boundary: probe the
    CDP endpoint **once**. Unreachable → every URL that is not already saved
    quarantines with the missing-endpoint reason and the run exits cleanly (AC2
    at batch scope). Reachable → open a single warm session (``open_session``,
    connect-once) and dispatch each URL to its own tab on that one connection
    (AC1), reusing US15's per-URL classify (idempotent skip / save / nav-failed
    quarantine) via ``_dispatch_url`` — so one URL's failure (a nav timeout, or
    Chrome lost mid-batch) quarantines just that URL and the loop carries on
    (AC4). On block exit the session detaches without closing Chrome (AC3).

    Returns the saved (and already-present) paths in **first-seen order** (AC5),
    ready to pipe into ``convert-html`` — a drop-in over a list. Each collaborator
    defaults to its module-level ``_default_*`` implementation so a test (or the
    CLI) can monkeypatch it.
    """
    probe_cdp = probe_cdp or _default_probe_cdp
    # Bind ``interactive`` into the *default* session opener only; an injected
    # ``open_session`` keeps its ``(cdp_url) -> ctx-mgr[TabFetcher]`` shape (US40).
    if open_session is None:
        open_session = lambda cdp: _default_open_session(cdp, interactive=interactive)
    files_dir = Path(files_dir)
    manifest_path = Path(manifest_path)
    urls = list(urls)  # materialize once: iterate twice below, and slice on failure

    saved: list[Path] = []
    if not urls:
        return saved  # nothing to fetch — never probe or open a browser for an empty list

    if not probe_cdp(cdp_url):
        # No dev-mode browser for the whole batch — quarantine each URL that is
        # not already saved (an existing target is still an idempotent skip), then
        # exit cleanly. Never open a session, never launch Chrome, never crash.
        for url in urls:
            target = _target_path(url, files_dir)
            if target.exists():
                saved.append(target)
            else:
                _quarantine_no_endpoint(manifest_path, url, cdp_url)
        return saved

    # One connection for the whole list; a tab per URL rides the warm session.
    handled = 0
    try:
        with open_session(cdp_url) as fetch_tab:
            for url in urls:
                path = _dispatch_url(
                    url,
                    fetch_tab,
                    cdp_url=cdp_url,
                    files_dir=files_dir,
                    manifest_path=manifest_path,
                )
                handled += 1
                if path is not None:
                    saved.append(path)
    except Exception as exc:
        # The warm session failed to open (or tear down) after the probe passed —
        # e.g. Chrome died between probe and connect, or a non-Chrome CDP server
        # answered the probe (US15 DEVLOG). ``_dispatch_url`` already caught every
        # *per-URL* nav failure, so only URLs the loop never reached remain: a
        # teardown raise after a full pass leaves ``urls[handled:]`` empty (nothing
        # double-quarantined). Quarantine that remainder with a **distinct** reason
        # and never crash the batch (rule 02).
        for url in urls[handled:]:
            target = _target_path(url, files_dir)
            if target.exists():
                saved.append(target)  # idempotent skip precedes the quarantine
            else:
                _manifest.append(
                    manifest_path,
                    stage="browser-fetch",
                    url=url,
                    cdp_url=cdp_url,
                    reason=f"browser session failed to open: {exc}",
                )
    return saved


app = typer.Typer(
    add_completion=False,
    help="Fetch bot-walled URLs through a dev-mode Chrome over CDP, one warm session (US15/US16).",
)


@app.command()
def run(
    urls_file: Annotated[
        Optional[Path],
        typer.Argument(
            exists=True,
            dir_okay=False,
            readable=True,
            help="file of bot-walled URLs, one per line; reads stdin when omitted",
        ),
    ] = None,
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
    interactive: Annotated[
        bool,
        typer.Option(
            "--interactive",
            help=(
                "human-in-the-loop-once: on a detected wall, notify on stderr and "
                "poll until you clear it by hand, then auto-resume (US40). Off by "
                "default — a wall quarantines and the batch never blocks."
            ),
        ),
    ] = False,
) -> None:
    """Fetch a list of URLs over one warm browser; print each saved path, one per line.

    Reads URLs from ``urls_file`` (or stdin when omitted), one per line — blank
    lines and surrounding whitespace are ignored, so a single URL is just a
    one-line list. Prints each saved (or already-present) path to stdout in
    first-seen order (AC5), a drop-in to pipe into ``convert-html``; anything that
    could not be fetched is quarantined in ``manifest`` (inspect it for the
    reasons), never crashing the run.
    """
    text = urls_file.read_text(encoding="utf-8") if urls_file else sys.stdin.read()
    urls = [line.strip() for line in text.splitlines() if line.strip()]
    paths = browser_fetch_batch(
        urls,
        cdp_url=cdp,
        files_dir=files_dir,
        manifest_path=manifest,
        interactive=interactive,
    )
    for path in paths:
        typer.echo(str(path))
    # Don't leave a batch that saved nothing silent: note the quarantine count on
    # stderr (stdout stays paths-only for piping into convert-html). The manifest
    # carries the per-URL reasons.
    quarantined = len(urls) - len(paths)
    if quarantined:
        typer.echo(
            f"{quarantined} of {len(urls)} URL(s) quarantined (see {manifest})", err=True
        )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (rule 03): ``uv run browser-fetch`` and ``__main__``."""
    return invoke(app, argv)


if __name__ == "__main__":
    raise SystemExit(main())
