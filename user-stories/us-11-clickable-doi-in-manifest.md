# US 11 Clickable DOI link in the resolve-oa quarantine record

As a *researcher reading `manifest.jsonl` by hand*, i want *each resolve-oa
quarantine that recovered a DOI to carry a clickable `https://doi.org/…` link*,
so that *I can click straight through to the paper* instead of copy-pasting a
bare DOI string into a browser.

resolve-oa quarantines route to the human/browser lane (US9 AC5, US10 AC2), so
the record *is* the hand-off. Today it stores `doi` as a bare identifier
(`10.1016/j.learninstruc.2007.02.008`) and `url` as whatever was passed in —
which, for a DOI-input run, is that same non-clickable bare DOI. A reader of the
manifest then has to reconstruct the `doi.org` URL by hand. Emitting the
resolvable link when a DOI is known makes the hand-off directly actionable.

The scope is a **read-side, additive** field on the resolve-oa manifest record
only: it does not change the fetch-one record shape, does not merge or rewrite
prior records (the manifest stays append-only, one record per quarantine event
per step), and does not change any exit code or stdout behavior.

## Acceptance Criteria

1. Given a resolve-oa quarantine whose record has a recovered `doi`
   (e.g. closed access, or an OA-lookup error)
   - then the record also carries a `doi_url` of `https://doi.org/<doi>` — a
     clickable link a manifest reader can follow to the paper
2. Given a resolve-oa quarantine with no DOI recovered (`doi` is `null` — the
   title→DOI dead ends)
   - then no `doi_url` is added (there is no DOI to link); the existing `url`
     field still records the original input unchanged
3. Given the fetch-one (or any other stage's) quarantine record
   - then its shape is unchanged — `doi_url` is a resolve-oa-only field

## Case handling (classify-then-dispatch)

The resolve-oa quarantine helper classifies on whether a DOI was recovered: a
present DOI adds the derived `doi.org` link; a `null` DOI adds nothing. No new
network call — the link is a pure string transform of the DOI already in hand.

## Later stages (deferred)

- **Consolidated manifest view.** A separate read-side reporting tool could group
  the append-only manifest by input/DOI to show "everything that happened to this
  paper" in one glance — without collapsing the per-stage, per-event rows that
  make the log diagnostic. Out of scope here; noted so the append-only write path
  stays untouched. See DEVLOG.
- **Dedup on re-run.** Re-running a step on the same input appends a duplicate
  quarantine row. Deduplicating identical re-run records (within one stage) is a
  separate concern from this link enhancement.
