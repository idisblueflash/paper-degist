# US 29 Discover candidates by topic via OpenAlex

As a *researcher whose topic review wants a free, no-key, cross-field index*, i
want *`discover` to search OpenAlex by topic and emit each work in the common
candidate schema — with the abstract reconstructed and a direct OA PDF link when
one exists*, so that *I get broad CC0 coverage and a fetchable open copy up
front, without an API key and without a separate open-access resolve step*.

## Background

US 25 built `discover` with a `--source` **registry** (arXiv, s2) over one query
per run; US 27 added SerpAPI Scholar adapters to it. This story adds one more
adapter, **`--source openalex`**, over the OpenAlex Works endpoint
(`https://api.openalex.org/works`). OpenAlex's edge in this registry:

- **Keyless.** No signup, no key — like arXiv. Politeness is the **"polite
  pool"** convention: send a contact email as a `mailto=` query param
  (`--email` / `OPENALEX_EMAIL`) for the faster shared pool. Absent, it still
  runs (common pool) and **logs a warning** — a missing email is *not* a
  quarantine (contrast US 27's hard SerpAPI-key requirement), because OpenAlex
  serves keyless traffic. This mirrors `resolve-oa`'s existing
  `UNPAYWALL_EMAIL` contact-email convention.
- **Full abstract, but inverted.** Each work carries `abstract_inverted_index`
  (a `{token: [positions]}` map), **not** plain text. The adapter reconstructs
  the abstract by ordering tokens by position, encoding that quirk **once**
  (rule 02). A work with a null index is emitted with `abstract` null and
  `abstract_present: false` (US 25 AC3), never dropped.
- **OA PDF up front.** `best_oa_location.pdf_url` (falling back to the first
  `oa_locations[]` with a `pdf_url`) gives a directly fetchable open copy — the
  same `pdf_url` edge US 27's `scholar` adapter has, so a hit can short-circuit
  `resolve-oa`.
- **Cross-field, CC0.** Broader than arXiv (all disciplines, older works) and
  free of Semantic Scholar's keyless rate-limit wall (US 25's bake-off found
  S2's keyless pool unusable — every call 429'd).

The query uses `filter=title_and_abstract.search:<query>`, sorted by
`cited_by_count:desc` so the wide net surfaces the most-cited first. It maps into
US 25's **common schema** (`title`, `authors`, `abstract`, `doi`, `url`,
`published`, `source_id`), extended with `pdf_url` (when OA) and `cited_by`. It
stays **coarse and high-recall** (US 25's contract); US 26 narrows.

The default source stays arXiv (US 25's bake-off verdict); OpenAlex is an opt-in
`--source openalex`. A phase-2 characterization (rule 06 phase 2 — result count,
abstract-present rate, OA-link rate, latency; no relevance ground truth to
crown by accuracy) is run against real queries at build time and recorded here.

## Acceptance Criteria

1. Given a topic query and `--source openalex`
   (e.g. `"graph neural networks for molecular property prediction"`)
   - when discover searches OpenAlex Works and it answers with hits
     - then each hit is emitted in US 25's common JSONL schema — `title`,
       `authors`, `abstract`, `doi`, `url`, `published`, `source_id` — and a
       `discover` record is appended to `manifest.jsonl` (`stage: "discover"`,
       `source: "openalex"`) with `query` and `result_count`
2. Given a hit whose `abstract_inverted_index` is present
   - when discover emits it
     - then `abstract` is the **reconstructed** plain text (tokens ordered by
       their positions), not the raw inverted-index map
3. Given a hit that carries an open `best_oa_location` (or an `oa_locations[]`
   entry) with a `pdf_url` (e.g. an arXiv or repository copy)
   - when discover emits it
     - then the record carries a `pdf_url` (directly fetchable by `fetch-one`)
       and a `cited_by` count; a hit with no OA `pdf_url` is still emitted,
       without `pdf_url`
4. Given `--source openalex` and **no** contact email (neither `--email` nor
   `OPENALEX_EMAIL`)
   - when discover runs the search
     - then it still queries OpenAlex (the keyless common pool) and **logs a
       warning** that the polite pool was skipped — it does **not** quarantine
       (contrast US 27's missing-SerpAPI-key branch); the email is politeness,
       not an access requirement
5. Given a work with a null `abstract_inverted_index`
   - when discover emits it
     - then the record is emitted with `abstract` null and
       `abstract_present: false` (US 25 AC3) — title + DOI still feed the
       downstream chain — rather than dropped here
6. Given a query that returns zero results, or OpenAlex errors / rate-limits
   (a 429 / 4xx / 5xx)
   - when discover cannot get candidates
     - then it quarantines to `manifest.jsonl` (`stage: "discover"`) with a
       **distinct** `reason` separating empty-result from api-error, and exits
       cleanly — never crashes, never calls an LLM

## Case handling (classify-then-dispatch)

discover classifies first on `--source` (US 25): `openalex` is one more registry
adapter; an unknown source still quarantines offline (US 25 AC5). **Before the
network**, a missing contact email does **not** block — it downgrades to the
common pool with a warning (OpenAlex is keyless), unlike US 27's SerpAPI key
which is a hard offline quarantine. The adapter issues the Works query
(`title_and_abstract.search`, `sort=cited_by_count:desc`, `mailto` when set) and
maps the response into the common schema, encoding OpenAlex's fixed quirks
**once** (rule 02): abstract-inverted-index reconstruction and
`best_oa_location`/`oa_locations` PDF extraction. **Then on the transport
result**: hits → emit JSONL (with `pdf_url` when an OA link exists); zero hits →
quarantine (empty-result); an HTTP 4xx/5xx / 429 → quarantine (api-error). No
LLM is ever called to classify or rescue a record.

## Later stages (deferred)

- **Topic/concept-id filtering.** OpenAlex exposes structured `topics.id` /
  `concepts.id` filters (a controlled vocabulary) beyond free-text
  `title_and_abstract.search`. Precise topic-id targeting is a precision
  refinement (US 26's grain), deferred from this wide-net entry.
- **Date / OA-only filters at the source.** `from_publication_date` and
  `is_oa:true` filters belong to US 26's deterministic narrowing pass, not this
  high-recall front (mirrors US 25's deferral).
- **Cursor pagination / depth.** discover returns OpenAlex's first page (up to
  200 via `per-page`); cursor paging (`cursor=*`) for exhaustive recall is
  gated, like US 25/27, on the first page proving too shallow.
- **Optional API key.** OpenAlex now offers an optional key ($1/day free tier)
  for higher limits; keyless + `mailto` is sufficient for this step, so a
  `--api-key` path is deferred until throughput demands it.
- **OA-location cross-check for `resolve-oa`.** Reusing OpenAlex's OA locations
  as a fallback when Unpaywall reports closed is its **own** story (US 30),
  sharing the OpenAlex client module — not folded in here.
