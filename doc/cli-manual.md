# paper-degist — CLI manual

A hand-runnable reference for every pipeline step, so a human (or Claude Code,
between sessions) can drive the workflow from the shell **with no AI in the
loop**. Each step is an independent console script (rule 03); the pipeline is
run one step at a time, piping `parse-url → fetch-one → convert-html`, with
`resolve-oa` as the recovery lane for a failed fetch.

Every command is invoked with `uv run <name>` (rule 01 — never bare `python`).
Run `uv run <name> --help` for the authoritative option list; this manual adds
the examples and the *why*.

## Conventions shared by every step

- **Input**: a file or URL argument; `parse-url` also reads **stdin** when the
  argument is omitted, so steps pipe.
- **Output**: the useful result (a URL, a saved path, an OA PDF URL) is printed
  to **stdout**, one record per line — so the output of one step feeds the next.
- **Quarantine, never crash** (rule 02): an input the step cannot handle is
  appended to `manifest.jsonl` and the step exits **cleanly (exit 0)** with a
  `quarantined (see manifest.jsonl): <input>` note on **stderr**. A quarantine
  is an expected outcome, not an error — the batch still finishes. The manifest
  is the queue of cases to handle by hand (or the next code branch).
- **Idempotent**: a step that writes a file skips when the target already
  exists — it never overwrites, so re-runs are safe.
- **Files** land under `files/` by default (untracked). The manifest is
  `manifest.jsonl` in the working directory by default.

## The signpost

```
uv run paper-degist
```

Prints the list of steps and what each does. It runs nothing itself — it is a
directory to the real commands below.

---

## `parse-url` — extract URLs from text (US1)

Pull the http(s) links out of a free-text blob (e.g. a notes file),
de-duplicated, in first-seen order.

```
uv run parse-url <file>       # read a file
uv run parse-url              # read stdin
```

- **Argument**: `file` — a text file to parse. Omit it to read stdin.
- **Output**: one URL per line on stdout.
- De-duplication is exact-string (no normalization): scheme case, a trailing
  slash, query strings, and fragments are each treated as distinct URLs.

### Examples

```bash
# From a file
uv run parse-url notes.md

# From stdin (pipe prose in)
pbpaste | uv run parse-url

# Drive the next step: fetch every URL found
uv run parse-url notes.md | while read -r url; do
  uv run fetch-one "$url"
done
```

---

## `fetch-one` — fetch one paper file (US2)

Fetch a URL and save the file under `files/`, classifying what actually came
back (HTTP status → Content-Type → `%PDF` byte-sniff) and dispatching by type.

```
uv run fetch-one <url>
uv run fetch-one <url> --files-dir out/ --manifest manifest.jsonl
```

- **Argument**: `url` — the URL to fetch.
- **Options**: `--files-dir` (default `files`), `--manifest` (default
  `manifest.jsonl`).
- **Output**: the saved path on stdout, e.g. `files/paper.pdf`. Follows
  redirects; a PDF → `.pdf`, an HTML paper → `.html`.
- **Quarantined** (stderr note, recorded in the manifest): a paywall/login wall,
  a `4xx`/`5xx`/timeout, or an unrecognized content type. A `403` from a
  Cloudflare-gated host (ResearchGate, Academia.edu) lands here — that is the
  cue to try `resolve-oa`.

### Examples

```bash
# Happy path — prints e.g. files/1706.03762.pdf
uv run fetch-one https://arxiv.org/pdf/1706.03762

# A 403 quarantines cleanly; then try the OA lane
uv run fetch-one https://www.researchgate.net/publication/249870239_An_investigation
#   -> stderr: quarantined (see manifest.jsonl): https://www.researchgate.net/...
```

---

## `convert-html` — HTML paper → Markdown (US5)

Convert a saved `files/<name>.html` into a structure-preserving
`files/<name>.md` (headings, lists, tables, code). This is the `.html` branch of
the convert stage; `.pdf` input is *not* this step's job and is quarantined.

```
uv run convert-html files/paper.html
uv run convert-html files/paper.html --manifest manifest.jsonl
```

- **Argument**: `file` — the `.html` file to convert (must exist).
- **Option**: `--manifest` (default `manifest.jsonl`).
- **Output**: the saved `.md` path on stdout.
- **Quarantined**: a non-`.html` extension (e.g. you pointed it at a `.pdf`), an
  undecodable (non-UTF-8) file, or Markdown below the content-density threshold
  (a hollow JS-rendered SPA shell — "HTML too thin").

### Examples

```bash
# Happy path — prints files/keyword-method.md
uv run convert-html files/keyword-method.html

# Wrong type quarantines cleanly (PDF is US3+US4, not this step)
uv run convert-html files/paper.pdf
#   -> stderr: quarantined (see manifest.jsonl): files/paper.pdf
```

---

## `resolve-oa` — recover an open-access copy of a failed fetch (US9 / US10)

When `fetch-one` quarantines a URL (typically a `403`), ask whether the paper is
reachable for free somewhere. Recover the paper's DOI — embedded in the URL, or
(US10) resolved from the URL's title slug via Crossref — then ask Unpaywall for
an open-access **PDF** URL. Print that URL so it can be piped back into
`fetch-one`.

