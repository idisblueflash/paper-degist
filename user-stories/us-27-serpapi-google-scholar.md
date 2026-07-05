# US 27 Discover candidates via SerpAPI Google Scholar (topic + author)

As a *researcher whose topic reaches past arXiv/S2 (older papers, other fields,
or a specific author's body of work)*, i want *`discover` to search Google
Scholar through SerpAPI — both by topic and by author id — and emit each hit in
the same candidate schema, carrying a **direct PDF link** when Scholar has one*,
so that *I get broad Scholar coverage and a fetchable file up front, instead of
being limited to arXiv/S2 and then resolving open access separately*.

## Background

US 25 built `discover` with a `--source` **registry** (arXiv, s2) over one query
per run, and its "Later stages" name new sources as one adapter entry each. This
story adds **two SerpAPI Google Scholar adapters** to that registry (a
phase-2 PoC characterized both against a real key):

- **`--source scholar`** — a **topic** query through SerpAPI's
  `google_scholar` (organic) engine. Each `organic_results` item carries a
  `snippet` (an abstract **fragment**, with `…` ellipses — *not* the full
  abstract), an `inline_links.cited_by.total` count, and — when Scholar has an
  open copy — a `resources[]` entry with `file_format` (`PDF`/`HTML`) and a
  `link`. That link is directly fetchable by `fetch-one`, which is this story's
  edge over arXiv/s2 (it can short-circuit `resolve-oa` for an open PDF).
- **`--source scholar-author`** — an **author id** through SerpAPI's
  `google_scholar_author` engine. Each `articles` item is **bibliographic only**
  — `title`, `link`, `citation_id`, `authors`, `publication`, `cited_by`,
  `year` — with **no abstract and no PDF** (confirmed live on a real profile).
  It lists an author's body of work; per-paper abstract/PDF enrichment (a
  follow-up organic lookup per title) is a deferred N+1 stage.

Both engines are one SerpAPI endpoint (`https://serpapi.com/search.json`,
`engine=…`) and **require an API key** — `SERPAPI_API_KEY` (env, already
templated in `.env.example`) or `--serpapi-key`. Both map into US 25's **common
schema**, extended with `pdf_url` and `cited_by` when the record carries them.
It stays coarse and high-recall (US 25's contract); US 26 narrows.

SerpAPI's organic ranking is **fuzzy** — a topic/title query can return a
loosely-related top hit (the PoC's `"Attention is all you need"` topped with
*"The psychology of attention"*), so a title-match check (reuse `resolve_oa`'s
`_title_overlap`) is a **deferred** precision guard, not a wide-net requirement.

## Acceptance Criteria

1. Given a topic query and `--source scholar` with a SerpAPI key
   (e.g. `"retrieval-augmented generation for code"`)
   - when discover searches SerpAPI's Google Scholar organic engine and it
     answers with hits
     - then each hit is emitted in US 25's common JSONL schema, with `abstract`
       set to the Scholar `snippet` (fragment), and a `discover` record is
       appended to `manifest.jsonl` (`stage: "discover"`, `source: "scholar"`)
       with `query` and `result_count`
2. Given a `scholar` hit whose `resources[]` carries an open `file_format: "PDF"`
   entry (e.g. an arXiv/institutional copy)
   - when discover emits it
     - then the record carries a `pdf_url` (the resource `link`) — directly
       fetchable by `fetch-one` — and a `cited_by` count when present; a hit
       with no open resource is still emitted, without `pdf_url`
3. Given an author id and `--source scholar-author` with a SerpAPI key
   (e.g. `"JicYPdAAAAAJ"`)
   - when discover searches SerpAPI's Google Scholar author engine
     - then each of the author's `articles` is emitted in the same schema —
       `title`, `authors`, `url` (the citation `link`), `source_id` (the
       `citation_id`), `published` (the `year`), `cited_by` — with `abstract`
       null and `abstract_present: false` (the author engine carries none), and
       **no** `pdf_url`
4. Given a `scholar`/`scholar-author` source but **no** SerpAPI key (neither
   `--serpapi-key` nor `SERPAPI_API_KEY`)
   - when discover looks up the source
     - then it quarantines with a **distinct** reason (missing SerpAPI key)
       **without touching the network**, mirroring the offline-classify
       discipline of the unknown-source branch (US 25 AC5)
5. Given a query that returns zero results, or SerpAPI errors / rate-limits / a
   bad key (a 401/429, or a 200 whose body carries an `error` field)
   - when discover cannot get candidates
     - then it quarantines to `manifest.jsonl` (`stage: "discover"`) with a
       **distinct** `reason` separating empty-result from api-error, and exits
       cleanly — never crashes, never calls an LLM

## Case handling (classify-then-dispatch)

discover classifies first on `--source` (US 25): `scholar` and `scholar-author`
are two new registry adapters; anything else still quarantines (unknown source)
offline. **Before the network**, a scholar source with no API key quarantines
(missing key) — the key is deterministic input, checked offline like the source
name. Each adapter then issues its SerpAPI call and maps the engine's response
into the common schema, encoding each engine's fixed shape **once** (rule 02):
`scholar`'s `snippet`/`resources[]`/`cited_by`; `scholar-author`'s bibliographic
`articles`. **Then on the transport result**: hits → emit JSONL (with `pdf_url`
when a resource link exists); zero hits / a SerpAPI "no results" `error` →
quarantine (empty-result); an HTTP 401/429 or other `error` → quarantine
(api-error). No LLM is ever called to classify or rescue a record.

## Later stages (deferred)

- **Author-article enrichment.** `scholar-author` returns bibliographic records
  only; fetching each article's abstract snippet + PDF via a follow-up
  `google_scholar` lookup per title is an **N+1** pass that burns SerpAPI quota,
  deferred until an author-driven review needs the files.
- **Full abstracts.** Scholar exposes only a truncated `snippet`; recovering the
  full abstract (via the resolved DOI → S2/Crossref, or the fetched paper) is
  downstream work — arXiv/s2 remain the full-abstract sources.
- **Fuzzy-match precision guard.** Verifying an organic hit against the intended
  title (reuse `resolve_oa._title_overlap`) to drop loosely-related top hits — a
  precision refinement, counter to US 25's wide-net recall, deferred to US 26.
- **Pagination / depth.** Scholar's `start`/`num` paging for exhaustive recall,
  gated (like US 25) on the first page proving too shallow.
- **Direct fetch hand-off.** A driver that pipes a `scholar` hit's `pdf_url`
  straight into `fetch-one` (skipping `resolve-oa`) is composed from this step,
  not baked in.
