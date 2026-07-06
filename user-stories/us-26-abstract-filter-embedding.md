# US 26 Filter candidates by abstract similarity

As a *researcher triaging a wide-net candidate list*, i want *a step that drops
the obviously-irrelevant candidates and ranks the rest by how close their
abstract is to my topic*, so that *only a short, on-topic shortlist reaches
fetch-one instead of every keyword hit*.

## Background

`discover` (US 25) casts a wide net and over-returns. This story narrows it in
**two passes, and no LLM** — the criteria-aware LLM judge on the ambiguous middle
is explicitly a later stage (deferred below). The two passes are:

1. **Deterministic** (pure, offline): dedup candidates by normalized DOI —
   reusing US 14's scheme/prefix-strip, lowercase normalization — and drop any
   candidate US 25 flagged `abstract_present: false`, since a hit with no abstract
   is dead weight for a similarity filter. This throws out the cheap junk before
   spending a single embedding call.
2. **Embedding similarity** (offline, deterministic): embed the `--topic` query
   once as a query and each surviving abstract as a document via `embed-text`
   (US 24), take the **cosine similarity**, and cut everything below a threshold.
   The threshold is a constant **measured against a real sample** (rule 06
   phase 2), not guessed — the same discipline as the HTML-density and OCR
   constants.

Similarity measures "about the same area," not "matches my exact intent" — so this
filter is a high-recall *shortlister*, and the finer intent judgment (survey vs
primary, method X vs Y) is left to the deferred LLM pass. The output is a **ranked
JSONL shortlist** with each candidate's score, a drop-in to `fetch-one`.

The scope is a **new filter step, `abstract-filter`, over a candidate JSONL and a
topic**. It does **not** call an LLM, resolve intent beyond topical closeness, or
fetch anything.

## Threshold calibration (evidence)

Measured the cosine cutoff against a real sample (rule 06 phase 2 — like the
HTML-density and OCR constants, not guessed). Embedded the topic
`"contrastive learning for speech representations"` once as a query and each
candidate abstract as a document through the live `nomic-embed-text-v1.5`
(the same model + `search_query:`/`search_document:` prefixes the pipeline
uses), and scored cosine on two real arXiv candidate sets: 20 hits for the
on-topic query, 12 for an unrelated `"CRISPR base editing off-target effects"`
query.

| Set                          | n  | min    | max    | mean   |
| ---------------------------- | -- | ------ | ------ | ------ |
| on-topic (speech contrastive)| 20 | 0.6408 | 0.8326 | 0.7479 |
| off-topic (CRISPR editing)   | 12 | 0.4959 | 0.6337 | 0.5841 |

The two sets separate cleanly: every off-topic (CRISPR) candidate scores
**≤ 0.6337**, while the clearly-on-topic speech papers cluster **≥ 0.72**. The
only entries in the gap are two wide-net arXiv hits that are *not* about speech
at all — "Transformation Properties of Learned Visual Representations" (0.6682)
and "AtomSurf: Surface Representation for … Protein Structures" (0.6408) — noise
the coarse `all:` net returned. **`DEFAULT_THRESHOLD = 0.65`** sits just above
the entire off-topic cluster (0.6337) with margin: it drops 100 % of the
deliberately-off-topic set and keeps 100 % of the clearly-on-topic speech
papers, a recall-biased shortlister (the finer intent judgment is the deferred
LLM pass). A curated slice of this real corpus is saved at
`src/tests/samples/abstract-filter-speech-candidates.jsonl`. Per-topic
auto-calibration (the cut is topic-dependent) is deferred — see below and DEVLOG.

## Acceptance Criteria

1. Given a candidate JSONL where two candidates share a normalized DOI and one
   candidate is flagged `abstract_present: false`
   - when abstract-filter runs its **deterministic pass first**
     - then the duplicate and the abstract-less candidate are dropped **before any
       embedding call**, each with a `filtered` record in `manifest.jsonl`
       (`stage: "abstract-filter"`, a `reason` separating dedup-doi from
       no-abstract)
2. Given a surviving candidate whose abstract is topically close to the `--topic`
   query (cosine ≥ threshold), e.g. topic
   `"contrastive learning for speech representations"`
   - when abstract-filter scores it via `embed-text`
     - then it is kept and emitted with its `similarity` score attached
3. Given a surviving candidate whose cosine similarity is **below** the threshold
   - when abstract-filter scores it
     - then it is dropped with a `filtered` record (`reason: below-threshold` and
       its `similarity`) — auditable, never silent
4. Given the kept candidates
   - when abstract-filter emits them
     - then they are printed as JSONL one per line, ordered by **descending
       similarity** with the score attached, so the shortlist is a ranked drop-in
       to `fetch-one`
5. Given `embed-text` quarantines one abstract mid-run (server down)
   - when abstract-filter cannot obtain that candidate's vector
     - then only that candidate is quarantined (`stage: "abstract-filter"`,
       `reason` naming embed-unavailable) and the rest of the batch still
       completes — never crashes, never drops it silently

## Case handling (classify-then-dispatch)

abstract-filter runs two layers. **Deterministic first**: classify each candidate
on its normalized DOI (repeat key → drop as duplicate) and on `abstract_present`
(false → drop as no-abstract); both are pure string checks, so this pass is
offline and free. **Embedding second**: the query is embedded once; each surviving
abstract is embedded via `embed-text` and scored by cosine against the threshold —
`≥` keep, `<` drop (below-threshold). An abstract whose embedding call quarantines
propagates as a per-candidate quarantine, and the batch continues. No LLM is ever
called — the intent-aware judge is a separate, later story.

## Later stages (deferred)

- **LLM judge on the ambiguous middle.** The step 3 we set aside: a criteria-aware
  keep/drop with a reason, run **only** on the band of candidates near the
  threshold, applying inclusion/exclusion rules (primary-only, method, population)
  that similarity blurs. A distinct story so this one stays LLM-free.
- **Reference-paper relevance.** Defining the target by an exemplar paper
  (`--like exemplar.json`, embed it as the query) instead of a `--topic` string is
  a nicer UX for some users; deferred as an alternate input mode.
- **Merged multi-source input.** When US 25's deferred "query both and merge"
  lands, this filter consumes the merged union; the dedup pass already handles the
  cross-source duplicates.
- **Per-topic threshold calibration.** One global threshold is measured against a
  sample; auto-calibrating it per topic (the cut is topic-dependent) is a later
  refinement. See DEVLOG.