```
uv run resolve-oa <url-or-doi> --email you@example.com
```

- **Argument**: `url` — the failed URL, or a bare DOI.
- **Options**: `--email` (**required**; Unpaywall and Crossref both require a
  contact email — set once via `export UNPAYWALL_EMAIL=you@example.com` instead
  of passing `--email` each time), `--manifest` (default `manifest.jsonl`).
- **Output**: the open-access PDF URL on stdout.
- **Quarantined**, each with a precise reason (not a bare `http 403`):
  - `no OA copy (closed access)` — Unpaywall reports the paper closed.
  - `title→DOI: no confident Crossref match (route to human/browser)` — a title
    was recovered but Crossref's best match is too weak to trust.
  - `no DOI and no title to resolve (route to human/browser)` — nothing to work
    from (e.g. a bare domain).
  - `OA lookup error: …` / `title→DOI lookup error: …` — a network/API error;
    finishes cleanly.
- **Manifest hand-off** (US11): every quarantine that recovered a DOI also
  carries a `doi_url` of `https://doi.org/<doi>` — a clickable link straight to
  the paper for a reader working `manifest.jsonl` by hand. A quarantine with no
  DOI (`doi: null`) carries no `doi_url`.

### Examples

```bash
export UNPAYWALL_EMAIL=you@example.com

# From a DOI — prints the OA PDF URL when one exists
uv run resolve-oa 10.1371/journal.pone.0000308

# From a slug-only URL — recovers the title, asks Crossref, then Unpaywall
uv run resolve-oa https://www.researchgate.net/publication/249870239_An_investigation

# The recovery loop: feed the resolved URL straight back into fetch-one
pdf=$(uv run resolve-oa 10.1371/journal.pone.0000308) && uv run fetch-one "$pdf"
```

---

## `browser-up` — launch (or reuse) a dev-mode Chrome for the browser lane (US18)

The browser lane (`browser-fetch`, US15/16) attaches to an **already-running**
dev-mode Chrome over the Chrome DevTools Protocol (CDP). `browser-up` is the
setup command one layer before it: it locates the Chrome binary, launches it on
the remote-debugging port against a **fixed persistent profile**, waits until the
endpoint answers, and prints it — then detaches, leaving Chrome running for the
researcher to log in once. Call it at the top of every browser-lane run: if a
dev-mode Chrome is already reachable it **reuses** that one (idempotent — never a
second Chrome) and prints the same endpoint.

```
uv run browser-up [--cdp http://localhost:9222] [--user-data-dir .browser-profile]
```

- **Options**: `--cdp` (CDP endpoint to reuse or bring up; default
  `http://localhost:9222`), `--user-data-dir` (persistent Chrome profile;
  default `.browser-profile`).
- **Output**: the reachable CDP endpoint on stdout (feed it to `browser-fetch`).
- **Profile is secrets-at-rest.** The fixed `--user-data-dir` holds the
  researcher's live logged-in sessions, so it is **gitignored** and never
  committed. Because the login lives in the profile, the manual confirmation is
  amortized to the **first** run — until a session expires, when the researcher
  re-logs-in by hand (browser-up cannot detect expiry).
- **Loud failure, not a quarantine.** This step has no paper and no batch to keep
  running, so a launch it cannot complete exits **non-zero** with a clear
  diagnostic (never a stack trace, never a manifest line):
  - `could not find a Google Chrome / Chromium binary …` — Chrome is not
    installed / not on PATH.
  - `the CDP port … is already held by a non-debug process …` — something else
    holds the port; free it or pass another `--cdp` port.
  - `launched Chrome but the CDP endpoint … did not come up in time`.

### Examples

```bash
# Happy path — launches Chrome (or reuses a running one) and prints the endpoint
uv run browser-up
#   -> http://localhost:9222   (Chrome window opens; log in by hand once)

# Idempotent — a second call reuses the same Chrome, prints the same endpoint
uv run browser-up

# A different port / profile is a flag, not a new command
uv run browser-up --cdp http://localhost:9333 --user-data-dir .browser-profile

# Compose with the browser lane: bring Chrome up, then fetch a bot-walled URL
endpoint=$(uv run browser-up) && uv run browser-fetch <url> --cdp "$endpoint"
```

The researcher owns Chrome's shutdown — `browser-up` never kills a browser (a
warm session survives for later runs). `browser-fetch` and `--cdp` (US15/16) are
not built yet; the composition line shows the intended shape.

---

## End-to-end (no AI in the loop)

```bash
export UNPAYWALL_EMAIL=you@example.com

# 1. Links out of notes → 2. fetch each → 3. convert any HTML papers
uv run parse-url notes.md | while read -r url; do
  path=$(uv run fetch-one "$url") || continue
  case "$path" in
    *.html) uv run convert-html "$path" ;;
  esac
done

# 4. For anything that quarantined with a 403, try the OA lane by hand:
#    inspect manifest.jsonl, then for each failed url:
uv run resolve-oa "<failed-url>" && uv run fetch-one "<printed OA pdf url>"
```

Inspect `manifest.jsonl` for everything that could not be handled
automatically — each line names the `stage`, the input, and the `reason`, which
tells you (or the next code branch) exactly what to do next.
