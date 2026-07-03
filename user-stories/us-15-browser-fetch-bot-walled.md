# US 15 Fetch a bot-walled page through a dev-mode browser

As a *researcher recovering a paper that 403s a plain fetch*, i want *a step that
drives a Chrome i already have open in dev-mode to fetch one URL's rendered
HTML*, so that *a page that bot-walls an automated HTTP client is still captured
through a real, logged-in browser session instead of being lost to the wall*.

## Background

US 12 teaches fetch-one to *recognize* a bot-walled 403 (ResearchGate, PubMed)
and tag it `blocked_by` — but recognizing a wall is not getting past it. Those
hosts reject the plain HTTP client precisely because it is not a browser; a real
Chrome the researcher started in **dev-mode** (`--remote-debugging-port=9222`,
its own persistent `--user-data-dir`) is a genuine browser session and loads the
page. This step connects to that **already-running** Chrome over the Chrome
DevTools Protocol (CDP), navigates one URL, and saves the rendered HTML — the
recovery *mechanism* that complements US 9's `resolve-oa` DOI lane.

The operator owns the browser's lifecycle: Claude Code brings the dev-mode Chrome
up (US 18, `browser-up`), the researcher logs in once and solves any interactive
wall by hand. This step never launches or kills Chrome — it **attaches** for the
fetch and detaches. It is a classify-then-dispatch step over
one cheap signal: is a CDP endpoint reachable? Reachable → navigate and capture;
not → quarantine. No new judgement, no LLM.

The scope is a **new CLI step,&#x20;****`browser-fetch`****, over a single URL**. It connects
to a CDP endpoint (default `http://localhost:9222`), navigates the URL, waits for
the DOM to settle, saves the rendered HTML under `files/`, and prints the saved
path to stdout — mirroring fetch-one's save + manifest contract so `convert-html`
can consume the result. It does **not** launch or close Chrome, does **not** log
in or solve captchas for you, does **not** classify which 403s are walls (US 12's
job) or decide which URLs need the browser (US 17's job), and does **not** batch a
list (US 16).

## Acceptance Criteria

1. Given a dev-mode Chrome reachable at the CDP endpoint and a bot-walled URL
   (e.g. `https://www.researchgate.net/publication/220320021_Spaced_Repetition_and_Long-Term_Retention`)
   - when browser-fetch navigates to it and the DOM settles
     - then the page's rendered HTML is saved under `files/` and its path is
       printed to stdout, with a `saved` record appended to `manifest.jsonl`
       (`stage: "browser-fetch"`)
2. Given **no** CDP endpoint reachable at the configured address
   (e.g. Chrome is not running in dev-mode on `:9222`)
   - when browser-fetch cannot connect
     - then it quarantines the URL to the manifest (`stage: "browser-fetch"`,
       `reason` naming a missing dev-mode browser endpoint), exits cleanly, and
       never crashes — the item waits for a run with Chrome up
3. Given Chrome **is** reachable but the navigation itself fails (a nav timeout or
   error on `https://www.researchgate.net/publication/319012693_The_Testing_Effect_in_the_Classroom`)
   - when browser-fetch cannot render the page
     - then it quarantines with a **distinct** reason (navigation failed, not a
       missing endpoint), so the manifest separates "no browser" from "browser
       could not load this page" — and still never crashes
4. Given a URL whose HTML was already saved by a prior run
   - when browser-fetch runs again on the same URL
     - then it skips and does not re-fetch or overwrite the saved file (re-runs
       stay safe), mirroring fetch-one's idempotency

## Case handling (classify-then-dispatch)

browser-fetch classifies on one cheap signal before doing any work: can it open a
CDP connection to the configured endpoint? **No endpoint** → quarantine
(`reason`: missing dev-mode browser) and move on — never crash, never launch a
browser itself. **Endpoint reachable** → open a tab, navigate, and wait for the
DOM to settle (network idle) so client-rendered pages are captured, not the raw
initial response; on a navigation error it quarantines with the distinct
nav-failed reason; on success it saves the HTML and records `saved`. The CDP
endpoint is the encoded knowledge — a different port or a remote debugger is a
`--cdp` option, not a new code path. No signal beyond reachability and nav result
is needed, so the step stays deterministic and LLM-free.

## Later stages (deferred)

- **Reuse one warm browser across a list.** This story fetches one URL per
  invocation, connecting and detaching each time. Looping many URLs over a single
  persistent connection — so one login/warm session serves the whole batch — is
  US 16.
- **Deciding which URLs need the browser.** browser-fetch fetches the URL it is
  given; reading fetch-one's `blocked_by` records and routing them here
  automatically is US 17. This story is only the mechanism.
- **Automating the wall itself.** Logging in, clicking consent, or solving a
  captcha in-script is out of scope — the researcher does that by hand in the
  real browser once, and the persistent profile carries it forward. Script-driven
  auth is a separate, deferred design. See DEVLOG.

