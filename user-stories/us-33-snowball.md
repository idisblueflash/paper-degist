# US 33 Snowball from a seed paper via OpenAlex

As a *researcher expanding from a known paper*, i want *to fetch the papers
that a seed cites and the papers that cite it — from OpenAlex — so that* I can
discover highly related work that keyword search misses (directly linked by the
authors of the seed).

## Background

Keyword discovery (`discover`, US 25/29/31) finds papers that share vocabulary
with a query string. Citation snowballing finds papers that **share a link** with
a specific seed: every paper in the reference list was judged relevant by the
seed's authors; every paper in the citer list was influenced by the seed. These
two sets are disjoint from keyword search and complement it: a paper with
idiosyncratic terminology (Transformers, Mamba, SSM) may never surface in
keyword search but appears immediately in the seed's reference or citer list.

OpenAlex exposes both directions for free (keyless, polite-pool `mailto`):

- **References** (`referenced_works`): the list of Works the seed cites.
  The seed's Work record carries an array of OpenAlex Work IDs; the step
  batch-fetches them.
- **Citers** (`cites:{id}` filter): the paginated list of Works that cite
  the seed. Fetched page by page up to `--max-citers`.

Output is the same discover-shaped JSONL as `discover --source openalex` so
the candidates feed directly into `abstract-filter`, `rank-cited`, or
`fetch-one` without any transform.

## Acceptance Criteria

1. Given a seed **DOI** (or a URL containing a DOI like
   `https://doi.org/10.48550/arxiv.1706.03762`), when `snowball` runs
   - then the seed is resolved to an OpenAlex Work record, and the step
     emits each **referenced work** as a candidate (title, url, doi,
     source="openalex", cited_by when available, abstract/tldr when
     available)
2. Given a seed and `--direction citers`, when `snowball` runs
   - then the step emits papers that **cite** the seed (using the
     `cites:{openalex_id}` filter), not the seed's own references
3. Given a seed and `--direction both` (the default), when `snowball` runs
   - then both the seed's references and its citers are emitted, in that
     order (refs first, citers second), with no duplicate records (same
     OpenAlex ID appears only once)
4. Given `--max-refs N`, when `snowball` fetches the reference list
   - then at most N reference candidates are emitted; if the seed cites
     more than N papers the rest are silently capped (the spec is a budget,
     not a quarantine — no manifest row for capped extras)
5. Given a seed that cannot be resolved (DOI not found, API error, no
   OpenAlex record), when `snowball` tries to fetch it
   - then the seed is quarantined (`stage: "snowball"`,
     `reason: "seed-not-found"` or `"api-error"`), nothing is emitted,
     and the step exits cleanly (exit 0)
6. Given an OpenAlex Work in the reference or citer list that lacks a
   landing URL or DOI (an opaque Work with no ``doi`` and no
   ``primary_location.landing_page_url``), when `snowball` processes it
   - then that Work is skipped with a `filtered` manifest row
     (`stage: "snowball"`, `reason: "no-url"`) and the rest of the batch
     still emits

## Case handling (classify-then-dispatch)

- Seed has a recognizable DOI → resolve via `_openalex.fetch_work_by_doi`.
- Seed is an OpenAlex Work URL (`https://openalex.org/W…`) → resolve
  directly via `_openalex._get`.
- Seed cannot be resolved (HTTP 404 / other error) → quarantine with
  `seed-not-found` / `api-error`.
- Each resolved Work in the output: has a usable URL → emit; no URL, no
  DOI → filtered with `no-url`. Never crash, never call an LLM (rule 02).

## Arguments and options

```
uv run snowball <seed>
              [--direction refs|citers|both]  (default: both)
              [--max-refs N]                  (default: 200)
              [--max-citers N]                (default: 200)
              [--email EMAIL]                 (polite pool)
              [--manifest manifest.jsonl]
```

## Later stages (deferred)

- **Recursive snowball.** Running `snowball` on every emitted candidate to
  depth-2 is a later refinement; today one hop from the seed is enough.
- **SerpAPI / Semantic Scholar citation lanes.** OpenAlex covers most
  CS/ML papers; a follow-up story adds s2's citation API for the
  arXiv-only papers that OpenAlex misses.
- **Dedup across prior discover runs.** Passing the union through
  `dedup-inputs` after snowball is the composition pattern; this step does
  not absorb dedup responsibility.
