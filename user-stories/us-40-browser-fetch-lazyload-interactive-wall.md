# US 40 Capture lazy-loaded full-text through an interactive wall

As a *researcher recovering an open-access paper from a JavaScript-heavy
publisher (ScienceDirect / Elsevier) whose page lazy-loads its body behind a
Cloudflare "Are you a robot?" wall*, i want *browser-fetch to wait on a settle
signal such pages actually reach, let me clear the wall by hand once and then
auto-resume, and save only once the real article body has loaded*, so that *the
full-text HTML is captured cleanly and feeds convert-html — instead of being
falsely quarantined on a networkidle timeout or saved as a "Loading…" stub —
without ever solving a captcha in-script*.

## Background

US 15's `browser-fetch` navigates one URL, waits for the DOM to settle with
`wait_until="networkidle"`, and saves `page.content()`; US 35 adds a wall-vs-paper
check before the save. Both assume a page that (a) reaches network idle and (b)
renders its body eagerly. A modern publisher SPA violates both, and a real
end-to-end PoC against `https://doi.org/10.1016/j.jbi.2018.12.005` (the open-access
*PsyTAR* corpus paper, J. Biomed. Inform., 2026-07-21) pinned three distinct
failures on the same capture path:

1. **`networkidle` never fires.** ScienceDirect keeps analytics / long-poll
   connections alive, so the 30 s `networkidle` wait times out and the article is
   **falsely quarantined** as `navigation failed` — the exact residual DEVLOG
   already flagged for a retune ("a page that never idles … retune the wait
   then", browser_fetch happy-path E2E flag). A `domcontentloaded` + bounded
   settle wait reaches the page in ~2 s.
2. **A Cloudflare captcha wall.** On a fresh (or TTL-expired) profile the host
   answers with an "Are you a robot?" interstitial. US 35 *detects* this and
   quarantines — correct for an unattended batch, but for an OA paper the
   researcher is entitled to, the right move is a **human-in-the-loop-once**
   clear-and-resume, not an outright drop.
3. **The body is lazy-loaded on scroll.** Capturing on container *existence*
   grabbed the placeholder — the body container held literally `"Loading…"`
   (1 word), yielding a 783-word header-only stub. After a scroll nudge and a
   wait for the body to fill (0 → 10 312 words), `convert-html` produced the
   full **14 242-word** Markdown with every section (Abstract, Introduction,
   Methods, Results, Discussion, Conclusion, References, Acknowledgements).

The full reproducible PoC — every script and every measured run behind these
findings — is compiled in the tech note
[`doc/us40-sciencedirect-poc.md`](../doc/us40-sciencedirect-poc.md).

The PoC also verified the clearance is **durable**: after the operator solved the
captcha once, killing Chrome and relaunching `browser-up` on the same persistent
`.browser-profile` loaded the body with **no wall** — the `cf_clearance` cookie
survives a browser restart. It is not eternal, though: Cloudflare issues it with a
TTL, so when it lapses the wall returns and needs one more manual clear. That is
why interactive recovery is a **standing mechanism**, not one-time setup.

The scope is **additive to browser-fetch's existing capture path** (rule 02 —
classify-then-dispatch, extended, not rewritten): a settle-based wait that retires
`networkidle` as the default, an **opt-in** interactive-recovery mode that
notifies + polls + resumes on a detected wall, and a **content-readiness gate**
that scroll-nudges and requires real body content before the save. It does **not**
solve captchas or click consent (the operator clears the wall by hand once — US 15
/ US 35 deferral), does **not** download the "View PDF" binary (a Could-Have,
deferred below), does **not** change the default unattended/batch contract
(US 16 — a wall still quarantines and the batch never blocks), and does **not**
call an LLM.

## Ground truth (sample-measured constant)

The body-readiness threshold is measured against the PoC sample, not guessed: the
unloaded body reads **1 word** (`"Loading…"`) and the fully-loaded body **10 312
words**, so a threshold on the order of **800 words** cleanly separates a stub
from a real body. The sample HTML (`sd-fulltext-lazyload.html`, the loaded
capture) lands in `src/tests/samples/` and pins the constant.

## Acceptance Criteria

