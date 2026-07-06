# US 30 Cross-check open access against OpenAlex when Unpaywall says closed

As a *researcher recovering a failed fetch*, i want *`resolve-oa` to ask
OpenAlex for an open-access copy when Unpaywall reports the paper closed*, so
that *a paper with a repository or self-archived copy OpenAlex knows about is
not wrongly reported "closed access" and abandoned*.

## Background

US 9 built `resolve-oa` around a **single** OA source, Unpaywall
(`resolve_oa.py::_unpaywall_lookup`): recover a DOI, ask Unpaywall, output the
OA PDF URL or quarantine `"no OA copy (closed access)"`. That verdict rests on
one index. Unpaywall and OpenAlex do not have identical OA coverage — OpenAlex
aggregates repository copies, author self-archives, and preprint hosts that
Unpaywall can miss — so a paper Unpaywall marks closed may still have a free PDF
OpenAlex can point to. This is the OPEN deferred flag in
[`DEVLOG.md`](../DEVLOG.md) (*"resolve_oa — single OA source (Unpaywall);
OpenAlex/CORE not cross-checked"*); this story closes it.

The fix is a **second OA lookup, tried only when Unpaywall yields no PDF**:
query OpenAlex Works by the recovered DOI (`https://api.openalex.org/works/doi:
<doi>`) and read `best_oa_location` / `oa_locations[]` for a `pdf_url`. It is the
**same keyless + `mailto` polite-pool client** US 29 introduces (shared module,
`OPENALEX_EMAIL` / `--email`), and it reuses US 9's injected-lookup shape so it
stays testable offline. The verdict becomes the **union**: open if *either*
index has an OA PDF; closed only when **both** agree there is none — and the
closed-access quarantine reason then reflects that both were checked.

This is a `resolve-oa` **precision** change (fewer false "closed" verdicts); it
does not touch DOI recovery (US 9/US 10), the clickable-DOI record (US 11), or
`discover` (US 29). Unpaywall stays the **first** lookup (it carries a richer
verdict); OpenAlex is the **fallback**, so the common path is unchanged and a
paper Unpaywall already resolves never triggers a second call.

## Acceptance Criteria

1. Given a recovered DOI that Unpaywall reports as **closed** (no OA PDF) but
   for which OpenAlex has an OA location with a `pdf_url`
   (e.g. a repository copy of `10.1145/3292500.3330701`)
   - when resolve-oa falls back to OpenAlex
     - then it outputs OpenAlex's OA PDF URL (success) — the paper is **not**
       quarantined as closed
2. Given a recovered DOI that **both** Unpaywall and OpenAlex report with no OA
   PDF
   - when resolve-oa has consulted both indexes
     - then it quarantines `"no OA copy (closed access)"` (US 9 AC2/AC4) with the
       reason recording that **both** Unpaywall and OpenAlex were checked — a
       verdict backed by two indexes, not one
3. Given a recovered DOI that **Unpaywall** already reports open (with a PDF)
   - when resolve-oa resolves it
     - then it outputs Unpaywall's OA PDF URL **without calling OpenAlex** — the
       fallback fires only when the first lookup yields no PDF
4. Given the OpenAlex fallback lookup errors (network / timeout / API 4xx-5xx /
   429) while Unpaywall returned closed
   - when resolve-oa cannot complete the cross-check
     - then it quarantines with an OA-lookup-error reason that names OpenAlex as
       the failed source (distinct from Unpaywall's own error, US 9 AC6), and
       finishes cleanly — never crashes, never calls an LLM
5. Given `--source`-style config with **no** contact email for the OpenAlex
   fallback
   - when the fallback runs
     - then it queries OpenAlex on the keyless common pool and **logs a
       warning** (US 29 AC4) — a missing email downgrades politeness, it does
       not skip the cross-check

## Case handling (classify-then-dispatch)

resolve-oa keeps US 9's shape — recover a DOI, then dispatch on the OA verdict —
but the verdict is now computed from **two** indexes in sequence: Unpaywall
first; if it yields a PDF, done (OpenAlex is never called). Only when Unpaywall
returns no PDF does the OpenAlex fallback issue its keyless `mailto` lookup by
DOI and read `best_oa_location`/`oa_locations` for a `pdf_url`, encoding that
extraction **once** (rule 02) in the shared OpenAlex client (US 29). The union
rule decides: **open** if either index has an OA PDF → output it; **closed**
only when both agree → quarantine with the both-checked reason; an OpenAlex
transport error → quarantine (OA-lookup-error naming OpenAlex). No LLM is ever
called to classify or rescue a verdict.

## Later stages (deferred)

- **CORE as a third OA index.** DEVLOG's flag names OpenAlex **and** CORE.
  OpenAlex closes the common gap (it already aggregates many repository copies);
  adding CORE as a further union member is a later refinement, gated on a paper
  still wrongly reported closed after the OpenAlex cross-check.
- **OA-location provenance in the record.** Recording *which* index supplied the
  winning PDF (Unpaywall vs OpenAlex) in the success record — useful telemetry
  for coverage comparison — is deferred; this story only needs the URL.
- **Shared client extraction.** US 29 and this story both parse OpenAlex
  `oa_locations`; the common client/DTO is factored once and reused, but any
  broader OpenAlex-metadata surface (authors, topics) beyond OA locations is out
  of scope here.
