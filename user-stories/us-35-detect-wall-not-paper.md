# US 35 Detect a wall page captured instead of the paper

As a *researcher recovering a bot-walled paper through the browser lane*, i want
*browser-fetch to recognize when the page it rendered is a login / consent /
Cloudflare wall rather than the paper itself*, so that *a wall is quarantined for
me to log in and retry instead of being silently saved and treated forever as a
successful capture*.

## Background

US 15's `browser-fetch` trusts whatever the dev-mode Chrome renders: it navigates
one URL, waits for the DOM to settle, and saves the HTML with a `saved` record.
But a host can answer the navigation with a **wall** instead of the paper — a
login form, a cookie-consent interstitial, or a Cloudflare challenge / "Request
PDF" page — and that wall renders *successfully*, so its HTML is saved and
recorded `saved` as if the wall were the content.

This was **confirmed live** (US 15 real E2E, 2026-07-04): fetching a ResearchGate
publication through a real dev-mode Chrome **not logged in** saved a 939 KB HTML
that was a Cloudflare-gated "Request PDF" page — recorded `saved`, exactly the
wall-as-paper case. Two deterministic signals were present: Cloudflare challenge
markers (`cloudflare`, `challenge-platform`) in the body, and a `<title>` for an
**unrelated** paper (a title/URL-slug mismatch).

`convert-html`'s "too thin" check (US 5) does **not** catch this: a wall is a
full, content-rich page, not a near-empty shell, so it sails past a body-length
threshold. The judgement belongs at capture time, where the requested URL and the
rendered title are both in hand.

The scope is an **additive wall-signature check on browser-fetch's capture path,
run before the save**. It classifies the rendered HTML on cheap deterministic
signals (known wall markers; requested-slug vs rendered-`<title>` mismatch) and,
on a wall, quarantines with a **distinct** reason and writes **no file** — so a
bad wall never becomes the sticky saved artifact. It does **not** log in, solve a
captcha, or click consent (US 15 leaves in-script auth to the researcher by hand),
does **not** rename or alter a genuine capture, and does **not** call an LLM.

## Acceptance Criteria

1. Given a rendered page carrying a known wall signature — a Cloudflare challenge
   (markers `cloudflare` / `challenge-platform`) returned for
   `https://www.researchgate.net/publication/221609650_Retrieval_Practice_Produces_More_Learning`
   - when browser-fetch classifies the capture **before** saving
     - then it quarantines the URL to `manifest.jsonl` (`stage: "browser-fetch"`,
       a **distinct** `reason` naming a wall, not the paper), writes **no** HTML
       file, exits cleanly, and never crashes — so a later logged-in run can
       recapture it
2. Given a rendered page whose `<title>` does **not** reflect the requested URL's
   paper slug — navigating
   `https://www.academia.edu/38654201/Distributed_Practice_in_Verbal_Recall_Tasks`
   returns a page titled for an unrelated paper
   - when browser-fetch compares the requested slug to the rendered title
     - then it quarantines with the wall reason and writes no file — the mismatch
       is treated as "captured the wall, not this paper", using the same slug
       comparison shape as US 13 (lowercase, punctuation-stripped tokens)
3. Given a rendered page that **is** the paper — a genuine, logged-in capture of
   `https://www.researchgate.net/publication/220320021_Spaced_Repetition_and_Long-Term_Retention`
   whose title matches the requested slug and carries no wall marker
   - when browser-fetch classifies the capture
     - then it saves the HTML and records `saved` exactly as US 15 does today —
       the check adds no false quarantine to a real capture
4. Given the wall check runs **before** the save
   - then a wall never lands as a saved `.html` and never becomes the idempotent
     "already saved" artifact of US 15 AC4 — the sticky-bad-capture failure mode
     cannot occur, and the manifest stays append-only

## Case handling (classify-then-dispatch)

Between "the DOM settled" and "save the HTML", browser-fetch classifies the
rendered content on cheap deterministic signals: does the body carry a **known
wall marker** (Cloudflare `challenge-platform`, a login/consent signature), or
does the rendered `<title>` **fail to reflect the requested URL's paper slug**?
Either → quarantine with the distinct wall reason and **do not write the file**
(so idempotency never pins a wall). Neither → save and record `saved` as before.
The wall markers and the slug-mismatch rule are the encoded knowledge — a
newly-seen wall signature is a one-line addition to the marker set (rule 02: the
manifest of wall captures is the queue of cases), not a new code path. No signal
beyond the markers and the title/slug check is needed, so the step stays
deterministic and LLM-free.

## Later stages (deferred)

- **Automating the wall.** Logging in, clicking consent, or solving a captcha
  in-script stays out of scope — the researcher logs the persistent profile into
  the host by hand once (US 15's deferral). This story only *detects* a wall so it
  is quarantined instead of saved; it does not get past one.
- **Per-host wall taxonomy.** The marker set ships the signatures actually
  observed (Cloudflare challenge, generic login/consent). Growing it into a
  per-host wall-signature table — and distinguishing "login wall" from "consent
  wall" from "captcha" with their own reasons — is deferred until a real capture
  recurs with an unrecognized signature.
- **Title/slug mismatch tuning.** The requested-slug vs rendered-title check is a
  token-overlap comparison; calibrating its threshold against a labelled set (so a
  legitimately-retitled landing page is not a false wall) pairs with the
  resolve-oa title-overlap threshold work. See DEVLOG.
