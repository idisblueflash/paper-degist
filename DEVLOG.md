# Dev log — deferred flags to revisit

Small, non-blocking issues noticed during development. Each names the code
location, the case not yet handled, and the trigger that should make us fix it.

## parse_url — trailing-punctuation stripping is heuristic

- **Where:** `src/paper_degist/parse_url.py` (`_URL_RE` + `rstrip(".,;")`).
- **Case not handled:** the regex captures up to whitespace or `)`, then strips
  trailing `.,;`. This is correct for URLs that end a sentence, but would wrongly
  strip a trailing `.`/`;`/`,` that is a *real* path or query character. Markdown
  links wrapped in `<...>` and URLs containing a legitimate closing `)` are also
  not handled.
- **Trigger to fix:** the first time a real input URL ends in one of these chars,
  or a `manifest.jsonl` entry shows a mangled URL. Add a failing scenario/unit
  test with that URL, then tighten the regex.
- **Status:** RESOLVED (PR #1 review). `_URL_RE` now matches generously
  (angle-brackets excluded, `re.IGNORECASE`, left-boundary lookbehind against
  embedded schemes) and `_trim_trailing` strips prose punctuation plus only
  *unbalanced* wrapper parens, so `paper_(v2).pdf` survives while `[t](url)`
  loses its wrapper. Balanced-paren, mixed-case, and embedded-scheme cases are
  pinned by unit tests. One residual heuristic remains: a trailing `.` after a
  path (`.../a.`) is still treated as sentence punctuation and stripped — an
  accepted policy, documented by `test_strips_trailing_prose_punctuation_*`.

## fetch_one — redirect hop cap (US2 AC5) not explicitly bounded

- **Where:** `src/paper_degist/fetch_one.py::_default_fetch`.
- **Case not handled:** AC5 says "follow it (cap the hops)". `_default_fetch`
  passes `follow_redirects=True` to `httpx.get`, which follows up to httpx's
  own default `max_redirects` (20) — the hop cap is implicit, not a stated
  policy of ours, and the re-classify-final-response behavior is untested
  (tests inject a fake fetch, so no redirect chain is exercised).
- **Trigger to fix:** when a real input redirects (or loops) and we want a
  tighter/explicit cap, or when adding an integration test that exercises a
  live redirect. Set an explicit `httpx.Client(max_redirects=...)` and add a
  scenario then.
- **Status:** OPEN.

## fetch_one — JS-rendered HTML may be saved as a thin/empty shell

- **Where:** `src/paper_degist/fetch_one.py::classify` (the `text/html` branch)
  and `_default_fetch`.
- **Case not handled:** `_default_fetch` does a plain `httpx.get` with no JS
  execution. For a client-rendered SPA (Next.js/React/etc.), the response can be
  a near-empty shell whose real content only appears after client-side
  hydration. `classify` sees a valid `text/html` body and saves it as a
  legitimate `.html`, so a content-thin page passes as success rather than being
  quarantined. Observed live on `https://keymagine.app/keyword-method` — a
  Next.js app (`_next/static/...`); that particular page did carry its content
  inline, so it was fine, but the shape is the risk.
- **Trigger to fix:** the first time the convert step yields near-empty Markdown
  from a saved `.html`, or a real input SPA returns a hollow shell. Add an
  "HTML too thin" signal (e.g. text-density / body-length threshold, or a
  `<div id="__next"></div>`-empty check) that quarantines to `manifest.jsonl`
  with that reason, driven by a failing test on a captured hollow-shell fixture.
  Now specified as US 5 AC2 in `user-stories.md`.
- **Status:** ADDRESSED at the convert stage (US 5). `convert_html` measures the
  extracted Markdown's non-whitespace character count and quarantines anything
  below `_MIN_CONTENT_CHARS` (200) to `manifest.jsonl` with reason
  `"HTML too thin"` — a hollow `<div id="__next"></div>` yields 0 non-ws chars,
  a real paper thousands (the captured `keyword-method.html` sample: 7623).
  `fetch_one` still *saves* the shell (it cannot tell inline-rendered from
  hollow without converting); the thin-shell judgment now lives one stage later
  where the Markdown makes it cheap and deterministic.

## convert_html — density threshold is a fixed char count, not a ratio

- **Where:** `src/paper_degist/convert_html.py` (`_MIN_CONTENT_CHARS`,
  `_content_chars`).
- **Case not handled:** the "too thin" signal is an absolute non-whitespace
  character count (200). A genuinely short-but-real note under 200 chars would
  be quarantined as a false positive, and a hollow shell that happens to inline
  200+ chars of boilerplate nav/footer would pass. A text-density *ratio*
  (content chars / raw HTML bytes) or a boilerplate strip would be more robust.
- **Trigger to fix:** the first real paper wrongly quarantined as thin, or a
  hollow shell wrongly saved. Add the offending fixture as a failing test, then
  switch to a ratio or add a boilerplate-strip pass.
- **Status:** OPEN.

## convert_html — non-UTF-8 HTML is quarantined, not transcoded

- **Where:** `src/paper_degist/convert_html.py::convert_html` (the
  `read_text(encoding="utf-8")` guard).
- **Case not handled:** a file whose bytes are not valid UTF-8 (e.g. a page
  served as `charset=iso-8859-1`) would have crashed with `UnicodeDecodeError`;
  it is now caught and quarantined with reason `"undecodable HTML (not UTF-8)"`
  so the batch finishes (rule 02: never crash). We do **not** yet sniff the
  declared charset or transcode — a real Latin-1 paper is quarantined rather
  than converted.
- **Trigger to fix:** the first real input quarantined for this reason. Add a
  branch that reads the `<meta charset>` / HTTP charset and decodes with it
  (falling back to `errors="replace"`), driven by a failing test on a captured
  non-UTF-8 fixture.
- **Status:** OPEN.

## convert stage — extension dispatcher (.pdf vs .html) not built yet

- **Where:** the convert stage as a whole; only `convert_html` (the `.html`
  branch) exists.
- **Case not handled:** US 5's case handling says the convert stage dispatches
  by file extension — `.pdf` → the PDF path (US 3 + US 4), `.html` →
  `convert_html` — both converging on `files/<name>.md`. Only the `.html` branch
  is built; there is no top-level `convert` entry point that classifies by
  extension and dispatches, because the PDF path (US 3/US 4) does not exist yet.
- **Trigger to fix:** when US 3/US 4 land. Add a `convert` step that classifies
  by suffix and dispatches to `convert_html` or the PDF path, mirroring
  `fetch_one`'s Content-Type dispatch; quarantine unknown extensions.
- **Status:** OPEN (top-level dispatcher). Mitigated: `convert_html` now
  classifies its *own* input first — a non-`.html`/`.htm` file is quarantined
  (reason `"not an HTML file (unexpected extension …)"`) instead of being
  markdownified into a garbage `.md` (Codex review). So the `.html` handler is
  safe to invoke directly today; the deferred work is only the shared front
  door that routes `.pdf` vs `.html`.

## parse_url CLI — console entry point (`main`) is not unit-tested

- **Where:** `src/paper_degist/parse_url.py::main`, `src/tests/test_parse_url.py`.
- **Case not handled:** tests exercise `parse_url()` directly; `main([...])`,
  stdin input, one-URL-per-line stdout formatting, and error exit codes are
  unguarded. Deferred by the writer in PR #1 review ("let's not touch this from
  now, consider later").
- **Trigger to fix:** when CLI error handling lands (see the CLI-framework
  decision below), or the first CLI-behavior regression. Add `main`/stdin tests
  via `capsys`/`monkeypatch` plus a missing-file case then.
- **Status:** RESOLVED (Typer adoption PR). `src/tests/test_cli.py` drives the
  step's Typer `app` through `typer.testing.CliRunner`: file argument, stdin
  fallback, one-URL-per-line stdout, and the missing-file path (non-zero exit,
  no traceback). The `capsys`/`monkeypatch` plan is moot — `CliRunner` captures
  stdout and exit codes directly.

## CLI framework — adopt Typer project-wide (deferred to next PR)

- **Where:** every step's CLI surface, starting with
  `src/paper_degist/parse_url.py::main` (raw `open(args.file)` emits tracebacks
  for missing/unreadable files — PR #1 finding r3509869286).
- **Decision:** standardize the pipeline's CLI steps on **Typer** (Click under
  the hood) instead of hand-rolling `argparse` + per-step `try/except`. Typer's
  `Path(exists=True, readable=True)` gives early file validation, clean stderr
  messages, and POSIX exit codes for free, and its `CliRunner` makes `main`
  testable — closing both this finding and the untested-`main` item above with
  one convention. Chosen over a stdlib guard because paper-degist is many
  independent CLI steps that all need identical file-in/stdout-out/clean-error
  behavior.
- **Trigger to fix:** the **next PR** (writer's call — keep PR #1 scoped to
  URL-parsing). Add `typer` via `uv add typer`, refactor `parse-url` onto it as
  the pattern the other steps follow, then apply to `fetch`/`convert`/`import`.
- **Status:** RESOLVED (this PR). `typer` added via `uv add`; both existing CLI
  surfaces refactored onto it — `parse_url` (an `@app.command()` with a
  `typer.Argument(exists=True, dir_okay=False, readable=True)` that validates
  the file up front) and the root `paper_degist` signpost (an
  `invoke_without_command` callback). The convention for the remaining steps:
  a module-level `app = typer.Typer(add_completion=False)`, commands using
  `Annotated[..., typer.Argument(...)]` for validation, and a rule-03
  `main(argv=None) -> int` that delegates to `paper_degist._cli.invoke(app,
  argv)` — the single place that runs the app in standalone mode (clean error
  output) and normalizes the raised `SystemExit` into an int (`None`→0,
  non-int payload→1). Apply the same shape to `fetch`/`convert`/`import` as
  they land.

## fetch_one — bare `http 403` was a dead end (now: resolve-oa)

- **Where:** `src/paper_degist/fetch_one.py` (the `status_code >= 400` branch)
  and the new `src/paper_degist/resolve_oa.py`.
- **Case not handled:** a 403 from a Cloudflare-gated host (ResearchGate,
  Academia.edu) told us nothing about whether the paper is reachable for free
  elsewhere; the manifest carried only `"http 403"`.
- **Status:** ADDRESSED by US9. `resolve-oa` takes a failed URL/DOI, recovers a
  DOI, and asks Unpaywall for an open-access PDF URL — printing it (pipe into
  `fetch-one`) or quarantining `"no OA copy (closed access)"`. The real E2E run
  confirmed both: the ResearchGate paper's DOI `10.1191/1362168805lr151oa` came
  back closed, while `10.1371/journal.pone.0000308` resolved to a PLOS PDF that
  `fetch-one` then downloaded (91 KB, 5-page `%PDF-1.4`).

## resolve_oa — title→DOI (Crossref) resolution not built (US9 AC5)

- **Where:** `src/paper_degist/resolve_oa.py::resolve_oa` (the `doi is None`
  branch) and `doi_from`.
- **Case not handled:** a slug-only URL with no embedded DOI (the original
  ResearchGate publication link) is quarantined `"no DOI in input; title→DOI
  lookup not built (route to human/browser)"`. In this session the DOI was
  recovered manually via Crossref's `query.bibliographic` from the URL's title
  slug — that lookup is not yet code, so slug URLs cannot be resolved
  automatically.
- **Trigger to fix:** the first time we want a slug URL resolved without a hand
  lookup. Add a `title_from(url)` slug extractor + a Crossref `title→DOI`
  lookup (mirroring `_unpaywall_lookup`'s injected shape), driven by a failing
  test; feed its DOI into the existing OA dispatch.
- **Status:** RESOLVED by US10. `title_from` extracts the title from the URL
  slug (strips the numeric publication id, `_`→space); `_crossref_title_lookup`
  queries Crossref's `query.bibliographic` and gates the top result through
  `_doi_from_crossref`; `resolve_oa` grew an injected `title_lookup` param whose
  recovered DOI rejoins the existing OA dispatch. The real E2E confirmed it: the
  ResearchGate keyword-method slug now recovers the correct DOI
  `10.1191/1362168805lr151oa` (title overlap 1.0) and returns a precise
  `no OA copy (closed access)` — no longer a bare `no DOI` dead end. Two new
  boundaries surfaced by that run are logged below (same-title-different-record;
  threshold calibration).

## resolve_oa — human / browser-devtools rescue lane not built (US9)

- **Where:** the `resolve-oa` quarantine reasons (`closed access`, `no DOI`).
- **Case not handled:** closed-access and Cloudflare-gated papers are named in
  the manifest but there is no downstream lane that hands them to a person or an
  authenticated Chrome dev-mode session to fetch with real cookies. The manifest
  reason is the routing signal; nothing consumes it yet.
- **Trigger to fix:** when we build the manual/browser rescue step. Read the
  `resolve-oa` manifest records and present them as a work queue (or drive a
  logged-in browser context), quarantining anything still unreachable.
- **Status:** OPEN.

## resolve_oa — single OA source (Unpaywall); OpenAlex/CORE not cross-checked

- **Where:** `src/paper_degist/resolve_oa.py::_unpaywall_lookup`.
- **Case not handled:** the OA verdict comes from Unpaywall alone. A paper Unpaywall
  marks closed but OpenAlex/CORE hosts (repository copies, author self-archives)
  would be a false "closed access". Unpaywall also requires a contact email
  (`--email`/`UNPAYWALL_EMAIL`); a missing/invalid email raises inside the
  lookup and is quarantined as an `"OA lookup error"` (AC6), not a real verdict.
- **Trigger to fix:** the first paper wrongly reported closed that has an OA copy
  elsewhere. Add an OpenAlex/CORE fallback lookup (same injected shape) and take
  the union of OA locations, driven by a failing test.
- **Status:** OPEN.

## resolve_oa — "OA but no PDF link" shares the "closed access" reason

- **Where:** `src/paper_degist/resolve_oa.py::_pdf_url_from_unpaywall` (returns
  `None`) → `resolve_oa` quarantines `"no OA copy (closed access)"`.
- **Case not handled:** a paper Unpaywall marks `is_oa: true` but with no
  `url_for_pdf` in any location (only a landing-page `url`) is now correctly
  *not* returned (Codex review finding 1 — we never print a landing page as if
  it were a PDF). But it quarantines with the same `"closed access"` reason as a
  truly closed paper, which is slightly imprecise: the paper *is* open, it just
  has no direct PDF link (an HTML-only OA landing page).
- **Trigger to fix:** the first OA-but-no-PDF paper we want distinguished (e.g.
  to route it to the HTML convert path via its landing page). Widen the injected
  `oa_lookup` contract to report the sub-case (closed vs OA-no-PDF) and emit a
  distinct reason, driven by a failing test.
- **Status:** OPEN (surfaced + partially addressed by Codex review of US9: the
  landing-page-as-PDF bug is fixed; only the reason precision is deferred).

## fetch_one — URL-basename filename loses query-string names

- **Where:** `src/paper_degist/fetch_one.py::_target_path`.
- **Case not handled:** the filename is the URL *path* basename. The PLOS OA URL
  `.../article/file?id=10.1371/journal.pone.0000308&type=printable` has path
  basename `file`, so the paper saved as `files/file.pdf` — the real identifier
  lives in the `?id=` query, which is dropped. Surfaced by the US9 real E2E run
  (`resolve-oa | fetch-one`). Harmless for a single fetch, but two such URLs
  would collide on `file.pdf`.
- **Trigger to fix:** the first real collision, or the first paper we want named
  by its DOI/query id. Fall back to a query-param (`id`) or the DOI when the
  path basename is generic (`file`, `download`, `pdf`), driven by a failing
  `_target_path` test.
- **Status:** OPEN.

## resolve_oa — title→DOI guard is title-overlap only (same-title ≠ same record)

- **Where:** `src/paper_degist/resolve_oa.py::_doi_from_crossref` (takes only
  `items[0]`, gated by `_title_overlap >= _MIN_TITLE_OVERLAP`).
- **Case not handled:** the confidence guard rejects *low* title-overlap matches
  (truncated slugs, unrelated papers, a conference abstract whose title diverges)
  — its designed job. It does **not** distinguish a *different record that shares
  the exact title*: Crossref's bibliographic query returns preprints, reprints,
  conference abstracts, and F1000/ScienceOpen "peer-review" echo-records that
  echo a paper's title under a different DOI, some even OA. The US10 E2E surfaced
  this concretely — for `"Deep residual learning for image recognition"` the top
  results were a `posted-content` preprint and a **wrong** MDPI `journal-article`
  reprint (`10.3390/app12188972`), with the real CVPR DOI (`10.1109/cvpr.2016.90`)
  only at rank #3; `"Array programming with NumPy"` topped with a `peer-review`
  echo. Because those share the title, the overlap guard passes them — so a
  slug can resolve to a wrong (occasionally OA) DOI. (The keyword-method slug was
  clean: correct `journal-article` top-1, score 54.9 vs 38.5 — a wide margin.)
- **Trigger to fix:** the first slug that resolves to a wrong DOI (or a wrong OA
  PDF) in a real run. Widen `rows`, filter to primary work types (drop
  `posted-content`, `peer-review`, `dataset`, `component`, `grant`), prefer the
  best title-overlap among the survivors, and consider a Crossref `score`-margin
  gate (a clear top-1 vs a score-clustered tie). Pairs with the US10-deferred
  **multi-candidate scan** and **prefer-OA-edition** items. Driven by a failing
  test on captured multi-record Crossref fixtures.
- **Status:** OPEN (guard rejects low-overlap wrong matches today; same-title
  wrong-record disambiguation deferred).

## resolve_oa — title-overlap threshold is a fixed Jaccard on 3 samples

- **Where:** `src/paper_degist/resolve_oa.py` (`_MIN_TITLE_OVERLAP = 0.6`,
  `_title_overlap` symmetric content-token Jaccard).
- **Case not handled:** the threshold was calibrated on three real Crossref
  responses (a correct full-title match at 1.0; two best-effort wrong matches at
  0.50 and 0.33), so 0.6 sits between them. It is precision-biased: a *correct*
  published title carrying a subtitle the slug lacks (e.g. the PRISMA 2020 record
  with `: development of and key changes …`) scores ~0.57 and is rejected — a
  false negative, which safely routes to the human lane but forgoes an
  automatable resolve. The fixed count is not tuned against a labelled corpus,
  and a fuzzier string metric (token-set ratio, cosine) might separate better.
- **Trigger to fix:** the first *correct* match wrongly rejected that we want
  resolved, or a wrong match that slips through. Assemble a small labelled
  slug→DOI set, measure precision/recall across thresholds/metrics, and retune
  (or swap the metric), driven by tests over that captured set.
- **Status:** OPEN.

## browser_up — locked-profile launch failure is not its own branch yet

- **Where:** `src/paper_degist/browser_up.py::browser_up` (the launch dispatch)
  and `_default_launch`.
- **Case not handled:** a fixed `--user-data-dir` is single-instance — Chrome
  locks the profile dir, so launching a second Chrome against a profile another
  (non-dev-mode) Chrome already holds fails to bring the CDP endpoint up. Today
  that lands in the generic `launched Chrome but the CDP endpoint … did not come
  up in time` failure, not a distinct "profile is locked by another Chrome"
  diagnostic. The US18 background names the locked profile as one of the
  launch-failure branches; only "binary not found" (AC4) and "port in use" (AC5)
  got their own branch.
- **Trigger to fix:** the first real run that fails because the profile is
  locked. Detect the lock (a `SingletonLock` file in the profile, or Chrome's
  stderr) and raise a distinct `BrowserUpError`, driven by a failing test.
- **Status:** OPEN.

## browser_up — no state file (PID + endpoint); deferred stale-Chrome health check

- **Where:** `src/paper_degist/browser_up.py` (classifies on a live port probe,
  prints the endpoint to stdout — no persisted state).
- **Case not handled:** browser-up deliberately keeps **no** state file. The
  classify signal is a live port-reachability probe (self-correcting), the CDP
  endpoint is deterministic configured input (not discovered state), and the
  only real uses of a stored PID — kill / health-check — are out of scope (AC6
  leaves Chrome running; "detecting and relaunching a stale/crashed Chrome" is a
  named deferral). So a state file would be a second, staleable source of truth
  today. It earns its place only when the health check is built: a stored PID is
  the natural discriminator for "the Chrome *we* launched" vs. one the researcher
  started — i.e. "is it safe for us to recycle this."
- **Trigger to fix:** when the deferred stale/crashed-Chrome health check gets
  built (reuse a *reachable but wedged* endpoint → recycle it). Add a
  `.browser-up.state` (PID + endpoint) then, as that branch's discriminator.
- **Status:** OPEN (deliberate — decided in session 5a774313).

## browser_up — Chrome finder is macOS/Linux only; no --chrome override

- **Where:** `src/paper_degist/browser_up.py` (`_CHROME_CANDIDATES`,
  `_CHROME_ON_PATH`, `_default_find_chrome`).
- **Case not handled:** the fixed install locations cover macOS (`.app` bundles)
  and Linux (`/usr/bin/...`) plus a `$PATH` fallback. Windows paths
  (`C:\Program Files\Google\Chrome\...`) are absent, and there is no explicit
  `--chrome <path>` flag to point at a non-standard install — an uninstallable
  case today falls through to AC4's loud "binary not found".
- **Trigger to fix:** the first machine whose Chrome is not found (Windows, a
  custom install). Add the Windows candidates and/or a `--chrome` option
  (mirroring `--cdp`/`--user-data-dir`), driven by a failing finder test.
- **Status:** OPEN.

## browser_up — proxy env broke the CDP probe (fixed in the US18 E2E)

- **Where:** `src/paper_degist/browser_up.py::_default_probe_cdp`.
- **Case:** `HTTP(S)_PROXY` in the environment made httpx route the *localhost*
  CDP probe through the proxy, which 502s a loopback debug server. A perfectly
  reachable dev-mode Chrome then read as "not up", so the launch path reported
  `endpoint did not come up` and the reuse path misfired as `port held`.
  Surfaced by the US18 real E2E run on a machine with a proxy set.
- **Status:** RESOLVED. The probe now passes `trust_env=False` so it always hits
  the loopback endpoint directly, bypassing any proxy. Pinned by
  `test_default_probe_cdp_bypasses_proxy_env`.

## browser_up — port probe is IPv4-only (matches Chrome's 127.0.0.1 default)

- **Where:** `src/paper_degist/browser_up.py::_default_port_in_use`.
- **Case not handled:** `localhost` is dual-stack (resolves `::1` before
  `127.0.0.1`); the probe uses an `AF_INET` socket, so it checks IPv4 only. This
  is deliberate — Chrome binds `--remote-debugging-port` to `127.0.0.1` (IPv4) —
  so it matches what a launch would actually contend for. But a non-debug process
  holding *only* the IPv6 `::1:port` would not be detected, and the launch would
  then fail with the generic "endpoint did not come up" rather than the distinct
  "port held" diagnostic.
- **Trigger to fix:** the first real IPv6-only port collision. Resolve the host
  via `getaddrinfo` and probe every address family, driven by a failing test.
- **Status:** OPEN (low priority — IPv4 path matches Chrome's own binding).

## resolve_oa — doi_url is resolve-oa-only; no consolidated per-paper view (US11)

- **Where:** `src/paper_degist/resolve_oa.py::_quarantine` (the `doi_url` field)
  and the append-only `manifest.jsonl`.
- **Case not handled:** US11 adds a clickable `doi_url` to each resolve-oa
  quarantine that recovered a DOI, but two read-side follow-ups stay deferred:
  (1) a *consolidated manifest view* that groups the append-only rows by
  input/DOI to show "everything that happened to this paper" in one glance,
  without collapsing the per-stage diagnostic rows; and (2) *dedup on re-run* —
  re-running resolve-oa on the same input appends a duplicate quarantine row
  (confirmed in the US11 E2E: two identical `example.com` records after a
  re-run). Both are separate concerns from this link enhancement.
- **Trigger to fix:** when a reader wants the per-paper rollup, or when duplicate
  re-run rows become noise. Build a read-only reporting tool over the manifest
  (never collapsing the append-only write path), driven by a failing test.
- **Status:** OPEN (US11 shipped the clickable link; the rollup + dedup deferred).
