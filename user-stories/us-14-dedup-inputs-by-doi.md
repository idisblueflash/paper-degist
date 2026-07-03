# US 14 Dedup inputs by normalized DOI before fetching

As a *researcher assembling a list of papers to fetch*, i want *a step that
collapses inputs pointing at the same DOI down to one*, so that *a paper i
reached three ways — a publisher URL, a DOI i looked up by hand, and its
`doi.org` link — is fetched once, not three times*.

One paper is routinely reached by several inputs: a bare DOI
(`10.1016/j.learninstruc.2007.02.008`), its resolvable link
(`https://doi.org/10.1016/j.learninstruc.2007.02.008`), and a publisher URL that
embeds the same DOI in its path. These are the *same paper*, but nothing today
recognizes it — each is fetched and recorded independently. This story adds a
standalone filter step, `dedup-inputs`, that runs **before** fetch-one: it reads
a list of inputs, canonicalizes any DOI it can read out of each one, and keeps
only the first input for each distinct DOI, dropping the rest.

The canonical key is a **normalized DOI**: strip the scheme and any
`doi.org`/`dx.doi.org` prefix, lowercase (DOIs are case-insensitive), so
`https://doi.org/10.1177/002221949002300203` and `10.1177/002221949002300203`
fold to one key. The step is a **pure, offline** transform — it reads the DOI
that is already visible in the input string and makes **no network call and no
LLM call** (rule 02). It sits in the pipeline as `parse-url → dedup-inputs →
fetch-one`.

The scope is a **new filter step over a list**, keyed on DOIs extractable from
the input text. It does **not** resolve a DOI for an input that hides it (a
PubMed or ScienceDirect URL exposes no DOI without a lookup — that is
`resolve-oa`'s job); it does not rewrite inputs to canonical form (it prints the
*original* kept input so fetch-one still works); and it does not dedup against
prior runs' history (a durable seen-ledger is a separate, deferred design).

## Acceptance Criteria

1. Given a list containing the same DOI in two forms — a `doi.org` link and the
   bare DOI (e.g. `https://doi.org/10.1016/j.learninstruc.2007.02.008` then
   `10.1016/j.learninstruc.2007.02.008`)
   - when dedup-inputs processes the list
     - then only the **first** input is printed to stdout; the second is dropped
       as a duplicate of the same normalized DOI
2. Given a publisher URL that embeds a DOI in its path
   (e.g. `https://journals.sagepub.com/doi/10.1177/002221949002300203`) followed
   later by that bare DOI
   - when dedup-inputs extracts the embedded DOI from each
     - then the two are recognized as one paper and only the first is kept
3. Given an input carrying **no** extractable DOI
   (e.g. `https://pubmed.ncbi.nlm.nih.gov/2303742/`, whose DOI is not in the URL)
   - when dedup-inputs cannot read a DOI from it
     - then the input passes through unchanged — it is never dropped, because the
       step cannot prove it duplicates anything without a network lookup
4. Given a dropped duplicate
   - then a `duplicate` record is appended to `manifest.jsonl`
     (`stage: "dedup-inputs"`, the dropped input, its normalized `doi`, and the
     kept input it duplicates) — so the collapse is auditable, never silent, and
     the manifest stays append-only
5. Given the surviving inputs
   - then they are printed one per line to stdout in first-seen order, so the
     step is a drop-in filter between `parse-url` and `fetch-one`

## Case handling (classify-then-dispatch)

dedup-inputs classifies each input on whether a DOI is extractable from its
text: a `doi.org`/`dx.doi.org` link, a bare `10.\d+/…` DOI, or a URL path that
embeds a `10.\d+/…` segment all yield a normalized DOI key; anything else has no
key. It then dispatches on the key: **no key** → pass through (cannot dedup
offline); **first sight of a key** → keep and remember the key; **repeat key** →
drop and note the duplicate in the manifest. Normalization (scheme/prefix strip,
lowercase) is a pure string transform, so the whole step runs offline and
deterministically.

## Later stages (deferred)

- **Dedup across runs (seen-ledger).** This step dedups *within one input list*.
  A durable ledger of DOIs already handled in prior runs — so a paper fetched
  last week is skipped today — is the seen-ledger design considered and not
  chosen here; it belongs with the stages that *learn* a DOI (fetch-one,
  resolve-oa), not this up-front filter. See DEVLOG.
- **Dedup DOI-less inputs by resolving first.** A PubMed/publisher URL that hides
  its DOI can only be deduped after resolve-oa recovers the DOI. Running
  resolve-oa to unmask DOIs before dedup would catch these, but couples this
  offline filter to a network stage — deferred to keep dedup-inputs pure.
- **Consolidated manifest view.** A read-side report grouping the append-only
  manifest by DOI (US 11's deferred "consolidated view") is complementary: this
  story *prevents* duplicate fetches; that one *shows* a paper's whole history.
