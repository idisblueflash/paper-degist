# US 10 Resolving a DOI from a title (Crossref)

As a *researcher*, i want to *recover a paper's DOI from the title in a
slug-only URL*, so that *resolve-oa can check open access automatically* instead
of quarantining at US9 AC5.

US9 AC5 quarantines a slug-only URL (ResearchGate, Academia.edu) because no DOI
is embedded — routing it to a human. But the title is recoverable from the URL
slug, and Crossref's bibliographic query maps a title to a DOI. Building this
closes the US9 AC5 deferred branch so a slug URL can resolve end-to-end
(slug → title → DOI → OA PDF) without a hand lookup.

The risk is that Crossref's bibliographic query always returns a *best-effort*
top match — even a wrong paper for an unrecognized or truncated title. So the
recovered DOI is only trusted when the returned title **confidently matches** the
queried title; a weak match is quarantined (route to human), never fed blindly
into the OA lookup as if it were the paper.

## Acceptance Criteria

1. Given a slug-only URL from which a title is extracted and Crossref returns a
   confidently-matching DOI
   - when resolve-oa recovers the title and looks it up
     - then the recovered DOI feeds the OA dispatch (US9), yielding an OA PDF URL
       or a precise closed-access quarantine — no longer a bare "no DOI" dead end
2. Given a slug URL whose title Crossref matches only weakly (below the overlap
   threshold — a wrong or truncated best-effort match)
   - then quarantine with reason
     `"title→DOI: no confident Crossref match (route to human/browser)"` — never
     trust a low-confidence match as the paper
3. Given a URL with no extractable title slug (e.g. a bare domain)
   - then quarantine with reason
     `"no DOI and no title to resolve (route to human/browser)"`
4. Given the Crossref lookup errors (network / timeout / API 4xx)
   - then quarantine with the error reason and finish cleanly — never crash

## Case handling (classify-then-dispatch)

resolve-oa first tries an embedded DOI (US9). On none, it tries title→DOI:
extract a title slug from the URL, ask Crossref, and gate the top result on a
content-token overlap threshold. Each case is a branch; unknowns quarantine —
never crash, never call an LLM in the loop. A confidently-recovered DOI rejoins
the existing OA dispatch, so closed access and OA-PDF outcomes stay identical to
US9.

## Later stages (deferred)

- **OverLap threshold tuning.** The confidence guard is a symmetric content-token
  Jaccard against a fixed threshold, calibrated on three real Crossref responses.
  A larger labelled sample (or a fuzzier string metric) would set it more
  robustly — see DEVLOG.
- **Multi-candidate scan.** Only Crossref's top result is considered; a correct
  match ranked #2 is missed. Widen `rows` and pick the best-overlapping candidate
  when the top one fails the guard.
