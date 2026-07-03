# US 17 Recover bot-walled records through the browser lane

As a *researcher who just ran fetch-one over a list*, i want *a step that reads
the bot-walled records fetch-one quarantined and feeds their URLs to
browser-fetch*, so that *the papers blocked by a wall are retried through my real
browser automatically, instead of me copying each blocked URL out of the manifest
by hand*.

US 12 makes fetch-one tag a bot-walled 403 with `blocked_by`; US 15/16 can fetch
those URLs through a dev-mode Chrome. This story is the **join** US 12 deferred in
so many words — *"a future orchestrator could read a `blocked_by` record and
dispatch it"*: `recover-blocked` reads `manifest.jsonl`, selects the records that
carry a `blocked_by` host, and hands their URLs to browser-fetch's warm-batch
path (US 16). It is deterministic, offline routing — it filters the append-only
manifest and delegates the actual fetching; it holds no browser logic and no
judgement of its own, so there is no LLM in the loop.

This is a **second recovery lane, parallel to `resolve-oa`**: US 12's record
names `resolve-oa` (recover via DOI/title lookup) as one way around a wall; the
browser lane recovers by *rendering the walled page itself*. recover-blocked drives
the browser lane and leaves the DOI lane to US 9.

The scope is a **new orchestrator step, `recover-blocked`**, over the manifest. It
selects `blocked_by` records not yet recovered and dispatches their URLs to
browser-fetch (US 16). It does **not** drive Chrome itself (it delegates to
browser-fetch), does **not** re-classify walls (it trusts US 12's `blocked_by`),
does **not** touch resolve-oa's DOI lane, and does **not** rewrite past records —
the manifest stays append-only, gaining one new recovery-outcome record per
retry.

## Acceptance Criteria

1. Given a manifest holding `blocked_by` records (from `researchgate.net` and
   `pubmed.ncbi.nlm.nih.gov`) alongside generic, non-blocked quarantines
   (e.g. a plain `http 403` from `https://example.edu/papers/some-closed-paper`)
   - when recover-blocked selects the retry set
     - then only the `blocked_by` records' URLs are chosen; the generic
       quarantines are ignored (no `blocked_by` host, not this lane's job)
2. Given the selected blocked URLs
   - when recover-blocked dispatches them
     - then they are fetched via browser-fetch's warm-batch path (one Chrome,
       US 16) — not re-attempted by the plain fetch-one that already failed on
       the wall
3. Given a blocked URL that browser-fetch now recovers through the browser
   - when recover-blocked records the outcome
     - then a **new** recovery record is appended to the manifest; the original
       `blocked_by` record is left untouched (append-only, one record per event)
4. Given **no** dev-mode Chrome reachable
   - when recover-blocked cannot drive browser-fetch
     - then the blocked URLs stay quarantined via browser-fetch's own
       missing-endpoint quarantine (US 15 AC 2), and recover-blocked exits cleanly
       — never crashes, the retry simply waits for a run with Chrome up
5. Given a `blocked_by` record already retried and recovered in a prior run
   - when recover-blocked scans the manifest again
     - then it does not re-dispatch that URL (it reads the append-only manifest
       and skips URLs already recovered) — the step is idempotent across runs

## Case handling (classify-then-dispatch)

recover-blocked classifies each manifest record on two cheap fields: does it carry
a `blocked_by` host, and has that URL already been recovered in a later record?
**No `blocked_by`** → skip (generic quarantine, not this lane). **`blocked_by`
present, not yet recovered** → add its URL to the retry set. **`blocked_by`
present but already recovered** → skip (idempotent). The retry set is then
dispatched wholesale to browser-fetch (US 16), which owns the connect/navigate/
quarantine decisions — recover-blocked adds no browser logic of its own. Reading
`blocked_by` as the routing key is the encoded knowledge: a new walled host
becomes routable the moment US 12's table tags it, with no change here.

## Later stages (deferred)

- **Choosing the lane per host.** Some walls yield to `resolve-oa` (a DOI lookup
  finds an open-access copy), others only to the browser. A policy that picks the
  cheaper lane per `blocked_by` host — try resolve-oa first, fall back to the
  browser — is a routing refinement deferred here; this story drives the browser
  lane only. See DEVLOG.
- **A consolidated recovery report.** A read-side view grouping the append-only
  manifest by paper — blocked → retried → recovered — is complementary (US 11's
  deferred "consolidated view"); this story *performs* the retry, that one *shows*
  its history.
- **Scheduling / unattended runs.** Waking periodically to drain new `blocked_by`
  records against a standing dev-mode Chrome is an orchestration layer above this
  step, not built here.