1. Given a publisher page that never reaches network idle — ScienceDirect keeps
   analytics / long-poll alive at
   `https://doi.org/10.1016/j.jbi.2018.12.005`
   - when browser-fetch navigates to it
     - then it waits on a settle signal the page actually reaches
       (`domcontentloaded` + a bounded settle), **not** `networkidle`, so a
       heavy publisher SPA is captured rather than falsely quarantined as a
       navigation timeout — retiring the DEVLOG `networkidle` residual
2. Given the article body is lazy-loaded and its container first shows a
   `"Loading…"` placeholder — navigating
   `https://doi.org/10.1016/j.artmed.2021.102083`
   - when browser-fetch prepares to save the capture
     - then it scroll-nudges to trigger the lazy-load and saves **only** once the
       body container holds real content above the sample-measured word threshold
       (never a `"Loading…"` stub), so convert-html receives the full body — all
       sections, not a header-only fragment
3. Given interactive-recovery mode is **enabled** and a Cloudflare "Are you a
   robot?" wall is detected (US 35's markers / title signals) on
   `https://doi.org/10.1016/j.jbi.2018.12.005`
   - when browser-fetch classifies the capture
     - then it notifies the operator on stderr that a manual clear is needed,
       polls the page on a bounded interval, and **auto-resumes** the capture the
       moment the wall clears and the body loads — it never attempts to solve or
       click the captcha itself
4. Given interactive-recovery mode is **not** enabled (the default, unattended /
   batch path) and a wall is detected or the body never loads within the bound
   - when browser-fetch classifies the capture
     - then it quarantines with a **distinct** reason and moves on exactly as
       US 35 / US 16 do today — the batch never blocks waiting on a human, so
       US 16's one-URL-failure-never-aborts-the-batch contract is preserved

## Case handling (classify-then-dispatch)

Between "the DOM settled" and "save the HTML", browser-fetch classifies the
rendered capture on cheap deterministic signals: is a **wall** present (US 35's
markers / title-slug mismatch), and has the **body loaded** (the readiness gate —
the body container's real word count exceeds the sample-measured threshold, and is
not the `"Loading…"` placeholder)? Dispatch:

- **Body loaded, no wall** → save and record `saved`, as US 15 does today.
- **Wall detected, or body not yet loaded:**
  - *interactive-recovery mode* → notify on stderr, scroll-nudge, and poll on a
    bounded interval; re-classify each poll and resume the save the instant the
    page is clear-and-loaded; on exceeding the bound, quarantine with a distinct
    reason (never hang).
  - *default (unattended) mode* → quarantine with the distinct reason and move on
    — never block the batch, never launch or kill Chrome, never solve the wall.

The settle signal, the readiness threshold, the scroll nudge, and the wall
markers are the encoded knowledge (rule 02). A new publisher's lazy-load body
selector is a one-line addition to a selector set — the manifest of stubbed /
walled captures is the queue of cases — not a new code path. No signal beyond
these deterministic checks is needed, so the step stays LLM-free.

## Later stages (deferred)

- **Download the "View PDF" binary (Could-Have).** ScienceDirect's OA articles
  render full-text HTML, so this story covers them via `convert-html`. Resolving
  the `pdfft` link and downloading the authenticated PDF binary through the warm
  session — to feed `render-pdf` → `ocr-page` → `convert-pdf` for PDF-only
  articles — is a separate deferred story, not needed while HTML full-text is
  available.
- **Per-publisher readiness selectors.** The gate ships ScienceDirect's body
  selector; growing it into a per-host lazy-load selector table (Wiley, Springer,
  IEEE behind the same wall) is deferred until a real capture recurs with an
  unrecognized container.
- **Automatic wall solving stays permanently out of scope.** Clicking consent or
  solving a captcha in-script is bot-detection evasion — brittle and against the
  host's terms. The operator clears the wall by hand once; interactive-recovery
  mode only *waits and resumes*. This story never defeats a wall.
- **Cookie-TTL re-clear cadence and richer notification.** When `cf_clearance`
  lapses, interactive mode notifies for one more manual clear; a scheduled
  re-warm, or a notification channel beyond stderr (desktop / push), is deferred.
