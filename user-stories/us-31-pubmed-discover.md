# US 31 Discover candidates via PubMed (keyless, biomedical, full abstracts)

As a *researcher whose topic is biomedical (clinical, molecular, pharma) and
reaches past arXiv's CS/physics lean*, i want *`discover` to search PubMed and
emit each article in the same candidate schema — with its full abstract and DOI —
so that *I get authoritative biomedical coverage keyless, instead of arXiv missing
the field or Semantic Scholar 429-ing without a key*.

## Background

US 25 built `discover` with a `--source` **registry** (arXiv, s2), US 27 added
the SerpAPI Scholar adapters, and US 29 added OpenAlex. This story adds one more
registry adapter — **`--source pubmed`** — over NCBI's **E-utilities**, chosen to
cover the biomedical literature the existing sources under-serve (arXiv is
CS/physics-leaning; OpenAlex is broad but not MEDLINE-curated).

A phase-2 PoC confirmed the shape against the **live, keyless** API:

- PubMed is a **two-step** adapter, encoded once (rule 02):
  1. `esearch.fcgi?db=pubmed&term=<query>&retmode=json` → a list of **PMIDs**
     (the PoC's CRISPR query reported `count: 2610` — real recall).
  2. `efetch.fcgi?db=pubmed&id=<pmid,…>&retmode=xml` → the **full records**,
     batching the page of PMIDs into one call.
- The efetch XML maps cleanly to US 25's **common schema**: `ArticleTitle` →
  `title`; `Abstract/AbstractText` → `abstract` (the PoC pulled a **full** 1704-char
  abstract, not a fragment); `Author/{ForeName,LastName}` → `authors`;
  `PubDate/Year` → `published`; the PMID → `source_id`; and
  `ArticleId[IdType="doi"]` → `doi` (PoC: `10.1002/bies.70160`).
- **No direct PDF.** PubMed indexes metadata, not files — there is no `pdf_url`
  like US 27/US 29 carry. But the DOI is present on most records, so a PubMed hit
  feeds `resolve-oa` (US 9/10) directly. (The open-access subset also carries a
  PMC id in `ArticleId`; harvesting the PMC OA PDF is a deferred stage below.)

Both endpoints are **keyless**. NCBI's etiquette is a rate cap — **3 req/s** with
no key, **10 req/s** with a free `NCBI_API_KEY` (env, passed as `api_key=` when
set); the key only *raises* the cap, so its absence never quarantines. It stays
coarse and high-recall (US 25's contract); US 26 narrows.

## Phase-2 bake-off (to be measured)

Per rule 06 phase 2, before shipping run the two biomedical example queries below
through the `pubmed` adapter **and the US 25 arXiv default on the same queries**,
then record the deterministic signals here (characterize, don't crown by accuracy —
there is no relevance ground truth):

| Source | Query | Count | Abstract-present | DOI | Latency |
| ------ | ----- | ----- | ---------------- | --- | ------- |
| pubmed | `tirzepatide cardiovascular outcomes trial` | _tbd_ | _tbd_ | _tbd_ | _tbd_ |
| pubmed | `single-cell RNA-seq tumor microenvironment` | _tbd_ | _tbd_ | _tbd_ | _tbd_ |
| arXiv (US 25) | same two | _tbd_ | _tbd_ | — | _tbd_ |

The claim to test is that pubmed raises **abstract-present** and **DOI-present**
rates on biomedical queries where arXiv returns little or nothing at comparable
recall; whether it is preferred over arXiv for biomedical topics is settled by
this evidence, not asserted here.

## Acceptance Criteria

1. Given a topic query and `--source pubmed`
   (e.g. `"tirzepatide cardiovascular outcomes trial"`)
   - when discover runs esearch then efetch and it answers with hits
     - then each article is emitted in US 25's common JSONL schema — `title`,
       `authors`, `abstract`, `doi`, `url`, `published`, `source_id` (the PMID) —
       and a `discover` record is appended to `manifest.jsonl`
       (`stage: "discover"`, `source: "pubmed"`) with `query` and `result_count`
2. Given hits from esearch
   - when discover fetches their bodies
     - then `abstract` is the **full** text reconstructed from efetch's
       `AbstractText` element(s) — not the esearch summary — joining multi-section
       abstracts (Background/Methods/…) in order
3. Given an article whose efetch record carries no `AbstractText` (some PubMed
   records have none)
   - when discover emits it
     - then the record is emitted with `abstract` null and
       `abstract_present: false` (US 25 AC3) — dropped downstream, not here
4. Given an article whose efetch record carries an `ArticleId[IdType="doi"]`
   - when discover emits it
     - then the record carries that `doi` (feeding `resolve-oa`); a record with no
       DOI is still emitted (PMID `source_id` is always present), without a `doi`,
       and **no** `pdf_url` (PubMed indexes metadata, not files)
5. Given a query that returns zero results, or E-utilities errors / rate-limits
   (a 4xx/5xx, or a 429 for exceeding the cap)
   - when discover cannot get candidates
     - then it quarantines to `manifest.jsonl` (`stage: "discover"`) with a
       **distinct** `reason` separating empty-result from api-error, and exits
       cleanly — never crashes, never calls an LLM

## Case handling (classify-then-dispatch)

discover classifies first on `--source` (US 25): `pubmed` is a new registry
adapter; anything else still quarantines (unknown source) offline. The adapter
runs the fixed two-step E-utilities flow **once** (rule 02) — `esearch` for PMIDs,
then a single batched `efetch` for the page — parsing the efetch XML into the
common schema: `AbstractText` reconstruction (multi-section join, null →
`abstract_present: false`), `ArticleId`→`doi`, `PubDate/Year`→`published`. NCBI's
rate cap is honored with a politeness delay (raised when `NCBI_API_KEY` is set — an
etiquette default, **not** a required key, so its absence never quarantines).
**Then on the transport result**: hits → emit JSONL (no `pdf_url` — PubMed has no
file); zero PMIDs → quarantine (empty-result); an HTTP error / 429 → quarantine
(api-error). No LLM is ever called to classify or rescue a record.

## Later stages (deferred)

- **PMC open-access PDFs.** The OA subset carries a PMC id in efetch's
  `ArticleId`; resolving it to the PMC OA PDF (the PMC OA service) would give a
  `pdf_url` like US 27/US 29, letting a PubMed hit short-circuit `resolve-oa`.
  Deferred — the DOI already routes closed items through US 9/10.
- **MeSH / field filters at the source.** PubMed's `term=` supports MeSH tags and
  field qualifiers (`[MeSH Terms]`, date ranges). Per US 25's split that narrowing
  belongs to US 26, so this adapter uses a plain topic `term=` wide-net.
- **Pagination / depth.** discover returns the first page (`retmax`); deep paging
  via `retstart` for exhaustive recall is gated (like US 25) on the first page
  proving too shallow.
- **Embase (Elsevier) as a key-gated sibling.** A PoC confirmed Embase is reachable
  at `api.elsevier.com/content/embase` but returns `401 Invalid API Key` — it needs
  an Elsevier API key **plus a paid institutional entitlement**, so it cannot be a
  keyless source. It would be an opt-in `--source embase` (key-gated, quarantining
  offline when the key/entitlement is missing, mirroring `--source s2`), deferred
  until institutional access exists. See DEVLOG.
