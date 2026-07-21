# US 40 — PoC tech note: ScienceDirect full-text through the browser lane

**Date:** 2026-07-21 · **Driver for:** [US 40](../user-stories/us-40-browser-fetch-lazyload-interactive-wall.md)
· **Sample paper:** `https://doi.org/10.1016/j.jbi.2018.12.005` — *"A systematic
approach for developing a corpus of patient reported adverse drug events"*
(PsyTAR corpus, J. Biomed. Inform. 90, 2019), **open archive**.

This note compiles the throwaway PoC — every script and every measured run —
that established what US 40 must build. The scripts lived in the session
scratchpad (ephemeral); they are preserved here in full so the finding is
reproducible without re-running the captcha dance. The real 1.6 MB article HTML
capture is **not** committed (copyrighted Elsevier content); its measured
properties are recorded instead, and the implementation should build a minimal
synthetic fixture (`"Loading…"` body vs. a filled body) rather than ship the real
page.

## TL;DR

The full-text HTML **is** obtainable and converts cleanly (14 242-word Markdown,
all sections), but the existing `browser-fetch` cannot get it. Three distinct
blockers, each proven:

| # | Blocker | Proof | Fix |
|---|---------|-------|-----|
| 1 | `wait_until="networkidle"` never fires | `browser-fetch` quarantined: `Timeout 30000ms exceeded … waiting until "networkidle"` | `domcontentloaded` + bounded settle |
| 2 | Cloudflare "Are you a robot?" wall | interstitial on the fresh profile | human clears once → poll → auto-resume |
| 3 | Body lazy-loads on scroll | captured body = `"Loading…"` (1 word) → 783-word stub | scroll-nudge + wait for real body word count |

Plus a persistence finding: the `cf_clearance` cookie **survives a full Chrome
restart** in `.browser-profile`, but has a Cloudflare TTL — so interactive
recovery is a standing mechanism, not one-time setup.

## Environment

- **Chrome** 150.0.7871.129, launched by `uv run browser-up` on the persistent
  `.browser-profile`, CDP endpoint `http://localhost:9222`.
- **Playwright** 1.61.0 (repo dep). **websockets** pulled ephemerally via
  `uv run --with websockets` for the raw-CDP experiments — never added to the
  project.
- Loopback CDP must bypass any `HTTP(S)_PROXY` (`NO_PROXY=localhost,127.0.0.1`),
  the same trap `browser_fetch._no_proxy_for` already encodes.

## Timeline of findings

### 1. `resolve-oa` — no free copy, so the browser lane is required

```
$ uv run resolve-oa "10.1016/j.jbi.2018.12.005" --email … 
quarantined (…): 10.1016/j.jbi.2018.12.005
```

Unpaywall reports no OA PDF, so the free-DOI lane does not apply — confirming the
paper must come through the authenticated browser against ScienceDirect itself.
(The article *is* open-archive on ScienceDirect; Unpaywall's verdict is just
stale/absent — a separate matter.)

### 2. Existing `browser-fetch` — `networkidle` timeout (blocker #1)

Against `browser-up`'s clean Chrome, `connect_over_cdp` worked (navigated fine),
but the capture was quarantined:

```
reason: "navigation failed: Page.goto: Timeout 30000ms exceeded.
         … waiting until \"networkidle\""
```

ScienceDirect keeps analytics / long-poll connections open, so `networkidle`
never settles. This is exactly the residual the DEVLOG `browser_fetch` happy-path
E2E flag anticipated ("a page that never idles … retune the wait then").

### 3. Playwright vs. the *everyday* Chrome — why `browser-up` is needed

An earlier attempt against a normal, already-running user Chrome failed at
connect time:

```
BrowserType.connect_over_cdp: Protocol error (Browser.setDownloadBehavior):
Browser context management is not supported.
```

`connect_over_cdp` chokes on a full-profile everyday Chrome. `browser-up`'s
dedicated-profile Chrome does **not** hit this — so the lane must run against
`browser-up`, not whatever Chrome the operator happens to have open. (This matches
the DEVLOG note that "context management not supported" came from a non-`browser-up`
CDP server.)

### 4. Raw-CDP dead-ends — why we stayed on Playwright

Two raw-CDP routes were tried to sidestep the everyday-Chrome error and were
abandoned once `browser-up`'s Chrome made Playwright work:

