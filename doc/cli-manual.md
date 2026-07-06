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

## `dedup-inputs` — collapse inputs that point at the same DOI (US14)

A pure, offline filter that sits between `parse-url` and `fetch-one`: it reads a
list of inputs, canonicalizes any DOI it can read out of each one, and keeps only
the **first** input for each distinct DOI — so a paper reached three ways (a bare
DOI, its `doi.org` link, a publisher URL that embeds the DOI) is fetched once,
not three times. Makes **no network call and no LLM call**.

```
uv run dedup-inputs <file>                        # read a file
uv run dedup-inputs                               # read stdin
uv run dedup-inputs <file> --manifest manifest.jsonl
```

- **Argument**: `file` — a list of inputs, one per line. Omit it to read stdin.
- **Options**: `--manifest` (default `manifest.jsonl`) — where dropped duplicates
  are recorded.
- **Output**: the surviving inputs, one per line on stdout, in first-seen order.
  The *original* kept input is printed (never rewritten to canonical form), so
  `fetch-one` still works on it unchanged.
- **The key** is a **normalized DOI**: the DOI extracted from the input
  (`resolve_oa.doi_from`), scheme/`doi.org` prefix stripped, **lowercased** (DOIs
  are case-insensitive), so `https://doi.org/10.X`, `10.X`, and `10.x` fold to one
  key.
- **No extractable DOI → pass through** (never dropped): a PubMed or ScienceDirect
  URL exposes no DOI in its text, so the step cannot prove it duplicates anything
  without a network lookup — it keeps it. Unmasking those DOIs is `resolve-oa`'s
  job (a deferred coupling; see DEVLOG).
- **Dropped duplicate** → a `duplicate` record is appended to the manifest
  (`stage: "dedup-inputs"`, the dropped `input`, its normalized `doi`, and the
  `duplicate_of` input it duplicates) — so every collapse is auditable, never
  silent, and the manifest stays append-only.
- Dedups **within one input list** only; a cross-run seen-ledger (skip a paper
  fetched last week) is a separate, deferred design.

### Examples

```bash
# Happy path — three forms of one DOI collapse to the first; a bare uppercase
# twin folds too, and a DOI-less URL passes through
printf '%s\n' \
  'https://doi.org/10.1016/j.learninstruc.2007.02.008' \
  '10.1016/J.LearnInstruc.2007.02.008' \
  'https://pubmed.ncbi.nlm.nih.gov/2303742/' \
  | uv run dedup-inputs
#   -> https://doi.org/10.1016/j.learninstruc.2007.02.008
#   -> https://pubmed.ncbi.nlm.nih.gov/2303742/
#   -> manifest: {"stage":"dedup-inputs","input":"10.1016/J.LearnInstruc.2007.02.008",
#                 "doi":"10.1016/j.learninstruc.2007.02.008",
#                 "duplicate_of":"https://doi.org/10.1016/j.learninstruc.2007.02.008"}

# Drop-in between parse-url and fetch-one: parse, collapse dups, fetch each once
uv run parse-url notes.md | uv run dedup-inputs | while read -r url; do
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
- **Bot-wall recognition** (US12): a `403` from a *known* bot-walling host is
  tagged, not left as a bare `http 403`. The record gains a `blocked_by`
  registrable host (`researchgate.net`, `pubmed.ncbi.nlm.nih.gov`) and a `reason`
  that names it a bot-wall and points at the `resolve-oa` lane (PubMed also warns
  the URL is abstract-only). This is additive and `fetch-one`-only: a `403` from
  any other host keeps the generic record, and no exit code or stdout changes.
  The `blocked_by` tag is the routing key `recover-blocked` (US17) reads to drain
  these into the browser lane. Growing the host table is a one-line addition when
  a new walling host recurs in the manifest.
- **Filename verification** (US13): after a successful save, `fetch-one` compares
  the saved file's real title (HTML `<title>`, PDF `/Title` metadata) to its
  basename. This never changes stdout, the saved path, or the exit code — it only
  *notes* generic, collision-prone names in the manifest for a human to rename:
  - a **mismatch** (`10.pdf`, `viewcontent.cgi.pdf`) appends a `fetch-one` record
    carrying the `file`, the extracted `title`, and a `reason: mismatch: …`;
  - an **unverifiable** title (no `<title>`, no PDF metadata title) appends a
    `reason: title-unverifiable: …` record — absence of a title is not a wrong
    name, so it is not a mismatch;
  - a basename whose slug tokens are a subset of the title's writes **nothing**.
  Re-runs skip the already-saved file, so no duplicate note is written.

### Examples

```bash
# Happy path — prints e.g. files/1706.03762.pdf
uv run fetch-one https://arxiv.org/pdf/1706.03762

# A 403 quarantines cleanly; then try the OA lane
uv run fetch-one https://www.researchgate.net/publication/249870239_An_investigation
#   -> stderr: quarantined (see manifest.jsonl): https://www.researchgate.net/...

# US12 — a known bot-wall is tagged with blocked_by + an actionable reason
uv run fetch-one https://pubmed.ncbi.nlm.nih.gov/2303742/
#   -> manifest: {"stage":"fetch-one","url":"https://pubmed.ncbi.nlm.nih.gov/2303742/",
#                 "status":403,"blocked_by":"pubmed.ncbi.nlm.nih.gov",
#                 "reason":"bot-walled source: PubMed blocks automated fetches, and this
#                           URL is an abstract-only page … — route around it via resolve-oa"}

# US13 — a saved but generically-named PDF is flagged for rename (still exits 0)
uv run fetch-one "https://rdw.rowan.edu/cgi/viewcontent.cgi?article=1080&context=etd"
#   -> stdout: files/viewcontent.cgi.pdf
#   -> manifest: {"stage":"fetch-one","file":"files/viewcontent.cgi.pdf",
#                 "title":"The keyword method: a study of vocabulary acquisition …",
#                 "reason":"mismatch: filename does not reflect the paper's title …"}
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

