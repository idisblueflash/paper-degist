# US 16 Reuse one warm browser across a batch of URLs

As a *researcher checking many bot-walled URLs in one run*, i want *browser-fetch
to reuse a single long-running Chrome across the whole list*, so that *i pass the
wall once and every URL in the batch rides the same warm, authenticated session
instead of paying a cold browser and a fresh login per URL*.

US 15 fetches one URL per invocation: it connects to the dev-mode Chrome,
navigates, and detaches — every time. Checking a list that way re-opens the CDP
connection for each URL, and a session that forgets its cookies between URLs
re-hits the wall on every single one. This story teaches browser-fetch to take a
**list**: connect once, open and close a **tab** per URL against that one warm
browser, and detach at the end **without killing Chrome**. Paired with Chrome's
persistent `--user-data-dir`, the logged-in cookies survive across every URL in
the batch — and across runs, so the next invocation reuses the same warm session.

The distinction that keeps Chrome alive is deliberate: closing a *tab*
(`page.close()`) is not closing the *browser*, and letting the CDP client drop
merely **detaches**. browser-fetch never calls the browser-level close on a shared
dev-mode instance — the researcher owns that lifecycle (US 15).

The scope is an **enhancement to browser-fetch: accept a list and loop over it on
one connection**. It reads URLs from a file argument or stdin (one per line),
connects to the CDP endpoint once, fetches each URL on its own tab, and appends
one record per URL — reusing US 15's per-URL save, idempotency, and quarantine
behaviour unchanged. It does **not** launch or close Chrome, does **not**
parallelize beyond a small bounded number of open tabs, and does **not** add any
login/auth automation. The persistent profile is an operational property of *how
the researcher starts Chrome*, documented in the CLI manual, not new step code.

## Acceptance Criteria

1. Given a list of bot-walled URLs and one reachable dev-mode Chrome
   - when browser-fetch processes the list
     - then it opens the CDP connection **once** and fetches every URL over that
       single connection — Chrome is not reconnected or restarted per URL
2. Given a URL in the batch whose fetch has completed
   - when browser-fetch moves to the next URL
     - then the finished URL's **tab** is closed but the **browser stays
       running**, so a later URL in the same batch reuses the warm session
3. Given the batch finishes (or aborts partway)
   - when browser-fetch is done with the list
     - then it detaches from the CDP endpoint **without closing Chrome**, so the
       same warm browser serves the next run
4. Given one URL in the list fails (a nav timeout, or Chrome becomes unreachable
   mid-batch)
   - when browser-fetch cannot fetch that one URL
     - then that URL quarantines to the manifest (US 15's reasons) and the batch
       **continues** with the remaining URLs — one failure never aborts the run
5. Given the surviving URLs
   - when browser-fetch has processed the list
     - then each saved page's path is printed to stdout, one per line, in
       first-seen order — a drop-in over a list, composable with `convert-html`

## Case handling (classify-then-dispatch)

The connect-time classify from US 15 lifts to the **batch boundary**: browser-fetch
checks the CDP endpoint once — unreachable at the start → every URL quarantines
with the missing-endpoint reason and the step exits cleanly. Reachable → it holds
the one connection and dispatches each URL to a fresh tab, reusing US 15's
per-URL classify (nav-error → quarantine that URL; already-saved → skip;
success → save). A mid-batch loss of the browser is classified per URL as a
fetch failure — that URL quarantines and the loop carries on — so the batch is
resilient, never crashing, never calling an LLM. Tab-per-URL with a small bounded
count is the dispatch shape; detach-not-close is the invariant that keeps the
warm session alive for the next run.

## Later stages (deferred)

- **Deciding which URLs go into the batch.** This story fetches the list it is
  given; assembling that list from fetch-one's `blocked_by` manifest records is
  US 17. browser-fetch stays a mechanism over an explicit list.
- **Real parallelism.** Fetching several tabs concurrently (a bounded pool with
  backpressure) could speed a large batch, but risks tripping the very
  rate-limits and bot-walls the browser is meant to slip past — deferred in favour
  of sequential tab reuse. See DEVLOG.
- **Managing Chrome's lifecycle for the user.** Starting the dev-mode Chrome and
  supplying the persistent profile is US 18 (`browser-up`), one layer before this
  step; detecting a stale/crashed instance to relaunch it stays deferred there.
  This step still only attaches to a browser someone else brought up.