- **`PUT /json/new` + page websocket** (`poc_cdp.py`): the `/json`, `/json/list`,
  `/json/new` HTTP endpoints return **empty** on this Chrome (a DevTools security
  restriction — only `/json/version` answers). Dead end.
- **Browser-level ws + `Target.createTarget`** (`poc_cdp2.py`, `poc_html.py`):
  works in principle, but a raw `websockets` client hit
  `InvalidMessage: did not receive a valid HTTP response` on the ws handshake
  (Chrome rejects the upgrade without `--remote-allow-origins`; Playwright handles
  this itself). Also `httpx(trust_env=False)` to `localhost` resolved to IPv6
  `::1` and got `Connection refused` while Chrome listened on IPv4 — fetch the ws
  URL with `curl` or pin `127.0.0.1`.

**Conclusion:** drive everything through Playwright `connect_over_cdp` against
`browser-up`'s Chrome; raw CDP buys nothing here.

### 5. The wall + human-in-the-loop poll (blocker #2)

`poll_capture.py` opened the article, detected the Cloudflare interstitial
(`請稍候…` = "please wait"), **notified** and **polled** every 3 s; the operator
solved the captcha once by hand; the loop auto-continued:

```
[open] title='ScienceDirect' wall=True fulltext=False
>>> ACTION NEEDED: solve the captcha in the Chrome window …
[poll   3s] wall=True  … title='請稍候...'
[poll   9s] wall=False … title='(loading: Error)'
[poll  12s] … title='A systematic approach for developing a corpus …'
[cleared] after 15s — fulltext present
[saved] sd-fulltext.html (1168950 bytes)
```

### 6. The lazy-load stub (blocker #3)

That first capture looked successful but `convert-html` yielded only **783
words** — header/abstract, no body. Root cause: the readiness check fired on the
body container's mere *existence*, but the container held a placeholder:

```
body container words: 1
body preview: Loading...
```

Only ~720 words were real DOM text; the rest of the 1.17 MB was `<script>` JSON /
SVG / CSS that `markdownify` correctly drops.

### 7. Scroll-nudge + body-fill readiness → full capture

`scroll_capture.py` scrolled to trigger the lazy-load and gated the save on the
body's **real word count**:

```
[poll   3s] wall=False body_words=0     ← "Loading…" placeholder
[poll  12s] wall=False body_words=10312 ← body filled
[ready] body has 10312 words after 12s
[saved] sd-fulltext2.html (1628126 bytes)
```

`convert-html` on this capture produced **14 242 words** with every section:

```
abstract YES · introduction YES · methods YES · results YES
discussion YES · conclusion YES · references YES · acknowled YES
```

### 8. Clearance persists across a browser restart (with a TTL)

Killed the `browser-up` Chrome, relaunched on the same `.browser-profile`, probed
with **no human**:

```
[poll   0s] wall=False …
[poll   6s] wall=False body_words=10312   ← no captcha, straight through
[ready] body has 10312 words after 6s
```

`cf_clearance` survives the restart because it lives in the persistent profile.
It is not eternal — Cloudflare issues it with a TTL — so when it lapses the wall
returns and needs one more manual clear. Hence interactive recovery is a
**standing** mechanism.

## Measured constants (for the readiness gate)

| Body state | Real word count in the body container |
|------------|---------------------------------------|
| unloaded placeholder | **1** (`"Loading…"`) |
| fully loaded | **10 312** |
| → converted Markdown | **14 242** words, all sections |

A threshold on the order of **800 words** cleanly separates a stub from a real
body. Pin it against a sample fixture in `src/tests/samples/`.

## Reproduction

```bash
# 1. bring up the dedicated-profile Chrome (headed; needs a display)
uv run browser-up                       # prints http://localhost:9222

# 2. run the readiness-gated capture (solve the captcha by hand if it appears)
uv run python scroll_capture.py out.html   # scripts in the appendix below

# 3. convert and verify the full body survived
uv run convert-html out.html               # -> out.md, ~14k words, all sections
```

The clearance persists, so re-running after a restart needs no captcha until the
`cf_clearance` TTL lapses.

---

## Appendix A — the definitive scripts

### `scroll_capture.py` — clear-wall → scroll → body-fill readiness → save

