# US 38 Survive rate limits with bounded backoff; pace every source

As a *researcher running a wide topic sweep*, i want *`discover` to treat an
HTTP 429 as a distinct, retriable case — bounded exponential backoff that honors
`Retry-After` — and `discover-batch` to pace every keyless source, not just
arXiv*, so that *a big N-queries × M-sources fan-out survives transient rate
limits instead of silently dropping pairs to a catch-all `api-error` quarantine*.

## Background

`discover` (US 25/27/29) catches every network/API failure in one generic
`except Exception` and quarantines it as `api-error: HTTPStatusError` — a 429
rate-limit is indistinguishable from a bad key or a 500, and the pair's results
are lost without a retry. `discover-batch` (US 31) fans queries × sources
**serially**, so the rate pressure is cumulative request *volume*, not
concurrency — yet only arXiv is paced (`ARXIV_MIN_INTERVAL`, 3 s); OpenAlex and
Semantic Scholar issue back-to-back calls with no wait. A wide sweep across the
keyless pair therefore trips free-tier limits and bleeds pairs into quarantine.

A rate-limit is now a **known, recurring** case, so per rule 02 it becomes its
own code branch rather than a fall-through: classify the 429 out of the generic
`except`, retry it with **bounded exponential backoff** (honoring a `Retry-After`
header when present, capped), and quarantine only after the retry budget is
exhausted — with a **distinct** reason so the manifest tells a transient
rate-limit apart from a hard API error. The fan-out itself is **not** removed:
its cross-query/cross-source recall is US 31's whole value; this story hardens
it, it does not retreat from it.

The scope is (a) a retry/backoff branch in `discover`'s dispatch and (b) an
inter-call pace for the remaining keyless sources in `discover-batch`. It does
**not** add a new source adapter, add concurrency (the loop stays serial), or
change the merge/dedup logic. Backoff sleeps go through an **injectable pause**
(like `discover_batch`'s `pause`) so tests never actually wait.

## Acceptance Criteria

1. Given a source adapter that raises a 429 once and then succeeds on the next
   call (e.g. an `arxiv` query for `"mixture of experts routing"`)
   - when discover runs with a retry budget of at least one
     - then it retries after backing off and returns the recovered candidates —
       the pair is **not** quarantined
2. Given a source adapter that raises 429 on every attempt (e.g. an `openalex`
   query for `"retrieval augmented generation"`)
   - when discover exhausts its retry budget
     - then the pair is quarantined to `manifest.jsonl` with a **distinct**
       reason (`rate-limited-exhausted`, not `api-error`) and discover returns
       `None` — never crashes
3. Given a 429 response that carries a `Retry-After` header
   - when discover backs off before its retry
     - then it waits the header's interval (capped at a ceiling) via the
       injected pause, in preference to its default exponential schedule
4. Given a non-429 API error (e.g. a 500 or a bad-key `HTTPStatusError` from an
   `s2` query for `"speculative decoding"`)
   - when discover classifies the failure
     - then it is quarantined **immediately** as `api-error` with no retry — the
       backoff branch is reserved for rate-limits, distinct from hard errors
5. Given a `discover-batch` run that issues consecutive `openalex` (or `s2`)
   calls across several queries
   - when it walks the fan-out
     - then it waits a per-source minimum interval between those calls — mirroring
       the arXiv etiquette pace — and still pays no wait before the first call
       to a source
6. Given the backoff schedule (default and `Retry-After`)
   - when discover retries
     - then every wait is taken through the **injected** pause (no real
       `time.sleep` in the loop), so the suite runs without delay and the pace is
       deterministic

## Case handling (classify-then-dispatch)

The dispatch splits the failure by kind before quarantining: a 429 (rate-limit)
→ the retry-with-backoff branch, which loops up to the budget, honoring
`Retry-After` when present and otherwise an exponential schedule, then
quarantines as `rate-limited-exhausted` if it never clears; any other exception
→ the existing immediate `api-error` quarantine, unchanged. `discover-batch`
adds no new input classification — it extends the arXiv-only pace to a
per-source interval so every keyless source is spaced. No LLM is ever called;
nothing crashes; an exhausted pair takes out only itself and the batch finishes.

## Later stages (deferred)

- **Global token-bucket across sources.** This story paces each source
  independently; a shared budget that adapts to observed 429s across a long run
  is a later refinement.
- **Jitter.** The backoff is a plain (capped) exponential; adding randomized
  jitter to avoid synchronized retries can follow once multiple concurrent
  operators exist — moot while the loop is serial and single-operator.
- **Per-source retry tuning.** One retry budget/schedule serves all sources;
  per-adapter tuning (arXiv vs. keyed S2) would slot in at the registry.