# Compose with the browser lane: bring Chrome up, then fetch a list of URLs
endpoint=$(uv run browser-up) && uv run browser-fetch urls.txt --cdp "$endpoint"
```

The researcher owns Chrome's shutdown — `browser-up` never kills a browser (a
warm session survives for later runs).

---

## `browser-fetch` — capture bot-walled pages through the dev-mode Chrome (US15/US16)

`fetch-one` (US12) can *recognize* a bot-walled 403 but not get past it;
`browser-fetch` is the recovery *mechanism*. It **attaches** to the
already-running dev-mode Chrome that `browser-up` brought up (over CDP), and for
each URL navigates and waits for the DOM to settle (`networkidle`, so a
client-rendered page is captured — not the initial shell), then saves the
rendered HTML under `files/` with the researcher's real logged-in cookies. It
mirrors `fetch-one`'s save + manifest contract, so `convert-html` consumes the
result. It **never** launches or kills Chrome (that is `browser-up`) and never
logs in or solves a captcha for you (deciding *which* URLs need the browser is
US17).

It reads a **list** of URLs and reuses **one** warm connection across the whole
batch (US16): it probes the CDP endpoint once, then opens and closes a *tab* per
URL against that single session — so every URL rides the same warm, authenticated
Chrome instead of paying a cold connection per URL, and (via the persistent
profile) the next run reuses it too. A single URL is just a one-line list.

```
uv run browser-fetch [urls_file] [--cdp http://localhost:9222] [--files-dir files] [--manifest manifest.jsonl]
```

- **Argument**: `urls_file` — a file of bot-walled URLs, **one per line** (blank
  lines and surrounding whitespace are ignored). Omit it to read the list from
  **stdin**, so `browser-fetch` composes in a pipe.
- **Options**: `--cdp` (CDP endpoint of the running dev-mode Chrome; default
  `http://localhost:9222` — a different port or a remote debugger is just this
  flag, not a new command), `--files-dir` (where the rendered HTML is saved;
  default `files/`), `--manifest` (default `manifest.jsonl`).
- **Output**: each saved (or already-present) path on stdout, **one per line, in
  first-seen order** — a drop-in to pipe into `convert-html` — plus a `saved`
  record per URL in the manifest. If any URL quarantined, a one-line count is
  noted on **stderr** (stdout stays paths-only for piping).
- **Quarantine, not a crash** (unlike `browser-up`, this step carries items
  forward). One URL failing never aborts the batch — it quarantines and the run
  continues. Three distinct manifest `reason`s:
  - `no dev-mode browser endpoint reachable at … — bring one up with browser-up`
    — the CDP endpoint is unreachable; run `browser-up` first, then re-run.
  - `navigation failed: …` — Chrome was reachable but that URL's navigation
    errored or timed out.
  - `browser session failed to open: …` — the endpoint answered the probe but
    the session could not be opened (e.g. a non-Chrome debug server, or Chrome
    lost between probe and connect); the remaining URLs quarantine, never crash.
- **Idempotent.** A URL already saved under `files/` is skipped — the file is left
  untouched and **no** manifest record is appended, so re-running a partly-done
  batch only fetches what is still missing.

### Examples

```bash
# Happy path — bring Chrome up, then capture a whole list over one warm session
endpoint=$(uv run browser-up)
cat > urls.txt <<'EOF'
https://www.researchgate.net/publication/220320021_Spaced_Repetition_and_Long-Term_Retention
https://www.researchgate.net/publication/319012693_The_Testing_Effect_in_the_Classroom
EOF
uv run browser-fetch urls.txt --cdp "$endpoint"
#   -> files/220320021_Spaced_Repetition_and_Long-Term_Retention.html
#   -> files/319012693_The_Testing_Effect_in_the_Classroom.html
#   -> manifest: one {"stage":"browser-fetch","result":"saved", …} record per URL

# Drop-in over a list: pipe the saved paths straight into convert-html
uv run browser-fetch urls.txt --cdp "$endpoint" | while read -r p; do
  uv run convert-html "$p"
done

# Or read the list from stdin (a single URL is a one-line list)
echo "https://www.researchgate.net/publication/234567890_Retrieval_Practice_Produces_More_Learning" \
  | uv run browser-fetch --cdp "$endpoint"

# No Chrome up — every URL quarantines cleanly (exits 0), waits for browser-up
uv run browser-fetch urls.txt
#   -> stdout: (empty — nothing saved)
#   -> stderr: 2 of 2 URL(s) quarantined (see manifest.jsonl)
#   -> manifest: {"stage":"browser-fetch","reason":"no dev-mode browser endpoint reachable …"}
```

---

## `render-pdf` — render a PDF to per-page images for the OCR bench (US19)

The first step of the OCR-model bench (US 19–23): turn a paper PDF into one PNG
per page so every model under comparison sees the **same** page bitmaps. The
render is deterministic — same PDF + same dpi → byte-identical PNGs — so the
downstream scores are reproducible. Ghostscript is the renderer of record
(`png16m`, 150 dpi → 1275×1650 px for US-Letter); it is a bench input stage, not
part of the fetch→convert pipeline.

```
uv run render-pdf <pdf> [--dpi 150] [--pages-dir pages] [--manifest manifest.jsonl]
```

- **Argument**: the `pdf` file to render (validated up front — a missing file
  exits 2).
- **Options**: `--dpi` (render resolution; default `150` — a different dpi is
  this flag, not a new command), `--pages-dir` (root the pages land under;
  default `pages/`), `--manifest` (default `manifest.jsonl`).
- **Output**: one page path per line on stdout —
  `pages/<stem>/pNNNN.png` (zero-padded, in page order) — plus a `rendered`
  provenance record in the manifest (`stage`, `pdf`, `pages`, `dpi`).
- **Quarantine, not a crash** (rule 02). Two cases land in the manifest and exit
  cleanly (exit 0):
  - `not a PDF (no %PDF header)` — the input's magic bytes are not `%PDF` (e.g.
    a fetched `.html` was passed by mistake).
  - `unrenderable PDF: …` — the bytes start with `%PDF` but Ghostscript could
    not render them (truncated/corrupt); any partial pages are cleaned up so a
    re-run does not mistake them for a complete render.
- **Idempotent.** A PDF whose pages already exist under `pages/<stem>/` is
  skipped — the PNGs are left untouched and **no** manifest record is appended.
- **Requires** `gs` on `$PATH` (`brew install ghostscript`).

### Examples

```bash
# Happy path — render every page of a paper to pages/<stem>/pNNNN.png
uv run render-pdf files/WordCraft_Scaffolding_the_Keyword_Method.pdf
#   -> pages/WordCraft_Scaffolding_the_Keyword_Method/p0001.png
#   -> pages/WordCraft_Scaffolding_the_Keyword_Method/p0002.png   … (one per page)
#   -> manifest: {"stage":"render-pdf","pdf":"files/WordCraft_…pdf","pages":32,"dpi":150}

# A higher resolution is just a flag (no new command)
uv run render-pdf files/Attention_Is_All_You_Need.pdf --dpi 300

# Wrong type quarantines cleanly (a non-PDF is not this step's input)
uv run render-pdf files/Deep_Residual_Learning.html
#   -> stderr: quarantined (see manifest.jsonl): files/Deep_Residual_Learning.html
#   -> manifest: {"stage":"render-pdf","pdf":"files/Deep_Residual_Learning.html",
#                 "reason":"not a PDF (no %PDF header)"}
```

The page PNGs are the input the OCR bench's next step (US20 `ocr-page`) sends to
each registered model.

---

## `recover-blocked` — route the manifest's bot-walled URLs into the browser lane (US17)