```python
"""Re-capture, correctly: clear-wall (if any) -> scroll to trigger ScienceDirect's
lazy-loaded body -> wait until the body container actually fills (not 'Loading...')
-> capture. Readiness = real word count in the body, not container existence."""
import os, sys, time
from pathlib import Path

os.environ["NO_PROXY"] = "localhost,127.0.0.1," + os.environ.get("NO_PROXY", "")
os.environ["no_proxy"] = os.environ["NO_PROXY"]

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
ARTICLE = "https://doi.org/10.1016/j.jbi.2018.12.005"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("files/sd-fulltext2.html")
READY_WORDS = 800          # body must exceed this to count as loaded
MAX_WAIT_S = 240

WALL_RX = ("are you a robot", "confirm you are a human", "captcha challenge")
BODY_JS = """
(() => {
  const el = document.querySelector('#body, section.Body, .Body, .article-text');
  if (!el) return -1;                       // no container yet
  const t = (el.innerText || '').trim();
  if (/^loading/i.test(t)) return 0;        // placeholder still showing
  return t.split(/\\s+/).length;            // real word count
})()
"""

def probe(page):
    try:
        txt = (page.evaluate("document.body ? document.body.innerText : ''") or "").lower()
        is_wall = any(m in txt for m in WALL_RX)
        body_words = page.evaluate(BODY_JS)
        return is_wall, int(body_words), (page.title() or "")[:80]
    except Exception as exc:
        return False, -1, f"(loading: {type(exc).__name__})"

def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        page.goto(ARTICLE, wait_until="domcontentloaded", timeout=45000)
        time.sleep(2)
        waited, notified = 0, False
        while waited < MAX_WAIT_S:
            is_wall, body_words, title = probe(page)
            if is_wall and not notified:
                print("\n>>> ACTION NEEDED: solve the captcha in the Chrome window; I'm polling.\n", flush=True)
                notified = True
            if not is_wall:                       # nudge the lazy-loader
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(0.4)
                    page.evaluate("window.scrollTo(0, 0)")
                except Exception:
                    pass
            print(f"[poll {waited:>3}s] wall={is_wall} body_words={body_words} title={title!r}", flush=True)
            if body_words >= READY_WORDS:
                html = page.content()
                OUT.parent.mkdir(parents=True, exist_ok=True)
                OUT.write_text(html, encoding="utf-8")
                print(f"[ready] body has {body_words} words after {waited}s", flush=True)
                print(f"[saved] {OUT} ({len(html)} bytes)", flush=True)
                page.close()
                return 0
            time.sleep(3); waited += 3
        print(f"[timeout] body never reached {READY_WORDS} words in {MAX_WAIT_S}s", flush=True)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
```

### `poll_capture.py` — notify → poll → auto-continue (interactive wall recovery)

```python
"""Open the article, keep the tab alive, POLL until the human clears the wall,
then auto-capture. Human-in-the-loop-once, no captcha solving. Uses a
domcontentloaded wait (NOT networkidle) and is navigation-resilient."""
import os, sys, time
from pathlib import Path

os.environ["NO_PROXY"] = "localhost,127.0.0.1," + os.environ.get("NO_PROXY", "")
os.environ["no_proxy"] = os.environ["NO_PROXY"]

from playwright.sync_api import sync_playwright

CDP = "http://localhost:9222"
ARTICLE = "https://doi.org/10.1016/j.jbi.2018.12.005"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("files/sd-fulltext.html")
POLL_S, MAX_WAIT_S = 3, 240
WALL_RX = ("are you a robot", "confirm you are a human", "captcha challenge")

def state(page):
    """(is_wall, has_fulltext, title, url). Navigation-resilient: while the DOI
    redirect chain is in flight, evaluate() raises 'context destroyed' — treat any
    such transient as 'still loading' and let the caller keep polling."""
    try:
        url = page.url
        txt = (page.evaluate("document.body ? document.body.innerText : ''") or "").lower()
        is_wall = any(m in txt for m in WALL_RX)
        has_ft = page.evaluate("!!document.querySelector('#body, .Body, section.Body, .article-text')")
        return is_wall, bool(has_ft), (page.title() or "")[:90], url
    except Exception as exc:
        return False, False, f"(loading: {type(exc).__name__})", ""

def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        page = ctx.new_page()
        page.goto(ARTICLE, wait_until="domcontentloaded", timeout=45000)
        time.sleep(2)
        is_wall, has_ft, title, url = state(page)
        print(f"[open] url={url}\n[open] title={title!r} wall={is_wall} fulltext={has_ft}", flush=True)
        if is_wall or not has_ft:
            print("\n>>> ACTION NEEDED: a bot-wall / captcha is showing.\n"
                  ">>> Please click/solve it in the Chrome window now.\n"
                  ">>> I am polling every 3s and will auto-continue.\n", flush=True)
        waited = 0
        while waited < MAX_WAIT_S:
            is_wall, has_ft, title, url = state(page)
            if has_ft and not is_wall:
                html = page.content()
                OUT.parent.mkdir(parents=True, exist_ok=True)
                OUT.write_text(html, encoding="utf-8")
                print(f"[cleared] after {waited}s — fulltext present: {title!r}", flush=True)
                print(f"[saved] {OUT} ({len(html)} bytes)", flush=True)
                page.close()
                return 0
            print(f"[poll {waited:>3}s] wall={is_wall} fulltext={has_ft} title={title!r}", flush=True)
            time.sleep(POLL_S); waited += POLL_S
        print(f"[timeout] wall not cleared within {MAX_WAIT_S}s — leaving tab open", flush=True)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
```

