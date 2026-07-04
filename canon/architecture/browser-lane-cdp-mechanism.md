---
title: Browser lane CDP fetch mechanism
updated: 2026-07-04
status: verified
sources: []
---

# Browser lane CDP fetch mechanism

**What.** The browser lane recovers a paper that a plain HTTP client cannot fetch (a
bot-walled 403 from ResearchGate / PubMed) by driving a **real, already-running dev-mode
Chrome** over the Chrome DevTools Protocol (CDP). It is two console steps, one layer apart:

- `browser-up` (US 18, `src/paper_degist/browser_up.py`) — **sets up** the browser: locate
  Chrome, launch it on the remote-debugging port against a fixed persistent
  `--user-data-dir`, wait until the CDP endpoint answers, print it, and detach. Idempotent:
  a reachable dev-mode Chrome is reused, never a second one. Owns Chrome's *startup*.
- `browser-fetch` (US 15, `src/paper_degist/browser_fetch.py`) — **attaches** to that
  running Chrome (`connect_over_cdp`), navigates one URL, waits for the DOM to settle
  (`networkidle`), and saves the rendered HTML under `files/` with the researcher's real
  logged-in cookies. Registered as the `browser-fetch` console script.

**Shared classify signal.** Both steps classify (rule 02) on the same cheap signal — *is a
dev-mode Chrome answering on the CDP endpoint?* — via `browser_up._default_probe_cdp` (a GET
to `/json/version`). `browser-fetch` **reuses** that probe, so the two never drift. The
endpoint is deterministic configured input, default `DEFAULT_CDP = "http://localhost:9222"`
(a `--cdp` flag overrides; a different port or remote debugger is a flag, not a new code
path).

**Lifecycle invariant — never launch, never kill (from `browser-fetch`).** `browser-fetch`
only *attaches*: it never launches Chrome (that is `browser-up`) and never kills it. Teardown
closes **only the tab (and a context only if it had to create one)** it opened — it
deliberately does **not** call `browser.close()`, because for a CDP *attach* Playwright's own
docs describe that as "similar to force-quitting the browser" and it would clear the
researcher's live contexts; exiting `sync_playwright()` disconnects the driver instead. The
persistent profile carries the researcher's manual login forward across runs.

**Proxy-bypass is encoded knowledge (rule 02), applied twice.** The CDP endpoint is a
loopback debug server, so any `HTTP(S)_PROXY` must be bypassed or it 502s a perfectly
reachable Chrome:

- the **probe** uses `httpx.get(..., trust_env=False)` (`browser_up._default_probe_cdp`);
- the **fetch** wraps the CDP session in `browser_fetch._no_proxy_for(host)`, which adds the
  CDP host to `NO_PROXY` for the duration (restoring it after).

Both were surfaced by real E2E runs on a proxied machine — the same trap, encoded once per
step rather than re-derived.

**Quarantine, not loud failure (the split from `browser-up`).** `browser-up` has no batch to
carry, so a launch it cannot complete is a loud `BrowserUpError` (non-zero exit).
`browser-fetch` has an item to carry forward, so it **quarantines** to `manifest.jsonl`
(`stage: "browser-fetch"`) — never crashes: an unreachable endpoint and a failed navigation
get **distinct** reasons, and a success appends a `saved` record. Re-runs are idempotent (an
already-saved URL is skipped with no new record). Neither step calls an LLM.

**Known boundary — a wall page can be saved as if it were the paper.** `browser-fetch` trusts
whatever the browser renders; without the profile logged in to the host, a Cloudflare
challenge / login / "Request PDF" page renders successfully and is saved as `saved`
(confirmed live: the `Spaced_Repetition…` URL saved a 939 KB Cloudflare-gated page titled for
an unrelated paper). Automating the wall is out of scope (the researcher logs in by hand once);
detecting wall-vs-paper is deferred (see `DEVLOG.md`).

**Scope edges.** Reusing one warm connection across a batch is US 16; routing `blocked_by` /
`resolve-oa` records into `browser-fetch` is US 17; in-script auth is deferred.

**Sources.** [[session 5a774313-8a20-4405-8679-3b563de41dd4]] (browser-up design),
[[session 6225f110-7e1f-4ca2-bd51-2a6e883dd259]] (browser-fetch build + real E2E). Related:
[[browser-up keeps no state file]].
