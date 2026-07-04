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
  `latency`, `finish_reason`, `completion_tokens`).
- **Registered models** (the `(prompt, post-processor)` registry):
  - `qwen/qwen3-vl-4b` — a plain "Convert the document to markdown." instruction;
    output is unwrapped from the ```` ```markdown ```` fence it comes in.
  - `deepseek-ocr` — the `<|grounding|>Convert the document to markdown.` prompt
    (the literal `<image>` token **omitted**, or LM Studio 400s on a double
    image); the grounding markup is decoded to plain Markdown.
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
#                 "latency":20.8,"finish_reason":"stop","completion_tokens":167}

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
(US21–23). It does one `(page, model)` per run; a batch driver that walks a page
directory across every registered model — keeping the sequential-with-gap rule —
is the US23 report driver, composed from this step.

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
  per-call fields `ocr-page` recorded (`finish_reason`, `latency`,
  `completion_tokens`):
  - `dup_pct` — percentage of substantive lines that repeat an earlier one (the
    metric that flagged `unlimited-ocr`'s 95 % loop); markdown rules (`---`) and
    blank lines are excluded so legitimate boilerplate does not inflate it.
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
#        "finish_reason":"stop","latency":9.378,"completion_tokens":167}

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

`score-ocr` composes after `ocr-page` (whose `out/<model>/<page>.md` output it
scores, joining the manifest row `ocr-page` wrote for the same call). It scores
one output per run; the gold-referenced accuracy tier is US22 (`score-gold`), and
aggregating a cross-model scorecard from these rows is US23 (`ocr-report`).

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