> **Note — why two scripts:** `poll_capture.py` proved blocker #2 (interactive
> wall recovery) but still captured on container *existence*, so it saved the
> `"Loading…"` stub. `scroll_capture.py` folds in blocker #3's fix (scroll +
> real-word-count readiness) and is the one to lift into `browser-fetch`. Both
> use the `domcontentloaded` wait that fixes blocker #1.

## Appendix B — exploratory dead-ends (kept for the record)

These established what does **not** work; none should be carried into the
implementation. Reproduced verbatim.

### `poc_sd.py` — Playwright, everyday Chrome → `setDownloadBehavior` error

```python
"""PoC: pull the ScienceDirect PDF through the already-running dev Chrome (CDP).
FAILED against an everyday-profile Chrome:
  BrowserType.connect_over_cdp: Protocol error (Browser.setDownloadBehavior):
  Browser context management is not supported.
Lesson: run against browser-up's dedicated-profile Chrome, not the user's."""
import os, sys
from pathlib import Path
from urllib.parse import urljoin
os.environ["NO_PROXY"] = "localhost,127.0.0.1," + os.environ.get("NO_PROXY", "")
os.environ["no_proxy"] = os.environ["NO_PROXY"]
from playwright.sync_api import sync_playwright
CDP = "http://localhost:9222"
ARTICLE = "https://doi.org/10.1016/j.jbi.2018.12.005"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("poc.pdf")
# ... connect_over_cdp(CDP) raised before any navigation; abandoned.
```

### `poc_cdp.py` — raw CDP via `PUT /json/new`

```python
"""FAILED: /json, /json/list, /json/new return EMPTY on this Chrome (DevTools
security restriction — only /json/version answers). Also httpx(trust_env=False)
to localhost hit IPv6 ::1 -> Connection refused while Chrome listened on IPv4.
Lesson: the HTTP target-list endpoints are unusable here; only /json/version."""
# httpx.Client(trust_env=False).put(f"{CDP}/json/new?{ARTICLE}") -> ConnectError
```

### `poc_cdp2.py` / `poc_html.py` — browser-level ws + `Target.createTarget`

```python
"""Connect to the browser ws from /json/version, then Target.createTarget +
flattened Target.attachToTarget to drive a page, and fetch the resource in-page.
FAILED at the raw ws handshake:
  websockets.exceptions.InvalidMessage: did not receive a valid HTTP response
Chrome rejects the CDP ws upgrade without --remote-allow-origins; Playwright
handles this internally, so we reverted to Playwright. (The in-page fetch()->
base64 idea is sound and is how a future PDF-download story would pull the
'View PDF' pdfft binary with the session's own cookies.)"""
async def main():
    # ver = curl http://localhost:9222/json/version  (httpx tripped on ::1)
    # browser_ws = ver["webSocketDebuggerUrl"]
    # await call(ws, "Target.createTarget", {"url": ARTICLE})   # then attach + Page.enable
    ...
```

---

*Filed alongside US 40. The durable knowledge (why `networkidle` fails, the
`domcontentloaded`+settle wait, the interactive-recovery loop, the readiness
threshold, the restart-persistence + TTL) is captured in the US spec's
Acceptance Criteria and "Later stages"; this note is the reproducible evidence
behind them.*
