# US 25 Discover candidate papers by topic

As a *researcher starting a topic review*, i want *a step that searches a
scholarly API for a topic query and emits each candidate paper with its abstract
as one JSONL record*, so that *the pipeline has a wide-net list of maybe-relevant
papers to filter, instead of me pasting URLs by hand*.

## Background

Today the pipeline *starts* at `parse-url`/`fetch-one` — it assumes you already
have the URLs. This story adds the upstream front: given a topic, go find the
candidates. It is deliberately **coarse and high-recall** — keyword/query search
casts a wide net and over-returns; its job is "find everything that might be
relevant," not "find the right ones." Narrowing is US 26's job.

Two free APIs are in scope, chosen by a `--source` flag: **arXiv** (no key, no
signup; a ~3 s politeness delay between calls) and **Semantic Scholar** (free;
optional key, and a `TLDR` one-line summary on many records that US 26 can use as
a cheap pre-filter signal). Each is an **adapter** that maps the API's response
into one common JSONL schema — `title`, `authors`, `abstract`, `doi`/`url`,
`published`, `source_id`, and `tldr` when present. Which one becomes the default
is settled by a **phase-2 bake-off** (rule 06 phase 2): run the same real queries
through both and measure the deterministic signals — result count, abstract-present
rate, metadata completeness, overlap, latency — and record the evidence here.
There is no relevance ground truth to score, so the bake-off characterizes; it
does not crown a winner by accuracy.

The scope is a **new entry step, `discover`, over one query and one source**. It
emits candidates as JSONL to stdout (drop-in to the filter → fetch chain) and
records the run to `manifest.jsonl`. It does **not** rank or judge relevance
(US 26), fetch full text (`fetch-one`), or merge across sources (deferred).

## Phase-2 bake-off (evidence)

Ran both example queries through both adapters on a keyless machine (rule 06
phase 2 — characterize, don't crown by accuracy):

| Source | Query | Count | Abstract-present | Authors | Published | DOI | Latency |
| ------ | ----- | ----- | ---------------- | ------- | --------- | --- | ------- |
| arXiv | `sparse mixture-of-experts routing` | 25 | 25/25 | 25/25 | 25/25 | 0/25 | ~1.5 s |
| arXiv | `CRISPR base editing off-target effects` | 25 | 25/25 | 25/25 | 25/25 | 0/25 | ~2.5 s |
| s2 | either query | — | — | — | — | — | **429 rate-limited** |

**Verdict: arXiv is the default.** Keyless, reliable, 100 % abstract-present
(arXiv always carries a `<summary>`), full author/date metadata, ~1.5–2.5 s per
first page of 25. arXiv never carries a DOI (the abs `url` is the identifier).
Semantic Scholar's free tier **without an API key is unusable here** — every
call returned `429 Too Many Requests` (the shared keyless pool), which correctly
hit discover's `api-error` quarantine. S2's edge (a `tldr` pre-filter signal, and
better biomedical coverage than arXiv) only pays off once an `S2_API_KEY` is
supplied, so it stays an opt-in `--source s2`, not the default. There is no
relevance ground truth, so this characterizes; it does not rank by accuracy.

## Acceptance Criteria

1. Given a topic query and `--source arxiv`
   (e.g. `"sparse mixture-of-experts routing"`)
   - when discover searches arXiv and it answers with hits
     - then each hit is printed as one JSONL record carrying `title`, `authors`,
       `abstract`, `url`, `published`, and `source_id`, and a `discover` record is
       appended to `manifest.jsonl` (`stage: "discover"`) with `source`, `query`,
       and `result_count`
2. Given a topic query and `--source s2`
   (e.g. `"CRISPR base editing off-target effects"`)
   - when discover searches Semantic Scholar
     - then each hit is emitted in the **same** JSONL schema, including the `tldr`
       field when the record carries one (a deterministic pre-filter signal for
       US 26)
3. Given a returned hit that carries no abstract (some records lack one)
   - when discover emits it
     - then the record is still emitted with `abstract` null and an
       `abstract_present: false` flag — so US 26 can drop it cheaply — rather than
       dropped here (discovery casts wide; filtering is downstream)
4. Given a query that returns zero results, or the API errors / rate-limits
   - when discover cannot get candidates
     - then it quarantines to `manifest.jsonl` (`stage: "discover"`, with a
       **distinct** `reason` separating empty-result from api-error), and exits
       cleanly — never crashes
5. Given a `--source` that is not a known adapter (e.g. `--source pubmed`)
   - when discover looks it up
     - then it quarantines with a distinct reason (unknown source) without
       touching the network, mirroring the registry discipline of US 20/US 24

## Case handling (classify-then-dispatch)

discover classifies first on `--source`: a known adapter (`arxiv`, `s2`) → use it;
anything else → quarantine (unknown source) offline. The adapter issues the
search and maps the response into the common schema, encoding each API's fixed
quirks **once** (rule 02): arXiv's ~3 s inter-call delay and Atom parsing; Semantic
Scholar's field selection and `tldr`. **Then on the transport result**: hits →
emit JSONL; empty → quarantine (empty-result); HTTP error / rate-limit → quarantine
(api-error). No LLM is ever called to classify or rescue a record.

## Later stages (deferred)

- **Query both and merge.** This story does one source per run. A driver that
  fans a query across both adapters and merges + dedups the union (reusing US 14's
  DOI normalization) is composed from this step, deferred to keep each adapter
  simple.
- **Pagination / depth.** discover returns the API's first page of results. Deep
  paging for exhaustive recall is a later option, gated on the bake-off showing
  the first page is too shallow. See DEVLOG.
- **Re-runnable bake-off harness.** The phase-2 comparison is a one-time spike to
  pick the default source. Promoting it to its own re-runnable step (as the OCR
  bench US 19–23 did for models) is deferred until new sources make re-measuring
  worthwhile.
- **Date / type filters at the source.** Restricting to a date range or document
  type belongs to US 26's deterministic pass, not this wide-net entry.
