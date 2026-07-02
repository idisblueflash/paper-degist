# User Stories

## US 1 Parsing the links

As a *researcher*, i want to *parse the paper links out of a text*, so that i
can *fetch them* later.

### Acceptence Critierias

1. Given a text with URLs
   - when parse-url process the text
     - then we got a list of URLs

## US 2 Fetching the paper file

As a *researcher*, i want to *fetch the paper*, so that i can *handle it* later.

### Acceptence Critierias

1. Given a list of URLs
   - when fetch-list process the list
     - then we got the file of each URL
2. Given one URL
   - when fetch-one process the URL
     - then we fetch the file
     - and save it under files/ folder

### Case handling (classify-then-dispatch)

fetch-one classifies what actually came back (Content-Type header first,
byte sniff second) and dispatches to a handler. Unknown cases are
quarantined to manifest.jsonl and skipped — never crash, never call an LLM
in the loop. The manifest is the queue of cases the script does not yet
know how to handle.

3. Given a URL that returns a PDF (happy path)
   - when fetch-one classifies the response (`Content-Type: application/pdf`,
     or body starts with `%PDF`)
     - then save the bytes as `files/<name>.pdf`
4. Given a URL that returns an HTML paper (web version)
   - when fetch-one classifies the response as `text/html`
     - then save the raw HTML as `files/<name>.html`
     - and defer conversion to Markdown to a later stage (US 5)
5. Given a URL that returns a redirect (3xx)
   - when fetch-one follows it (cap the hops)
     - then re-classify the final response
6. Given a paywall / login wall, an error (4xx/5xx/timeout), or any
   response matching no known handler
   - when fetch-one cannot handle it
     - then append a record to `manifest.jsonl` (url, status, content-type,
       reason)
     - and skip to the next URL so the batch still finishes

### Filename rule

- Derive the name from the URL basename: `files/<basename>.<ext>`.
- If the file already exists, skip (so re-runs are idempotent and US 7 can
  detect what is genuinely new).

## US 3 Converting PDF

As a *researcher*, i want to *convert PDF paper into text file*, so that i can *process it with LLM* later.

## US 4 Formatting Paper

As a *researcher*, i want to *convert text file into MD file*, so that i can *process it with LLM* later.

## US 5 Converting HTML

As a *researcher*, i want to *convert an HTML paper into an MD file*, so that i
can *process it with LLM* later.

An HTML paper is already structured markup — unlike the PDF path (US 3 extracts
lossy text, US 4 reconstructs it), headings, lists, tables, and code blocks map
near-directly to Markdown, so this is a distinct, structure-*preserving*
converter rather than a case of US 4.

### Acceptance Criteria

1. Given a saved `files/<name>.html`
   - when convert-html processes it
     - then structure (headings, lists, tables, code) is preserved as Markdown
     - and saved as `files/<name>.md`

### Case handling (classify-then-dispatch)

The convert stage dispatches by file extension (mirroring fetch-one's
Content-Type dispatch): `.pdf` → the PDF path (US 3 + US 4), `.html` → this
converter. Both paths converge on `files/<name>.md`.

2. Given an HTML file whose real content is JS-rendered (a hollow SPA shell,
   e.g. a near-empty `<div id="__next">`)
   - when convert-html finds the extracted Markdown is below a content-density
     threshold
     - then quarantine it to `manifest.jsonl` (path, reason: "HTML too thin")
     - and skip it so the batch still finishes — never crash, never call an LLM
       in the loop (see DEVLOG deferred flag)

## US 6 Importing Paper

As a *researcher*, i want to *import MD files into src/* folder of LLM wiki, so that *my skill* *can compile them*.

## US 7 Compiling Paper

As a *Karpathy-wiki Skill*, i want to *compile the new files under src/*, so that i can *extract concepts*.

## US 8 Rating Paper

As a *Karpathy-wiki Skill*, i want to *rate each paper's depth need (skim / study / reimplement)*, so that *I don't flatten every topic into the same report*.

## US 9 Resolving open access for a failed fetch

As a *researcher*, i want to *verify whether a fetch that failed (403 / paywall)
has an open-access copy*, so that i can *download it from a free source — or
know precisely why i cannot*, instead of being left with a bare `http 403`.

Some hosts (ResearchGate, Academia.edu) sit behind Cloudflare and return 403 to
any non-browser client; the download link is browser-session-bound, not
URL-derivable (see DEVLOG). Rather than stop at the 403, recover the paper's DOI
and ask the open-access indexes (Unpaywall) whether a free PDF exists.

### Acceptance Criteria

1. Given a failed URL (or DOI) whose paper has an open-access copy
   - when resolve-oa looks it up
     - then it outputs the open-access PDF URL (which fetch-one can then fetch)
2. Given a failed URL whose paper is closed access
   - when resolve-oa looks it up and finds no OA copy
     - then quarantine to `manifest.jsonl` with reason
       `"no OA copy (closed access)"` — a precise reason, not a bare `http 403`

### Case handling (classify-then-dispatch)

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

### Later stages (deferred)

- **Title→DOI via Crossref**, so slug-only URLs (ResearchGate) resolve
  automatically instead of quarantining at AC5.
- **A human / Chrome dev-mode rescue lane** for closed or Cloudflare-gated
  papers: the manifest reason routes the item to a person (or an authenticated
  browser session) rather than back into the automated loop.

