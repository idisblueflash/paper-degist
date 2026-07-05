# US 29 Discover candidates via OpenAlex (keyless, DOI-bearing)

As a *researcher whose topic spans fields and decades (not just arXiv preprints),
and who needs a DOI on every hit for downstream dedup and OA resolution*, i want
*`discover` to search OpenAlex for a topic and emit each work in the same
candidate schema — carrying a DOI, a reconstructed abstract, and its open-access
PDF link when one exists*, so that *I get broad, keyless coverage with the
identifiers the rest of the pipeline needs, instead of arXiv's DOI-less rows or
Semantic Scholar's key-walled 429s*.

## Background

US 25 built `discover` with a `--source` **registry** (arXiv, s2) over one query
per run, and US 27 added the SerpAPI Scholar adapters to it. This story adds one
more registry adapter — **`--source openalex`** — that closes the two gaps US 25's
bake-off recorded:

- **arXiv never carries a DOI** (its `abs` URL is the identifier), so arXiv rows
  can't feed US 14's DOI dedup or US 9/10's DOI-keyed OA lookup directly.
- **Semantic Scholar's keyless tier is unusable** — every call `429`ed on the
  shared pool, so S2 is opt-in behind `S2_API_KEY`.

OpenAlex answers both: it is **keyless** (no signup; a *polite pool* is requested
by passing `mailto=` — env `OPENALEX_MAILTO`, already the etiquette OpenAlex
documents), and its Works corpus carries a **DOI on most records** plus the
`open_access` block with `is_oa`, `oa_status`, and `best_oa_location.pdf_url`. So
a single openalex hit can arrive DOI-keyed *and* with a directly-fetchable PDF —
US 27's edge, without a paid key.

**The one fixed quirk to encode once (rule 02):** OpenAlex does not return a plain
abstract string — it returns `abstract_inverted_index`, a `{word: [positions]}`
map (for copyright reasons). The adapter reconstructs the abstract by scattering
each word to its positions and joining in order; a work with a null inverted index
is emitted `abstract_present: false` (US 25 AC3), not dropped.

Both the search (`GET /works?search=…&filter=…`) and the polite-pool `mailto` are
one endpoint (`https://api.openalex.org/works`), **no API key**. It maps into
US 25's **common schema**, extended (as US 27 did) with `pdf_url` and `cited_by`
when the record carries them, plus `oa_status`. It stays coarse and high-recall
(US 25's contract); US 26 narrows.

## Phase-2 bake-off (to be measured)

Per rule 06 phase 2, before shipping run the two example queries below through the
`openalex` adapter **and re-run the US 25 arXiv default on the same queries**, then
record the deterministic signals here (characterize, don't crown by accuracy —
there is no relevance ground truth):

| Source | Query | Count | Abstract-present | DOI | OA-PDF present | Latency |
| ------ | ----- | ----- | ---------------- | --- | -------------- | ------- |
| openalex | `diffusion models for protein backbone generation` | _tbd_ | _tbd_ | _tbd_ | _tbd_ | _tbd_ |
| openalex | `mechanistic interpretability of transformer circuits` | _tbd_ | _tbd_ | _tbd_ | _tbd_ | _tbd_ |
| arXiv (US 25) | same two | _tbd_ | _tbd_ | _tbd_ | — | _tbd_ |

The claim to test is that openalex raises **DOI-present** and **OA-PDF-present**
rates over arXiv at comparable recall; whether it becomes the new default (over
US 25's arXiv) is settled by this evidence, not asserted here.

## Acceptance Criteria

1. Given a topic query and `--source openalex`
   (e.g. `"diffusion models for protein backbone generation"`)
   - when discover searches OpenAlex Works and it answers with hits
     - then each hit is emitted in US 25's common JSONL schema — `title`,
       `authors`, `abstract`, `doi`, `url`, `published`, `source_id` (the OpenAlex
       work id) — and a `discover` record is appended to `manifest.jsonl`
       (`stage: "discover"`, `source: "openalex"`) with `query` and `result_count`
2. Given a returned work whose abstract arrives as an `abstract_inverted_index`
   - when discover emits it
     - then `abstract` is the reconstructed plain-text abstract (words scattered
       to their positions and joined in order), not the raw index map
3. Given a returned work whose `abstract_inverted_index` is null (some records
   carry none)
   - when discover emits it
     - then the record is still emitted with `abstract` null and
       `abstract_present: false` (US 25 AC3) — dropped downstream, not here
4. Given a returned work whose `open_access.best_oa_location` carries a `pdf_url`
   - when discover emits it
     - then the record carries `pdf_url` (directly fetchable by `fetch-one`),
       `oa_status`, and `cited_by` (from `cited_by_count`) when present; a work
       with no OA location is still emitted, without `pdf_url`
5. Given a query that returns zero results, or OpenAlex errors / rate-limits
   (a 4xx/5xx, or a 429 for exceeding the pool)
   - when discover cannot get candidates
     - then it quarantines to `manifest.jsonl` (`stage: "discover"`) with a
       **distinct** `reason` separating empty-result from api-error, and exits
       cleanly — never crashes, never calls an LLM

## Case handling (classify-then-dispatch)

discover classifies first on `--source` (US 25): `openalex` is a new registry
adapter; anything else still quarantines (unknown source) offline. The adapter
issues the Works search (passing `mailto=` for the polite pool when
`OPENALEX_MAILTO` is set — an etiquette default, **not** a required key, so its
absence never quarantines), and maps the response into the common schema, encoding
OpenAlex's fixed shape **once** (rule 02): the `abstract_inverted_index`
reconstruction, the `open_access`→`pdf_url`/`oa_status` mapping, and
`cited_by_count`→`cited_by`. **Then on the transport result**: hits → emit JSONL
(with `pdf_url` when an OA location exists); zero hits → quarantine (empty-result);
an HTTP error / 429 → quarantine (api-error). No LLM is ever called to classify or
rescue a record.

## Later stages (deferred)

- **Filter at the source.** OpenAlex's `filter=` (date range, `type:article`,
  `is_oa:true`, `topics.id:…`) can pre-narrow at the API. Per US 25's split that
  narrowing belongs to US 26, so this adapter uses `search=` wide-net only; a
  `--filter` pass-through is a later refinement.
- **Topic-id resolution.** Resolving a fuzzy topic string to a canonical OpenAlex
  Topic id (`GET /topics?search=`) for precise `filter=topics.id` discovery,
  instead of brittle keyword `search=`, is its own small step — deferred.
- **Pagination / depth.** discover returns OpenAlex's first page (`per_page`).
  Cursor paging (`cursor=*`) for exhaustive recall is gated (like US 25) on the
  first page proving too shallow.
- **Cross-source merge.** When US 25's deferred "query both and merge" lands,
  openalex's always-present DOI makes it the natural dedup key for the union.
