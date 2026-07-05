# US 30 Expand candidates along the citation graph (OpenAlex)

As a *researcher who already has one on-topic seed paper and wants the papers
around it — the work it builds on and the work that builds on it*, i want *a step
that takes a seed (DOI or OpenAlex id) and emits its references and its citing
works as candidates in the same schema*, so that *I get high-precision,
graph-based recall that keyword search can't reach, instead of only flat topic
queries*.

## Background

`discover` (US 25/27/29) casts a **keyword** net: it finds papers whose *text*
matches a query. But the papers most relevant to a seed are often reachable only
through the **citation graph** — the seed's own references (backward / what it
builds on) and the works that cite the seed (forward / what builds on it). This is
classic "snowball" recall, and it is high-precision: an author's chosen references
and citers are a curated signal that no keyword query reproduces.

OpenAlex exposes both directions on the Works API, keyless (US 29's polite pool):

- **Backward** — the seed work's `referenced_works` is a list of OpenAlex ids.
  The step hydrates them into full records (batched via
  `filter=openalex_id:W…|W…`), so each reference arrives with title / abstract /
  DOI like a discover hit.
- **Forward** — works citing the seed come from `filter=cites:W…`, paginated.

The scope is a **new step, `expand-citations`, over one seed and a `--direction`
(`backward` | `forward` | `both`)**. It reuses US 29's OpenAlex adapter machinery
(the same `abstract_inverted_index` reconstruction and `open_access`→`pdf_url`
mapping) and emits the **same common candidate schema** as `discover`, so its
output is a drop-in to US 26's `abstract-filter` → `fetch-one` chain. Each emitted
record additionally carries its provenance: `seed` (the seed id/DOI) and
`relation` (`references` or `cites`). It is deliberately **one hop** — multi-hop
snowballing is deferred. It does **not** filter for relevance (US 26), fetch full
text (`fetch-one`), or rank.

## Acceptance Criteria

1. Given a seed DOI or OpenAlex id and `--direction backward`
   (e.g. `10.1038/nature14539`)
   - when expand-citations resolves the seed and reads its `referenced_works`
     - then each referenced work is hydrated and emitted in US 25's common schema
       (with US 29's `doi`/`pdf_url`/`oa_status` fields), plus `seed` and
       `relation: "references"`, and an `expand-citations` record is appended to
       `manifest.jsonl` (`stage: "expand-citations"`) with `seed`, `direction`,
       and `result_count`
2. Given a seed and `--direction forward`
   (e.g. OpenAlex id `W2963403868`)
   - when expand-citations queries `filter=cites:<seed>`
     - then each citing work is emitted in the same schema with
       `relation: "cites"`
3. Given a seed and `--direction both`
   - when expand-citations runs both directions
     - then references and citers are emitted together, the seed itself is never
       emitted as its own candidate (self-drop), and a record appearing in both
       directions is emitted once (dedup by normalized DOI, reusing US 14)
4. Given a seed whose DOI/id OpenAlex cannot resolve (unknown work, 404)
   - when expand-citations looks it up
     - then it quarantines to `manifest.jsonl` (`stage: "expand-citations"`) with
       a **distinct** reason (seed-not-found) and exits cleanly — never crashes
5. Given a resolvable seed that has **no** references (a `backward` run on a work
   with an empty `referenced_works`) or **no** citers yet (a `forward` run)
   - when expand-citations finds the graph empty in that direction
     - then it quarantines with a **distinct** reason (empty-result, separate from
       seed-not-found) — the seed exists but the graph is empty, not an error
6. Given an unknown `--direction` (e.g. `--direction sideways`), or the OpenAlex
   lookup / hydration errors (network, 429, 5xx)
   - when expand-citations classifies or calls out
     - then an unknown direction quarantines **offline** (unknown-direction,
       mirroring US 25's unknown-source), and a transport error quarantines
       (api-error) and finishes cleanly — never crashes, never calls an LLM

## Case handling (classify-then-dispatch)

expand-citations classifies first on `--direction` (`backward` / `forward` /
`both` known; anything else → quarantine unknown-direction, offline). Then it
resolves the seed: a DOI or OpenAlex id → `GET /works/<id>`; a 404 →
quarantine (seed-not-found). Dispatch by direction: **backward** reads
`referenced_works` and hydrates the ids in batches (`filter=openalex_id:…`);
**forward** pages `filter=cites:<seed>`; **both** unions them with a DOI-keyed
dedup (US 14) and a self-drop of the seed. Reconstructing abstracts and mapping OA
locations reuse US 29's adapter (rule 02 — encoded once). **On the result**: hits
→ emit JSONL; an empty direction → quarantine (empty-result); a transport error →
quarantine (api-error). No LLM is ever called to classify or rescue a record.

## Later stages (deferred)

- **Multi-hop / depth.** This step is one hop from the seed. A `--depth N` driver
  that re-feeds emitted candidates as new seeds (with a visited-set to avoid
  cycles and a cap to bound the fan-out) is composed from this step, deferred to
  keep one hop simple and cheap.
- **Multiple seeds.** One seed per run; a driver fanning over a seed list and
  merging + deduping the union (reusing US 14) is a later composition.
- **Co-citation / bibliographic coupling.** Ranking candidates by how many seeds
  they share references with (or are cited with) is a precision signal for US 26,
  not this wide-net expander.
- **Citation-count sort.** OpenAlex can `sort=cited_by_count:desc`; ordering the
  forward set by influence belongs to the downstream ranker (US 26), not here.
