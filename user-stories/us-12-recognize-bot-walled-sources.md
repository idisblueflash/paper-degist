# US 12 Recognize bot-walled sources on a blocked fetch

As a *researcher reading `manifest.jsonl` by hand*, i want *a fetch-one
quarantine from a known bot-walling source to say so and name the recovery
lane*, so that *I know the 403 is a wall to route around (via `resolve-oa`), not
a bug in my URL or a transient error to retry*.

Some sources reliably reject the fetcher: ResearchGate
(`researchgate.net`) and PubMed (`pubmed.ncbi.nlm.nih.gov`) both return
`HTTP 403` on a direct fetch because they bot-wall automated clients. Today both
land in the manifest with the generic `reason: "http 403"` — indistinguishable
from a one-off server error, and silent about what to do next. The knowledge
that these hosts are *walls, not bugs* is exactly the case-handling that rule 02
says to encode into the script once, rather than re-derive by hand on every run.
On top of that, a PubMed URL resolves only to an **abstract**, not the full
paper, so even a successful fetch would not yield the text — the record should
steer the reader to `resolve-oa` regardless.

The scope is an **additive, classify-side** enhancement to fetch-one's existing
403 handling: it adds a recognized-host branch that writes a distinct,
actionable manifest reason and a `blocked_by` host field. It does **not** make a
new network call, call an LLM, auto-invoke `resolve-oa`, change any exit code or
stdout, or alter the record shape for any non-bot-walled 403.

## Acceptance Criteria

1. Given a fetch that returns `HTTP 403` from a known bot-walling host
   (e.g. `https://www.researchgate.net/publication/287147155_The_Mnemonic_Keyword_Method`)
   - when fetch-one classifies the response
     - then the quarantine record carries `blocked_by: "researchgate.net"` and a
       `reason` that names it a bot-walled source and points at the `resolve-oa`
       recovery lane
2. Given a fetch that returns `HTTP 403` from PubMed
   (e.g. `https://pubmed.ncbi.nlm.nih.gov/2303742/`)
   - when fetch-one classifies the response
     - then the record carries `blocked_by: "pubmed.ncbi.nlm.nih.gov"` and a
       `reason` that flags it both as bot-walled and as an abstract-only page,
       steering the reader to `resolve-oa`
3. Given a `HTTP 403` (or any 4xx/5xx) from a host **not** on the known list
   (e.g. `https://example.edu/papers/some-closed-paper`)
   - when fetch-one cannot handle it
     - then it quarantines with the existing generic record (US 2 AC 6) — no
       `blocked_by` field, `reason` unchanged
4. Given the `blocked_by` field
   - then it is fetch-one-only and additive — no other stage's record shape
     changes, and the manifest stays append-only (one record per fetch event)

## Case handling (classify-then-dispatch)

fetch-one already dispatches on the response (US 2). This story adds one branch
*ahead of* the generic 4xx/5xx fallthrough: when the response is a block
(403) **and** the request host matches the known bot-wall table, dispatch to the
bot-walled handler (distinct reason + `blocked_by`); otherwise fall through to
the existing generic quarantine unchanged. The host table is the encoded
knowledge — a new bot-walling host discovered later is a one-line addition to
that table, not a new code path. No signal beyond the host and status is needed,
so the branch stays deterministic, offline, and LLM-free.

## Later stages (deferred)

- **Auto-route to `resolve-oa`.** fetch-one only holds the URL, not a DOI or
  title, so it cannot itself drive the recovery lane. A future orchestrator could
  read a `blocked_by` record and dispatch it to `resolve-oa` (which needs a
  DOI/title) automatically. Out of scope here — this story only *names* the lane
  in the record. See DEVLOG.
- **Growing the host table from the manifest.** The manifest is the queue of
  cases; a recurring generic-403 host that shows up repeatedly is the trigger to
  promote it into the bot-wall table. That promotion is a manual, per-host
  decision, not automated here.
