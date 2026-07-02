# US 9 Resolving open access for a failed fetch

As a *researcher*, i want to *verify whether a fetch that failed (403 / paywall)
has an open-access copy*, so that i can *download it from a free source — or
know precisely why i cannot*, instead of being left with a bare `http 403`.

Some hosts (ResearchGate, Academia.edu) sit behind Cloudflare and return 403 to
any non-browser client; the download link is browser-session-bound, not
URL-derivable (see DEVLOG). Rather than stop at the 403, recover the paper's DOI
and ask the open-access indexes (Unpaywall) whether a free PDF exists.

## Acceptance Criteria

1. Given a failed URL (or DOI) whose paper has an open-access copy
   - when resolve-oa looks it up
     - then it outputs the open-access PDF URL (which fetch-one can then fetch)
2. Given a failed URL whose paper is closed access
   - when resolve-oa looks it up and finds no OA copy
     - then quarantine to `manifest.jsonl` with reason
       `"no OA copy (closed access)"` — a precise reason, not a bare `http 403`

## Case handling (classify-then-dispatch)

resolve-oa classifies the input by whether a DOI can be recovered, then
dispatches on the OA verdict. Each known case is a branch; unknowns quarantine —
never crash, never call an LLM in the loop.

3. Given a URL/DOI from which a DOI is recovered and the OA index says "open"
   - then output the OA PDF URL (success)
4. Given a recovered DOI the OA index reports as closed
   - then quarantine, reason `"no OA copy (closed access)"`
5. Given an input with no recoverable DOI (e.g. a ResearchGate slug URL)
   - then quarantine, reason names that title→DOI resolution is not yet built
     (DEVLOG deferred flag) — later handled by a human or a browser dev-mode
     session
6. Given the OA lookup errors (network / timeout / API 4xx)
   - then quarantine with the error reason and finish cleanly — never crash

## Later stages (deferred)

- **Title→DOI via Crossref**, so slug-only URLs (ResearchGate) resolve
  automatically instead of quarantining at AC5. *(Now US 10.)*
- **A human / Chrome dev-mode rescue lane** for closed or Cloudflare-gated
  papers: the manifest reason routes the item to a person (or an authenticated
  browser session) rather than back into the automated loop.
