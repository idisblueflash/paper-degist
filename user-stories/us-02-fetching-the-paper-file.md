# US 2 Fetching the paper file

As a *researcher*, i want to *fetch the paper*, so that i can *handle it* later.

## Acceptence Critierias

1. Given a list of URLs
   - when fetch-list process the list
     - then we got the file of each URL
2. Given one URL
   - when fetch-one process the URL
     - then we fetch the file
     - and save it under files/ folder

## Case handling (classify-then-dispatch)

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

## Filename rule

- Derive the name from the URL basename: `files/<basename>.<ext>`.
- If the file already exists, skip (so re-runs are idempotent and US 7 can
  detect what is genuinely new).