`browser-fetch` (US15/16) is the recovery *mechanism*; `recover-blocked` is the
*routing* that decides **which** URLs need it. `fetch-one` (US12) tags a
bot-walled 403 with a `blocked_by` host in the manifest; `recover-blocked` reads
the append-only manifest, selects the `blocked_by` records **not yet recovered**,
and hands their URLs to `browser-fetch`'s warm-batch path (one Chrome, US16). It
is deterministic, offline routing — it filters the manifest and delegates the
actual fetching, holding no browser logic and no LLM. It is the **second recovery
lane, parallel to `resolve-oa`** (US9's DOI lane): this one recovers by
*rendering the walled page itself*.

```
uv run recover-blocked [manifest] [--cdp http://localhost:9222] [--files-dir files]
```

- **Argument**: `manifest` — the manifest to scan for `blocked_by` records
  (default `manifest.jsonl`). It must exist (nothing has been fetched otherwise).
  Unlike the other steps this reads a **file, not stdin**: the manifest is a
  persistent, appended-to record — `browser-fetch` writes its recovery records
  back into this same file — not a pipeable stream.
- **Options**: `--cdp` (CDP endpoint of the running dev-mode Chrome; default
  `http://localhost:9222`), `--files-dir` (where the rendered HTML is saved;
  default `files/`). The manifest read *and* written is the argument above.
- **Output**: each recovered path on stdout, **one per line, in first-seen
  order** — a drop-in to pipe into `convert-html`. A one-line outcome is noted on
  **stderr** (stdout stays paths-only for piping).
- **Classify-then-dispatch.** A record with **no** `blocked_by` (a generic 403)
  is skipped — not this lane's job. A `blocked_by` record **already recovered** by
  a later `browser-fetch` `saved` record is skipped — so the step is **idempotent
  across runs**. Everything else is dispatched wholesale to `browser-fetch`.
- **Never drives Chrome, never writes its own record.** The new recovery record
  is `browser-fetch`'s own `saved` one; the original `blocked_by` record is left
  untouched (append-only). With **no** dev-mode Chrome reachable, the blocked URLs
  stay quarantined via `browser-fetch`'s own missing-endpoint reason and
  `recover-blocked` exits cleanly — the retry simply waits for a run with Chrome up.

### Examples

```bash
# Happy path — after fetch-one has tagged some 403s as blocked_by, bring Chrome
# up and drain the walled URLs through it in one warm session
endpoint=$(uv run browser-up)
uv run recover-blocked manifest.jsonl --cdp "$endpoint"
#   -> files/287147155_The_Mnemonic_Keyword_Method.html   (a recovered page)
#   -> stderr: recovered 1 blocked page(s)
#   -> manifest: a new {"stage":"browser-fetch","result":"saved", …} record;
#                the original {"stage":"fetch-one","blocked_by":"researchgate.net", …} untouched

# Drop-in over the manifest: pipe the recovered paths straight into convert-html
uv run recover-blocked --cdp "$endpoint" | while read -r p; do
  uv run convert-html "$p"
done

# Quarantine branch — no Chrome up: the blocked URLs wait, the step exits 0
uv run recover-blocked manifest.jsonl
#   -> stdout: (empty — nothing recovered)
#   -> stderr: no blocked pages recovered — nothing walled to retry, or no dev-mode Chrome reachable
#   -> manifest: {"stage":"browser-fetch","reason":"no dev-mode browser endpoint reachable …"}
```

---

## `ocr-page` — OCR one page image with one registered model (US20)

The second step of the OCR-model bench: send **one** page PNG (from `render-pdf`)
to **one** named vision model and save its Markdown. The costly lesson from the
investigation was the *transport*, not the models — a Python `urllib` image POST
empty-body-502s and takes the MLX worker down. So the transport is fixed encoded
knowledge (rule 02): the JSON body is built in Python and POSTed with
`curl --data @body.json`, **sequentially**, with a recovery gap and
**retry-on-502**. Models are a **registry** — a new model is one
`(prompt, post-processor)` entry, not a code branch.

```
uv run ocr-page <page.png> <model-id> [--out-dir out] [--endpoint URL]
                [--attempts 3] [--gap 7.0] [--manifest manifest.jsonl]
```

- **Arguments**: the `page` PNG (validated up front — a missing file exits 2) and
  a **registered** `model` id (see the registry below).
- **Options**: `--out-dir` (root the Markdown lands under; default `out/`),
  `--endpoint` (the chat-completions URL of the vision server; default
  `http://localhost:1234/v1/chat/completions` — LM Studio), `--attempts` (max
  POSTs before quarantine; default `3`), `--gap` (recovery seconds between
  retries; default `7.0` — the report's ~6–8 s flap window), `--manifest`.
- **Output**: the saved Markdown path on stdout —
  `out/<model-slug>/<page>.md` (`qwen/qwen3-vl-4b` → `out/qwen_qwen3-vl-4b/`) —
  plus an `ocr` provenance record in the manifest (`stage`, `page`, `model`,
  `host`, `latency`, `finish_reason`, `completion_tokens`). `host` is the
  producing machine (`platform.node()`) — `latency` is machine-dependent, so the
  host is recorded to keep a mixed-machine bench attributable (see DEVLOG).
- **Registered models** (the `(prompt, post-processor)` registry):
  - `qwen/qwen3-vl-4b` — a plain "Convert the document to markdown." instruction;
    output is unwrapped from the ```` ```markdown ```` fence it comes in.
  - `deepseek-ocr` — the `<|grounding|>Convert the document to markdown.` prompt
    (the literal `<image>` token **omitted**, or LM Studio 400s on a double
    image); the grounding markup is decoded to plain Markdown.
  - `deepseek-ocr-2`, `deepseek-ocr@8bit` — DeepSeek-OCR-2 (and its 8-bit quant):
    the same grounding prompt as `deepseek-ocr`, but its `<|ref|>` slot holds a
    layout *category* (`text`/`title`/`sub_title`/`table`/…) rather than the text,
    so it takes a distinct decode that **drops** the label and keeps the content
    line (which already carries `##` headings / `<table>` HTML) — a variant is one
    registry entry, not a branch. The decode drops the category whether it arrives
    `<|ref|>`-wrapped or, on a degraded page, as a **bare** label line with no ref
    markers (else those bare `text`/`sub_title` lines repeat down the page and
    inflate the `dup_pct` score). On a RAM-constrained host load **one model at a
    time** (e.g.
    `lms unload --all && lms load deepseek-ocr-2`) and drive with
    `ocr-batch --model <one>` — co-loaded vision models can exhaust RAM and crash
    the worker (see DEVLOG).
- **Quarantine, not a crash** (rule 02). Two cases land in the manifest and exit
  cleanly (exit 0):
  - `unknown model: '…' not in registry` — the model id is not registered; the
    network is **never touched** (distinct from a server error).
  - `server unreachable after N attempts: …` — the endpoint 502'd / was
    unreachable through every retry; the curl diagnostic is included.
- **Idempotent.** A `(page, model)` whose `out/<model>/<page>.md` already exists
  is skipped — the model is the expensive, flaky resource, so a re-run **never**
  re-hits the server and appends **no** manifest record.
- **Requires** `curl` on `$PATH` and a vision server (LM Studio) already up with
  the model loadable — bringing the server up / warming a model is the operator's
  job (as `browser-up` is for Chrome), not this step.

### Examples

```bash
# Happy path — OCR page 2 with qwen; Markdown saved under out/<model-slug>/
uv run ocr-page pages/WordCraft_Scaffolding_the_Keyword_Method/p0002.png qwen/qwen3-vl-4b
#   -> out/qwen_qwen3-vl-4b/p0002.md  (path printed)
#   -> manifest: {"stage":"ocr-page","page":"pages/…/p0002.png","model":"qwen/qwen3-vl-4b",
#                 "host":"mac-mini.local","latency":20.8,"finish_reason":"stop","completion_tokens":167}

# The same page through DeepSeek-OCR is just a different registered id
uv run ocr-page pages/Attention_Is_All_You_Need/p0001.png deepseek-ocr

# An unregistered model quarantines without touching the network
uv run ocr-page pages/Deep_Residual_Learning/p0001.png some-unregistered-ocr
#   -> stderr: quarantined (see manifest.jsonl): …/p0001.png + some-unregistered-ocr
#   -> manifest: {"stage":"ocr-page","page":"…/p0001.png","model":"some-unregistered-ocr",
#                 "reason":"unknown model: 'some-unregistered-ocr' not in registry"}
```

`ocr-page` composes after `render-pdf` (`render-pdf` produces the page PNGs this
step consumes) and feeds the per-model Markdown to the bench's scoring steps
(US21–23). It does one `(page, model)` per run; the batch driver that walks a
page directory across every registered model — keeping the sequential-with-gap
rule — is `ocr-batch` (US28, below), composed from this step.

---

## `ocr-batch` — OCR a page directory across the model registry (US28)

The **grid** driver over `ocr-page`: walk one paper's page directory (from
`render-pdf`) across **every registered model** and lay down the whole
`out/<model>/<page>.md` corpus the scorers (`score-ocr`, `score-gold`) and the
report (`ocr-report`) consume — instead of invoking `ocr-page` once per
`(page, model)` pair by hand. It holds no transport logic of its own: it composes
`ocr-page` (which owns the curl transport, the retry-on-502, and the per-item
quarantine). Its one job beyond iterating the grid is the report §3 anti-flap
rule applied **between items** — a **recovery gap** before each pair that will
contact the server, so the flaky MLX runtime never sees rapid-fire hits.

```
uv run ocr-batch <pages-dir> [--model ID ]... [--out-dir out] [--endpoint URL]
                 [--attempts 3] [--gap 7.0] [--manifest manifest.jsonl]
```

- **Argument**: `pages_dir` — a directory of page images (validated up front — a
  missing directory exits 2), e.g. `pages/<paper>/` from `render-pdf`, or a gold
  set's image directory. Every `.png`/`.jpg`/`.jpeg` file is walked in page order
  — so render-pdf's `pNNNN.png` and OmniDocBench's `.jpg` gold pages are both
  covered.
- **Options**: `--model` (repeatable; restrict to these **registered** model ids;
  omit for the **whole registry** — a new registered model joins the grid with no
  flag change), `--out-dir`, `--endpoint`, `--attempts`, `--gap` (recovery seconds
  before each server-hitting pair; default `7.0`), `--manifest`. These mirror
  `ocr-page`'s and are threaded through per pair.
- **Output**: each saved `out/<model-slug>/<page>.md` path on stdout in
  page-then-model order (an already-present output is listed too); a one-line
  summary on stderr. The per-pair `ocr` / quarantine records are **`ocr-page`'s** —
  `ocr-batch` writes no manifest record of its own.
- **Idempotent, and cheap on re-run.** A pair whose `out/<model>/<page>.md`
  already exists is skipped **without re-hitting the server and without waiting a
  recovery gap** (a skip is not a server hit) — re-running the grid to fill in
  only the missing pairs stays fast.
- **Never aborts, never crashes** (rule 02). A pair `ocr-page` quarantines
  (server unreachable after retries, or an unknown `--model`) is simply omitted
  from the returned paths; the batch continues to the remaining pairs. An empty
  or all-cached directory does nothing and exits 0.
- **Requires** `curl` on `$PATH` and a vision server (LM Studio) already up — same
  precondition as `ocr-page`; `ocr-batch` does not bring the server up.

### Examples

```bash
# Happy path — OCR every page of one paper with every registered model
uv run render-pdf files/Spaced_Repetition_and_Long-Term_Retention.pdf   # -> pages/<stem>/pNNNN.png
uv run ocr-batch pages/Spaced_Repetition_and_Long-Term_Retention
#   -> out/qwen_qwen3-vl-4b/p0001.md
#      out/deepseek-ocr/p0001.md
#      out/qwen_qwen3-vl-4b/p0002.md ...        (page-then-model order)
#   -> manifest: one ocr-page `ocr` record per pair (stage:"ocr-page")

# Restrict the grid to a single model, with a shorter recovery gap
uv run ocr-batch pages/Attention_Is_All_You_Need --model qwen/qwen3-vl-4b --gap 8

# Re-run fills only the missing pairs — the already-saved ones skip (no server hit)
uv run ocr-batch pages/Attention_Is_All_You_Need
#   -> the existing paths are printed again; the server is not re-contacted for them
```

`ocr-batch` sits between `render-pdf` (its input pages) and the scoring steps:
its `out/<model>/<page>.md` grid is exactly what `score-ocr` / `score-gold` score
and `ocr-report` aggregates. It drives **one** page directory (one paper); a
corpus across every paper's directory is a thin wrapper deferred to a later story
(see `DEVLOG.md`).

---

## `score-ocr` — score one OCR output on reference-free defect metrics (US21)

The third step of the OCR-model bench: score **one** saved OCR output
(`out/<model>/<page>.md` from `ocr-page`) on cheap deterministic **defect**
metrics that need **no gold reference**. It is the everyday, offline scoring
tier — point it at any model's output for any page and get one `scores.jsonl`
row, no hand-corrected reference required (that is US22's gold tier). Each metric
is one deterministic function = one scored dimension (rule 02).

```
uv run score-ocr <output.md> [--scores scores.jsonl] [--manifest manifest.jsonl]
```

- **Argument**: the saved `output` Markdown (validated up front — a missing file
  exits 2). The `(model, page)` key is read straight off the path:
  `out/<model>/<page>.md` → `model` = the slug dir, `page` = the stem.
- **Options**: `--scores` (the append-only results log; default `scores.jsonl`),
  `--manifest` (the US20 manifest to join per-call fields from, and to quarantine
  to; default `manifest.jsonl`).
- **Output**: a `<model>/<page> -> <scores>` note on stdout, plus one appended
  `scores.jsonl` row carrying every reference-free dimension **joined** with the
  per-call fields `ocr-page` recorded (`host`, `finish_reason`, `latency`,
  `completion_tokens` — `host` travels with the row so a mixed-machine
  `scores.jsonl` stays attributable, since `latency` is machine-dependent):
  - `dup_pct` — percentage of substantive lines that repeat an earlier one (the
    metric that flagged `unlimited-ocr`'s 95 % loop); markdown rules (`---`) and
    blank lines are excluded so legitimate boilerplate does not inflate it. When a
    model emits the whole page on **one line** (no newlines), it falls back to
    sentence segmentation, so an intra-line repetition loop is still caught rather
    than scoring a false 0.
  - `hyphen_artifacts` — count of `word- word` dehyphenation breaks (the
    `"low- quality"` leak that separated `deepseek-ocr@8bit` from qwen).
  - `citation_groups` — count of inline numeric citation lists (`[51,53,75,82]`),
    so a model that *drops* citations scores lower than one that keeps them.
  - `cjk_present` — whether any CJK/IPA codepoint survived (the reads-the-language
    signal).
- **Quarantine, not a crash** (rule 02). An output it cannot read (e.g. a
  non-UTF-8 file) lands in the manifest (`stage: "score-ocr"`, a `reason`) and the
  step exits **cleanly (exit 0)** — the batch still finishes.
- **Append-only log.** `scores.jsonl` is a stream like `manifest.jsonl`: a re-run
  **appends** another row for the same (model, page) rather than skipping (the
  aggregator, US23, takes the last row per key). This is *not* the file-idempotent
  skip the saved-artifact steps use — there is no per-target file to test for.

### Examples

```bash
# Happy path — score qwen's page-1 output; appends one scores.jsonl row
uv run score-ocr out/qwen_qwen3-vl-4b/p0001.md
#   -> stdout: qwen_qwen3-vl-4b/p0001 -> scores.jsonl
#   -> scores.jsonl: {"model":"qwen_qwen3-vl-4b","page":"p0001","dup_pct":0.0,
#        "hyphen_artifacts":0,"citation_groups":0,"cjk_present":false,
#        "host":"mac-mini.local","finish_reason":"stop","latency":9.378,"completion_tokens":167}

# The same page's DeepSeek output is just a different output path. A fluent
# hallucination shows up here as a runaway completion_tokens (2301 vs 167),
# joined from the manifest — the reference-free signal the bench ranks on.
uv run score-ocr out/deepseek-ocr/p0001.md

# An unreadable output quarantines cleanly (a page PNG mistakenly named .md)
uv run score-ocr out/deepseek-ocr_4bit/p0009.md
#   -> stderr: quarantined (see manifest.jsonl): out/deepseek-ocr_4bit/p0009.md
#   -> manifest: {"stage":"score-ocr","page":"p0009","model":"deepseek-ocr_4bit",
#                 "reason":"unreadable output (UnicodeDecodeError): …"}
```

## `score-gold` — score a model against an OmniDocBench gold subset (US22)

The **gold-referenced accuracy** tier of the OCR bench, complementary to
`score-ocr`'s reference-free defect tier. Where `score-ocr` ranks models by
*fewest defects* with no reference, `score-gold` scores each model's saved OCR
output against **OmniDocBench**'s gold annotations with its official per-element
metrics — so "which model is most *faithful*" becomes a reproducible number, no
hand-labeling. Every metric is a deterministic comparison to the gold; **no LLM
judge** is ever called.

The gold set is **filtered to the pipeline's target distribution** — only
`data_source=academic_literature`, `layout=double_column`,
`language∈{english,en_ch_mixed}` pages (the two-column, embedded-CJK papers this
pipeline converts); newspapers, receipts, handwriting, and single-column pages
are dropped.

> **The dataset is not vendored.** OmniDocBench is research-only / non-commercial
> (license verified at build time), so you supply the annotation JSON and page
> images from your own local download (`opendatalab/OmniDocBench` on HuggingFace).
> OCR the gold page images with `ocr-page` first (its outputs are this step's
> input), then point `score-gold` at the annotation file.

```
uv run score-gold <annotations.json> <model> [--out-dir out] [--scores scores.jsonl] [--manifest manifest.jsonl]
```

- **Arguments**: `annotations` (the OmniDocBench annotation JSON — validated up
  front; a missing file exits 2, and a file that is not a JSON list of pages
  exits 2 with a clear message, never a traceback) and `model` (a registered
  model id, e.g. `qwen/qwen3-vl-4b`).
- **Options**: `--out-dir` (where `ocr-page` saved the outputs, `out/<model>/`;
  default `out`), `--scores` (the append-only results log; default
  `scores.jsonl`), `--manifest` (where un-OCR'd / unreadable pages quarantine;
  default `manifest.jsonl`).
- **What it does** (classify-then-dispatch, rule 02): loads the annotations,
  keeps only the in-subset pages, and for each scores the model's saved output at
  `out/<model-slug>/<image-stem>.md` — reusing US20's idempotent cache, so a
  re-run re-scores from stored outputs without re-hitting the flaky server. One
  metric is dispatched per annotation type the page carries:
  - `text_edit_distance` — normalized edit distance of the model's text to the
    gold text (**0.0** = perfect, higher = worse; the model's `<table>` HTML is
    stripped first so a table is not double-counted here).
  - `teds` — Tree-Edit-Distance-based Similarity of the model's table to the gold
    table (**1.0** = perfect structure + contents, → 0 as it degrades). A gold
    table the model omitted scores a real `0.0`.
  - Each row is tagged `"gold": true`, distinguishing it from `score-ocr`'s
    reference-free rows in the shared `scores.jsonl`.
- **Not-applicable, never a false zero** (AC4). A page missing a type records
  that metric as `null` (e.g. `teds: null` on a text-only page), *not* `0.0` — a
  false zero would poison the model's average.
- **Quarantine, not a crash** (rule 02). A selected page whose output has not been
  OCR'd yet, or an unreadable output, lands in the manifest
  (`stage: "score-gold"`, a `reason`) and the step exits **cleanly** — the batch
  still finishes.
- **Append-only log**, exactly like `score-ocr`: a re-run appends another row per
  (model, page); the aggregator (US23) takes the last row per key.

### Examples

```bash
# Happy path — score qwen against every in-subset gold page (outputs already
# produced by ocr-page under out/qwen_qwen3-vl-4b/)
uv run score-gold OmniDocBench.json qwen/qwen3-vl-4b --out-dir out
#   -> stdout: scored 37 gold page(s) for qwen/qwen3-vl-4b -> scores.jsonl
#   -> scores.jsonl: {"model":"qwen_qwen3-vl-4b","page":"acad_0007","gold":true,
#        "text_edit_distance":0.0652,"teds":1.0}   # a text+table page
#        {"model":"qwen_qwen3-vl-4b","page":"acad_0012","gold":true,
#        "text_edit_distance":0.041,"teds":null}   # text-only: table n/a

# Compare a second model on the same gold — just a different model id / out dir
uv run score-gold OmniDocBench.json deepseek-ocr --out-dir out

# Quarantine — a selected gold page not yet OCR'd exits cleanly, no scores row
uv run score-gold OmniDocBench.json qwen/qwen3-vl-4b --out-dir out
#   -> manifest: {"stage":"score-gold","page":"acad_0007","model":"qwen_qwen3-vl-4b",
#                 "reason":"no model output at out/qwen_qwen3-vl-4b/acad_0007.md (run ocr-page first)"}
```

`render-pdf` → `ocr-page` → `score-ocr` (reference-free) and `score-gold`
(gold-referenced) together fill `scores.jsonl`, which US23's `ocr-report` will
aggregate into the model comparison scorecard.

### Getting the gold data (no AI, no full 1.6 GB pull)

OmniDocBench is **research-only / non-commercial**, so it is not vendored — you
download it once from HuggingFace (`opendatalab/OmniDocBench`) into a gitignored
dir (`files/` is ignored). You only need the pages the subset filter selects
(45 of 1651 — academic, double-column, en/mixed), so fetch the 40 MB annotation
JSON, compute the in-subset image list with the *same* `matches_subset` filter
`score-gold` uses, and pull only those images (~40 MB, not ~1.6 GB):

```bash
mkdir -p files/omnidocbench/images
HF=https://huggingface.co/datasets/opendatalab/OmniDocBench/resolve/main

# 1. the annotation JSON (a list of 1651 page objects)
curl -sSL -o files/omnidocbench/OmniDocBench.json "$HF/OmniDocBench.json"

# 2. the in-subset image filenames, via the shipped filter (reproducible, no AI)
uv run python -c "
import json
from paper_degist.score_gold import matches_subset
pages = json.load(open('files/omnidocbench/OmniDocBench.json'))
subset = [p for p in pages if matches_subset(p['page_info']['page_attribute'])]
print('\n'.join(p['page_info']['image_path'] for p in subset))
" > files/omnidocbench/subset_images.txt
wc -l < files/omnidocbench/subset_images.txt          # -> 45

# 3. pull only those images (note the trailing newline read, so the last line isn't dropped)
while IFS= read -r img || [ -n "$img" ]; do
  curl -sSL -f -o "files/omnidocbench/images/$img" "$HF/images/$img"
done < files/omnidocbench/subset_images.txt
```

Then OCR one or a few of the images and gold-score them — no need to process all
45 for a smoke test:

```bash
# smoke-test the whole image -> ocr -> gold-score path on ~2 pages
for img in $(head -2 files/omnidocbench/subset_images.txt); do
  uv run ocr-page "files/omnidocbench/images/$img" qwen/qwen3-vl-4b --out-dir out
done
uv run score-gold files/omnidocbench/OmniDocBench.json qwen/qwen3-vl-4b --out-dir out
# score-gold quarantines the 43 pages you did NOT OCR ("run ocr-page first") and
# scores the 2 you did — exit 0, batch still finishes.
```

`score-gold` reads **both** table forms a model emits — inline HTML `<table>`
blocks (DeepSeek-OCR) and GFM pipe tables (`| a | b |`, what qwen emits, which
are converted to HTML before the TEDS compare) — so `teds` reflects a
transcribed table regardless of syntax. (Residual limits in DEVLOG: a pipe table
cannot carry `colspan`/`rowspan`, and an unescaped `|` inside a LaTeX cell
mis-splits.)

`score-ocr` composes after `ocr-page` (whose `out/<model>/<page>.md` output it
scores, joining the manifest row `ocr-page` wrote for the same call). It scores
one output per run; the gold-referenced accuracy tier is US22 (`score-gold`), and
aggregating a cross-model scorecard from these rows is US23 (`ocr-report`).

## `ocr-report` — aggregate the stored scores into one scorecard (US23)

The **aggregation** tier of the OCR bench: `score-ocr` (US21) and `score-gold`
(US22) fill `scores.jsonl` with one row per (model, page); on their own they are
a pile of rows. `ocr-report` summarizes them into a single **models × dimensions
scorecard** — one row per model, one column per scored dimension, plus a short
verdict per model — so comparing models is one regenerated report, not a manual
re-read of raw outputs. It **reads only the stored scores**: no model call, no
score computed here, so it runs offline and regenerates in seconds.

```
uv run ocr-report [scores.jsonl] [--report report.md] [--manifest manifest.jsonl]
```

- **Argument**: `scores` — the results log written by `score-ocr` / `score-gold`
  (default `scores.jsonl`; a missing file exits 2, and a non-text file — the
  wrong path, e.g. a PDF — exits 2 with a clear message, never a decode traceback).
- **Options**: `--report` (where the Markdown scorecard is written; default
  `report.md`), `--manifest` (where unplaceable records quarantine; default
  `manifest.jsonl`).
- **What it does** (classify-then-dispatch, rule 02): groups the rows by model and
  by dimension. **Both axes are derived from the records, never hard-coded** — a
  newly scored model or a new dimension appears with no code change (register +
  score + regenerate). Each dimension is summarized by a summarizer chosen from
  the *kind* of its values:
  - count-like ints (`hyphen_artifacts`, `citation_groups`, `completion_tokens`)
    → a representative **median** (one busy page does not skew it);
  - ratio/score numbers (`dup_pct`, `text_edit_distance`, `teds`, `latency`)
    → their **mean**;
  - categorical strings/bools (`finish_reason`, `cjk_present`, `host`) → their
    **dominant value**.
  - The `host` column (the machine that produced each row) makes a mixed-machine
    `scores.jsonl` visible in the scorecard, but the report does **not** yet
    segment `latency` by host — a scorecard pooled across machines still compares
    `latency` measured on different hardware (see the DEVLOG flag; host-aware
    aggregation is deferred to its own US23 follow-up).
- **Composite `accuracy` column** — a derived, higher-is-better roll-up of the two
  gold-referenced accuracy dimensions onto one 0–1 axis: `mean(teds, 1 −
  text_edit_distance)` (`teds` is already higher-is-better; `text_edit_distance` is
  flipped so a lower distance reads as a higher score). It is **computed** from
  those two aggregates, not a stored `scores.jsonl` dimension, so it renders as a
  trailing column after them and is ranked in the verdict. A model missing either
  half (e.g. no gold table, so no `teds`) shows a `—` gap, never a half-score.
- **Gap, never a false zero** (AC4). A (model, dimension) cell with no measurement
  — a metric that was not-applicable (`teds: null` on a text-only page) or a model
  that was never scored on that dimension — renders an explicit `—`, *not* `0`
  (a false zero reads as "scored badly" rather than "not measured").
- **Deterministic** (AC2). The report is a pure function of `scores.jsonl` (sorted
  axes, no timestamp in the body), so regenerating with no new scores is
  byte-identical — the artifact is stable to diff. Re-scored rows collapse
  **last-wins** per (model, page, gold-tier), so a re-run does not double-weight a
  page.
- **Verdict**: a per-model line naming the directional dimensions that model leads
  (strictly best; ties lead nobody) — including the derived `accuracy` composite.
  The dimensions are presented side by side; a single weighted ranking *across all*
  dimensions is still deferred (see DEVLOG / the story's "Later stages"), the
  `accuracy` roll-up being scoped to the two gold-accuracy metrics only.
- **Quarantine, not a crash** (rule 02). A record with no `model` cannot be placed
  in the grid → it lands in the manifest (`stage: "ocr-report"`) and is skipped;
  a malformed (non-JSON) line is skipped; the report still generates.

### Examples

```bash
# Happy path — aggregate every stored score into the scorecard
uv run ocr-report scores.jsonl --report report.md
#   -> stdout: scorecard -> report.md
#   -> report.md:
#      # OCR Model Scorecard
#
#      | Model | citation_groups | dup_pct | teds | text_edit_distance |
#      | --- | --- | --- | --- | --- |
#      | deepseek-ocr | 0 | 0 | 0.91 | 0.4 |
#      | qwen_qwen3-vl-4b | 6 | 0 | — | 0.05 |     # teds n/a: its gold page had no table
#
#      ## Verdict
#
#      - **deepseek-ocr** — leads: teds
#      - **qwen_qwen3-vl-4b** — leads: citation_groups, text_edit_distance

# Deterministic — regenerating with no new scores is byte-identical
uv run ocr-report scores.jsonl --report report.md   # same bytes as the run above

# A newly scored model needs no code change — just its rows in scores.jsonl
uv run score-ocr out/unlimited-ocr_v3/p0001.md      # register + score it (US20/US21)
uv run ocr-report scores.jsonl --report report.md   # it appears as a new row + verdict

# Quarantine — a score row with no model can't be placed; report still generates
uv run ocr-report scores.jsonl --manifest manifest.jsonl
#   -> manifest: {"stage":"ocr-report","record":{"page":"p0001","dup_pct":3.0},
#                 "reason":"score record has no model"}
```

`ocr-report` is the **last step of the OCR bench** and closes the
`render-pdf → ocr-page → score-ocr / score-gold → ocr-report` chain: it turns the
accumulated `scores.jsonl` into the comparison that informs which model the PDF
path (US3) should adopt. Adding a model to the comparison is pure data — score it,
regenerate — never a code edit.

---

## `embed-text` — embed one text with one registered local model (US24)

The similarity primitive for the abstract filter (US26): send **one** text to
**one** named embedding model over the same stable transport as `ocr-page` and
save its vector. It is the near-exact sibling of `ocr-page` — same LM Studio
server, same **registry**, same fixed-encoded transport (rule 02): the JSON body
is built in Python and POSTed with `curl --data @body.json`, **sequentially**,
with a recovery gap and **retry-on-5xx** — only the `/v1/embeddings` endpoint
instead of chat. Models are a **registry**; a new model is one
`(query-prefix, document-prefix)` entry, not a code branch.

```
uv run embed-text <model-id> [text-file] [--role query|document]
                  [--out-dir out] [--endpoint URL] [--attempts 3] [--gap 7.0]
                  [--manifest manifest.jsonl]
```

- **Arguments**: a **registered** `model` id (see the registry below), and the
  `text-file` to embed (validated up front — a missing file exits 2). With the
  file omitted, the text is read from **stdin**, so the step is pipeable.
- **`--role`** selects which registry prefix is applied: `document` (default —
  a passage/abstract, `search_document: …`) or `query` (a topic/query string,
  `search_query: …`). Getting the role wrong silently degrades ranking, so it is
  recorded in every manifest row and folded into the cache key.
- **Options**: `--out-dir` (root the vector lands under; default `out/`),
  `--endpoint` (the embeddings URL; default
  `http://localhost:1234/v1/embeddings` — LM Studio), `--attempts` (max POSTs
  before quarantine; default `3`), `--gap` (recovery seconds between retries;
  default `7.0`), `--manifest`.
- **Output**: the saved vector path on stdout —
  `out/embeddings/<model-slug>/<hash>.json`, where `<hash>` is a SHA-256 of
  `(model, role, text)` — plus an `embed` provenance record in the manifest
  (`stage`, `model`, `role`, `text_hash`, `dims`, `latency`). The JSON file holds
  `{model, role, dims, embedding}`.
- **Registered models** (the `(query, document)` prefix registry):
  - `nomic-embed-text-v1.5` — `search_query: ` for a query, `search_document: `
    for a passage (its documented task prefixes; a 768-dim vector).
- **Quarantine, not a crash** (rule 02). Two cases land in the manifest and exit
  cleanly (exit 0):
  - `unknown model: '…' not in registry` — the model id is not registered; the
    network is **never touched** (distinct from a server error).
  - `server unreachable after N attempts: …` — the endpoint 5xx'd / was
    unreachable through every retry; the curl diagnostic is included.
- **Idempotent.** A `(model, role, text)` whose `out/embeddings/<model>/<hash>.json`
  already exists is skipped — the model call is the expensive, flaky resource, so
  a re-run **never** re-hits the server and appends **no** manifest record.
- **Requires** `curl` on `$PATH` and a model server (LM Studio) already up with
  the embedding model loadable — bringing the server up is the operator's job (as
  `browser-up` is for Chrome), not this step.

### Examples

```bash
# Happy path — embed an abstract as a document; vector saved under out/embeddings/
uv run embed-text nomic-embed-text-v1.5 abstract.txt --role document
#   -> out/embeddings/nomic-embed-text-v1.5/71502e4f….json  (path printed)
#   -> manifest: {"stage":"embed-text","model":"nomic-embed-text-v1.5","role":"document",
#                 "text_hash":"71502e4f…","dims":768,"latency":0.147}

# Embed a topic string as a query (the other prefix) — piped in on stdin
echo "spaced repetition and long-term retention" \
  | uv run embed-text nomic-embed-text-v1.5 --role query

# An unregistered model quarantines without touching the network
uv run embed-text some-unregistered-embed abstract.txt
#   -> stderr: quarantined (see manifest.jsonl): some-unregistered-embed + role=document
#   -> manifest: {"stage":"embed-text","model":"some-unregistered-embed","role":"document",
#                 "text_hash":"7909048f…","reason":"unknown model: 'some-unregistered-embed' not in registry"}
```

`embed-text` is the primitive the US26 abstract filter composes: it embeds the
topic once as a `query` and each candidate abstract as a `document`, then ranks
by cosine similarity — a deterministic, offline signal, no LLM in the loop. It
does one text per run; the batch driver that walks an abstract list, keeping the
sequential-with-gap rule, is that filter's job.

## `discover` — find candidate papers by topic (US25)

The pipeline's **upstream front**: given a topic query, search a free scholarly
API and emit each candidate paper (with its abstract) as one JSONL record — a
drop-in to the filter → fetch chain, so you stop pasting URLs by hand. It is
deliberately **coarse and high-recall** (find everything that might be relevant);
narrowing is US26's job. Sources are a **registry**, not a per-source branch
(rule 02): a new API is one adapter entry.

```
uv run discover <query> [--source arxiv|s2|openalex] [--max-results 25]
                [--s2-api-key KEY] [--email you@example.com]
                [--manifest manifest.jsonl]
```

- **Argument**: the topic `query` (quote it — it is one string).
- **`--source`** selects the adapter: `arxiv` (default — no key, an Atom feed,
  100 % abstract-present), `s2` (Semantic Scholar — a JSON API that adds a
  `tldr` one-line summary US26 can pre-filter on), or `openalex` (US29 — keyless,
  cross-field/CC0, and carries a directly fetchable OA `pdf_url` when one exists).
  The phase-2 bake-off made arXiv the default: keyless and reliable, where S2's
  free tier **without a key is rate-limited to 429** (see the story). An unknown
  source (e.g. `pubmed`) quarantines **offline**, without touching the network.
- **Options**: `--max-results` (cap on the first page requested; default `25`),
  `--s2-api-key` (optional Semantic Scholar key, or the `S2_API_KEY` env var —
  raises the rate limit), `--email` (contact email for OpenAlex's faster **polite
  pool**, or the `OPENALEX_EMAIL` env var — see below), `--manifest`.
- **`openalex` specifics** (US29): OpenAlex is **keyless**. `--email` /
  `OPENALEX_EMAIL` is *politeness*, not access — supplying it uses the faster
  polite pool; **omitting it still runs** on the common pool and only **warns**
  (contrast S2, where a missing key means a 429). The adapter reconstructs the
  abstract from OpenAlex's `abstract_inverted_index` (a `{token: [positions]}`
  map, never plain text), sorts by `cited_by_count:desc` (most-cited first), and
  emits two extra fields when the record carries them: `pdf_url` (an open-access
  copy, straight into `fetch-one`) and `cited_by`.
- **Output**: one JSONL record per hit on stdout, in a **common schema** across
  sources — `title`, `authors`, `abstract`, `abstract_present`, `url`,
  `published`, `source`, `source_id`, plus `doi`, `tldr`, `pdf_url` and
  `cited_by` **only when the record carries them**. A run also appends a
  `discover` provenance record to the manifest (`stage`, `source`, `query`,
  `result_count`).
- **No abstract is kept, not dropped** (AC3). A hit with no abstract is still
  emitted with `abstract: null` and `abstract_present: false`, so US26 can drop
  it cheaply — discovery casts wide; filtering is downstream.
- **Quarantine, not a crash** (rule 02). Three cases land in the manifest with a
  **distinct** reason and exit cleanly (exit 0):
  - `unknown source: '…' not in registry` — the `--source` is not an adapter; the
    network is **never touched**.
  - `empty-result: the search returned no candidates` — the query matched nothing.
  - `api-error: <Type>: …` — the API errored / rate-limited (e.g. S2's keyless
    `429`); the diagnostic is included.

### Examples

```bash
# Happy path — search arXiv for a topic; each hit is one JSONL line
uv run discover "sparse mixture-of-experts routing" --source arxiv --max-results 5
#   -> {"title":"Task-Conditioned Routing Signatures …","authors":[…],
#       "abstract":"Sparse Mixture-of-Experts …","abstract_present":true,
#       "url":"http://arxiv.org/abs/2510.…","published":"2025-…","source":"arxiv",
#       "source_id":"2510.…"}    (× up to --max-results)
#   -> manifest: {"stage":"discover","source":"arxiv","query":"sparse …","result_count":5}

# Pipe the candidates straight into the fetch chain (parse the url field)
uv run discover "graph neural network expressivity" --source arxiv \
  | python3 -c 'import sys,json; [print(json.loads(l)["url"]) for l in sys.stdin]' \
  | uv run fetch-one

# Semantic Scholar (needs a key for a usable rate) — carries a tldr signal
uv run discover "CRISPR base editing off-target effects" --source s2 --s2-api-key "$S2_API_KEY"

# OpenAlex (keyless, CC0) — reconstructs the inverted-index abstract, sorts by
# citations, and carries an OA pdf_url up front. --email uses the polite pool.
uv run discover "graph neural networks for molecular property prediction" \
  --source openalex --email you@example.com --max-results 5
#   -> {"title":"Neural Message Passing for Quantum Chemistry","authors":[…],
#       "abstract":"Supervised learning on molecules …","abstract_present":true,
#       "url":"https://doi.org/10.48550/arxiv.1704.01212","published":"2017-04-04",
#       "source":"openalex","source_id":"W2606780347","doi":"10.48550/arxiv.1704.01212",
#       "pdf_url":"https://arxiv.org/pdf/1704.01212","cited_by":3010}    (× --max-results)

# The OA pdf_url short-circuits resolve-oa — fetch the open copy directly
uv run discover "neural message passing for quantum chemistry" --source openalex \
  --email you@example.com \
  | python3 -c 'import sys,json
for l in sys.stdin:
    r=json.loads(l)
    if r.get("pdf_url"): print(r["pdf_url"]); break' \
  | xargs -r -I{} uv run fetch-one "{}"

# OpenAlex with no email still runs (common pool) — only warns
uv run discover "sparse mixture-of-experts routing" --source openalex
#   -> stderr: warning: no OpenAlex contact email (--email / OPENALEX_EMAIL); …

# An unknown source quarantines without touching the network
uv run discover "single-cell RNA sequencing" --source pubmed
#   -> stderr: quarantined (see manifest.jsonl): pubmed + 'single-cell RNA sequencing'
#   -> manifest: {"stage":"discover","source":"pubmed","query":"single-cell …",
#                 "reason":"unknown source: 'pubmed' not in registry"}
```

`discover` is the entry point the US26 abstract filter composes: it emits a
wide-net candidate list (one source per run), and the filter narrows it by
abstract similarity. Merging both sources into one deduped union (reusing US14's
DOI normalization) is a deferred driver built on top of this step, not baked in.

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

# 5. For bot-walled 403s (blocked_by), drain them through the browser lane in one
#    warm session, then convert whatever it recovered:
endpoint=$(uv run browser-up)
uv run recover-blocked manifest.jsonl --cdp "$endpoint" | while read -r p; do
  case "$p" in *.html) uv run convert-html "$p" ;; esac
done
```

Inspect `manifest.jsonl` for everything that could not be handled
automatically — each line names the `stage`, the input, and the `reason`, which
tells you (or the next code branch) exactly what to do next.
