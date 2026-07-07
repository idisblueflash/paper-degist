# US 34 Fill missing abstracts for candidates by DOI via OpenAlex

As a *researcher running abstract-filter after snowball*, i want *candidates
that lack an abstract to be enriched from OpenAlex by DOI*, so that
`abstract-filter` can score them instead of dropping them for missing text.

## Background

`snowball` (US 33) emits reference/citer candidates that often lack an
`abstract` field: OpenAlex's `referenced_works` array carries only Work IDs,
and even when full Work records are fetched the `abstract_inverted_index`
field requires reconstruction. `discover --source arxiv` sometimes returns
a candidate with a `tldr` but no full abstract. `abstract-filter` (US 26)
drops a candidate with `abstract_present: false` as `"no-abstract"` — so
a candidate that could be scored is silently lost.

This step fills the gap: for each candidate whose `abstract` is absent (or
`abstract_present: false`), it looks the Work up by DOI on OpenAlex and
reconstructs the abstract from `abstract_inverted_index`. Candidates already
carrying an abstract pass through unchanged. Candidates without a DOI or
whose DOI OpenAlex does not recognise are quarantined (`stage:
"enrich-abstract"`, `reason: "no-doi"` / `"doi-not-found"`) — never dropped
silently.

The step is **additive**: it only fills `abstract` and `abstract_present`;
all other fields pass through unchanged. The output is the same JSONL shape
as the input — a drop-in before `abstract-filter`.

## Acceptance Criteria

1. Given a candidate with `abstract_present: false` and a usable `doi`,
   when `enrich-abstract` runs
   - then the candidate is emitted with a reconstructed `abstract` and
     `abstract_present: true`, all other fields unchanged
2. Given a candidate that **already has** `abstract_present: true`,
   when `enrich-abstract` runs
   - then the candidate passes through unchanged (no OpenAlex call made)
3. Given a candidate with `abstract_present: false` and **no `doi`**,
   when `enrich-abstract` runs
   - then the candidate is quarantined (`stage: "enrich-abstract"`,
     `reason: "no-doi"`) and nothing is emitted for it; the rest continue
4. Given a candidate whose DOI is not found in OpenAlex (404 / empty result),
   when `enrich-abstract` fetches it
   - then the candidate is quarantined (`stage: "enrich-abstract"`,
     `reason: "doi-not-found"`) and nothing is emitted for it; the rest
     continue
5. Given a candidate whose DOI resolves to an OpenAlex Work but the Work
   carries no `abstract_inverted_index` (no abstract on record),
   when `enrich-abstract` processes it
   - then the candidate is quarantined (`stage: "enrich-abstract"`,
     `reason: "no-abstract-on-record"`) and nothing is emitted for it;
     the rest continue
6. Given a non-JSON-object input line (truncated pipe, garbage line),
   when `enrich-abstract` parses the input
   - then the line is quarantined (`stage: "enrich-abstract"`, a distinct
     reason naming the line) and the well-formed candidates still run —
     never crashes

## Abstract reconstruction

OpenAlex's `abstract_inverted_index` is a dict mapping each word to the list
of positions it occupies in the abstract:
`{"The": [0], "Transformer": [1], ...}`. Reconstruction: sort by position,
join with spaces. An empty or absent dict → no abstract available (AC5).

## Case handling (classify-then-dispatch)

- Candidate has `abstract_present: true` → pass through (no API call).
- Candidate has no doi → quarantine `no-doi`.
- DOI not found on OpenAlex → quarantine `doi-not-found`.
- Work has `abstract_inverted_index` → reconstruct and emit.
- Work has no `abstract_inverted_index` → quarantine `no-abstract-on-record`.
- Unparseable input line → quarantine via `load_candidates` (rule 02).

## Arguments and options

```
uv run enrich-abstract [candidates.jsonl]
                       [--email EMAIL]               (polite pool)
                       [--manifest manifest.jsonl]
```

## Later stages (deferred)

- **Semantic Scholar abstract lane.** A candidate without a DOI can be
  looked up by title on S2; a follow-up story adds that lane.
- **arXiv abstract API.** arXiv exposes abstracts through its own API by
  arXiv ID; a follow-up adds that as a third enrichment source.
- **TLDR generation.** For a candidate whose abstract is genuinely absent on
  all APIs, a TLDR from an LLM is a follow-up (never in the step loop —
  queued to the manifest, invoked once by the operator).
