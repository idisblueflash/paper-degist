# US 31 Fan a topic across queries and sources, merge the union

As a *researcher opening a topic review*, i want *a driver that runs several
topic queries across several discover sources and emits one merged, deduplicated
candidate list*, so that *one command casts the whole net — instead of me running
`discover` once per (query, source) pair and hand-merging the JSONL*.

## Background

`discover` (US 25/27/29) deliberately does **one query against one source per
run**; its "Later stages" and the DEVLOG defer the fan-out/merge driver — this
story is that driver. It is pure composition: `discover-batch` calls the same
`discover` core once per (query, source) pair, so every per-pair behaviour
(adapter quirks, empty-result / api-error / missing-key quarantine, per-run
manifest rows) is inherited, not reimplemented. What this step adds is the
**batch discipline**:

- **Fan-out** over the cross product of queries × sources. A pair that
  quarantines (rate-limit, zero hits) takes out only itself; the batch finishes.
- **Politeness between calls.** arXiv's ~3 s etiquette constant
  (`ARXIV_MIN_INTERVAL`, encoded in US 25 *for this driver*) spaces consecutive
  arXiv calls; single calls and other sources pay no wait.
- **Merge + dedup** of the union. Two records are the same paper when their
  normalized DOIs match (US 14's `normalize_doi`, as US 26's dedup key reuses
  it), or — for DOI-less records like arXiv's — when they share the same
  `(source, source_id)`. First-seen wins, with one deterministic upgrade: a
  duplicate that **carries an abstract replaces a kept record that has none**
  (e.g. an OpenAlex record with a full abstract beats a bibliographic
  `scholar-author` stub), so the merged list keeps the richest copy for US 26.
  Every dropped duplicate leaves an auditable `filtered` manifest record.

The default sources are the **keyless pair** (`arxiv`, `openalex`) so the
command runs with zero setup; key-gated sources join via repeated `--source`.
The output is one merged JSONL candidate list — a drop-in to `abstract-filter`
(US 26), which still runs its own DOI dedup and so also handles any cross-batch
duplicates this step cannot see.

The scope is a **new driver step, `discover-batch`, over N queries and M
sources**. It does **not** add a new source adapter, rank or judge relevance
(US 26), fetch full text (`fetch-one`), or page beyond each source's first page
(US 25's pagination stays deferred).

## Acceptance Criteria

1. Given two topic queries (e.g. `"state space models for long sequences"` and
   `"linear attention transformers"`) and two sources (`arxiv`, `openalex`)
   - when discover-batch runs
     - then `discover` is invoked once per (query, source) pair — four runs —
       and the merged candidates are printed as one JSONL stream, with a
       `discover-batch` summary record appended to `manifest.jsonl` carrying the
       query count, the sources, and the merged `result_count`
2. Given two sources that return the same paper under one normalized DOI
   (e.g. `10.1016/j.neunet.2024.106789` from OpenAlex and
   `https://doi.org/10.1016/J.NEUNET.2024.106789` from S2)
   - when discover-batch merges the union
     - then only the first-seen record is emitted and the duplicate is dropped
       with a `filtered` manifest record (`stage: "discover-batch"`,
       `reason: dedup-doi`, naming what it duplicates)
3. Given one DOI-less paper returned by the **same** source for both queries
   (e.g. arXiv id `2405.12345v1` hit by two overlapping queries)
   - when discover-batch merges the union
     - then the second copy is dropped by its `(source, source_id)` key with a
       distinct `reason: dedup-source-id` — never emitted twice
4. Given a kept record with no abstract and a later duplicate of the same paper
   that carries one (e.g. a bibliographic `scholar-author` stub, then the
   OpenAlex record with the full abstract)
   - when discover-batch merges them
     - then the abstract-carrying duplicate **replaces** the stub (the merged
       list keeps the richest copy for US 26), and the replaced stub is the one
       recorded as filtered
5. Given one (query, source) pair that fails (the API rate-limits) while the
   other pairs return hits
   - when discover-batch runs
     - then the failing pair is quarantined by `discover`'s own api-error path,
       the surviving pairs' candidates are still merged and emitted, and the
       batch exits cleanly — never crashes
6. Given a batch whose every pair returns nothing (all quarantined or empty)
   - when discover-batch finishes with zero merged candidates
     - then it quarantines to `manifest.jsonl` (`stage: "discover-batch"`, a
       distinct `empty-batch` reason) and exits cleanly, mirroring `discover`'s
       empty-result discipline
7. Given a batch that calls the `arxiv` source more than once
   - when discover-batch issues consecutive arXiv calls
     - then it waits `ARXIV_MIN_INTERVAL` between them (the etiquette constant
       US 25 encoded for this driver) — and pays no wait before the first call
       or between other sources' calls

## Case handling (classify-then-dispatch)

discover-batch adds no new input classification of its own: each (query, source)
pair is dispatched to `discover`, whose registry/classify branches (unknown
source, missing-key, api-error, empty-result) already quarantine per pair —
`None` from a pair means "already quarantined, continue". The merge classifies
each candidate on its dedup key: a normalized DOI when extractable, else
`(source, source_id)`; a repeat key → drop (or upgrade-replace when the new copy
has the abstract and the kept one does not), each drop leaving a `filtered`
record. Zero merged survivors → quarantine (empty-batch). No LLM is ever called.

## Later stages (deferred)

- **Title-based cross-source dedup.** A DOI-less arXiv record and the same
  paper's OpenAlex record cannot be matched by DOI or source id; fuzzy title
  matching is a later refinement (US 26's embedding pass tends to keep both,
  which is safe over-recall).
- **Per-source query templating.** One query string is sent verbatim to every
  source; per-source fielded queries (US 25's deferred fielded arXiv search)
  would slot in at the adapter, not here.
- **Deep pagination.** Inherited from US 25 — each pair still returns the
  source's first page.
