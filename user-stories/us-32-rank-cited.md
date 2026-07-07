# US 32 Rank candidates by citation count, keep the top N

As a *researcher standing on the giants' shoulders*, i want *the discovered
candidate pool ranked by citation count and cut to the top N*, so that *the
most-established papers on the topic surface first — before I spend fetches,
embeddings, or reading time on the long tail*.

## Background

`discover` / `discover-batch` (US 25/31) cast a wide net and deliberately
over-return; `abstract-filter` (US 26) narrows by **topical similarity**. This
story adds the second, complementary ranking axis: **influence**. OpenAlex,
Semantic Scholar, and the two Scholar lanes already emit a `cited_by` count on
their candidates (US 25/27/29 encoded each source's field once), so the step is
pure, offline arithmetic over JSONL — no API call, no LLM, no network.

- **Rank + cut.** Candidates carrying a `cited_by` count are sorted descending
  and the top `--top` survive. The sort is **stable**: ties keep their input
  order, so a re-run over the same file emits the same list (deterministic,
  diff-able).
- **A missing count is a classified drop, not a crash.** arXiv candidates never
  carry `cited_by` (the API has no citation field); a candidate without a
  usable count cannot be ranked and is dropped with a `filtered` manifest
  record (`reason: no-cited-by`) — visible, auditable, and recoverable by a
  later enrichment step. A count of `0` **is** a usable count (a new paper
  ranks last; it is never confused with a missing field).
- **Every drop is auditable.** A candidate ranked below the cut leaves a
  `filtered` record (`reason: beyond-top`) carrying its `cited_by`, mirroring
  `abstract-filter`'s below-threshold discipline: nothing is dropped silently.

The output is the surviving records unchanged (still `discover`-shaped JSONL),
ordered most-cited first — a drop-in to `abstract-filter` or `fetch-one`.
Composition is the operator's choice: `rank-cited` **before** `abstract-filter`
keeps the famous papers regardless of abstract wording; **after** it, the
shortlist's most-cited. There is no measured threshold constant to calibrate
(rule 06 phase 2): `--top` is an operator budget, not a heuristic.

The scope is a **new deterministic step, `rank-cited`, over candidate JSONL**.
It does **not** fetch citation counts for candidates that lack one (a later
enrichment story), weight recency, or blend similarity and citations into one
score.

## Acceptance Criteria

1. Given a candidate JSONL where citation counts arrive out of order (e.g.
   `cited_by: 187`, `cited_by: 9041`, `cited_by: 512`)
   - when rank-cited runs
     - then the candidates are printed as JSONL ranked by **descending**
       `cited_by` (9041, 512, 187), each record passed through unchanged
2. Given more rankable candidates than `--top` (e.g. four candidates,
   `--top 2`)
   - when rank-cited cuts the ranking
     - then only the top N are emitted and each candidate below the cut leaves
       a `filtered` manifest record (`stage: "rank-cited"`,
       `reason: beyond-top`) carrying its `cited_by`
3. Given a candidate without a usable `cited_by` (an arXiv record, or a
   malformed non-integer count) among rankable ones
   - when rank-cited runs
     - then that candidate is dropped with a distinct `filtered` record
       (`reason: no-cited-by`), the rankable rest still rank, and a `cited_by`
       of `0` is ranked — never dropped as missing
4. Given two candidates with the **same** `cited_by` count
   - when rank-cited sorts them
     - then they keep their input order (stable sort) — the output is
       deterministic across re-runs
5. Given an input line that is not a JSON object (a truncated pipe, a garbage
   line)
   - when rank-cited parses the input
     - then the line is quarantined to `manifest.jsonl` (`stage: "rank-cited"`,
       a distinct reason naming the line) and the well-formed candidates still
       run — never crashes
6. Given an input where **no** candidate carries a usable `cited_by`
   - when rank-cited finishes with nothing to rank
     - then it quarantines (`stage: "rank-cited"`, a distinct `empty-rank`
       reason), prints nothing to stdout, and exits cleanly

## Case handling (classify-then-dispatch)

Each parsed candidate is classified on its `cited_by` field: a usable count
(an `int`, including `0`) → ranked; anything else (absent, `null`, a non-int)
→ `filtered` with `no-cited-by`. Ranked candidates beyond the `--top` cut →
`filtered` with `beyond-top`. An unparseable/non-object input line →
quarantined with the raw line preserved (reusing US 26's loader discipline).
Zero rankable candidates → quarantine (`empty-rank`). No LLM is ever called;
the step is pure and offline.

## Later stages (deferred)

- **Citation enrichment.** Looking up a missing `cited_by` (e.g. an arXiv
  candidate's OpenAlex record by DOI) is a separate story — this step ranks
  only what the pool already carries.
- **Recency weighting.** Raw counts favour old papers; a recency-normalized
  score (citations per year) is a later refinement, gated on the raw cut
  proving too conservative for young fields.
- **Blended scoring.** Combining `cited_by` with US 26's `similarity` into one
  ranking is deferred — composition via piping covers today's need.
