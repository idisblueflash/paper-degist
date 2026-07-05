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
- **Status:** ADDRESSED by US15 + US17. `browser-fetch` (US15) is the fetch
  *mechanism*: it attaches to an already-running dev-mode Chrome (US18
  `browser-up`) over CDP, navigates one URL, and saves the rendered HTML with the
  researcher's real cookies. `recover-blocked` (US17) is now the *routing* that
  consumes the manifest reason: it reads `fetch-one`'s `blocked_by` records, skips
  the ones a later run already recovered, and hands the rest to `browser-fetch`'s
  warm-batch path (US16) — deterministic, offline, no LLM. Still OPEN for the
  **`resolve-oa` DOI lane**: recover-blocked drives the *browser* lane only, so
  `resolve-oa`'s `closed access` / `no DOI` records are not yet auto-routed (see
  the two US17 deferrals below).

## recover_blocked — browser lane only; no per-host lane policy, no recovery report (US17)

- **Where:** `src/paper_degist/recover_blocked.py::recover_blocked`.
- **Case not handled:** recover-blocked routes every `blocked_by` record to the
  *browser* lane. It does not (a) pick the cheaper lane per host — some walls
  yield to `resolve-oa`'s DOI lookup (an open-access copy) without a browser, and
  a policy that tries `resolve-oa` first and falls back to the browser per
  `blocked_by` host is a routing refinement; nor (b) show a consolidated
  recovery report (blocked → retried → recovered) grouped by paper — that is a
  read-side view, complementary to US11's deferred per-paper rollup.
- **Trigger to fix:** (a) the first `blocked_by` host observed to recover more
  cheaply via `resolve-oa` than the browser — promote it into a per-host lane
  table; (b) the first time the append-only manifest's recovery history needs a
  human-readable rollup — build it alongside the resolve-oa per-paper view.
- **Status:** OPEN (deferred by US17 — this story performs the browser-lane retry;
  lane policy and the report are follow-ups).

## browser_fetch — a wall/login/consent page can be saved as if it were the paper (US15)

- **Where:** `src/paper_degist/browser_fetch.py::browser_fetch` (the save branch)
  and `_default_fetch_rendered`.
- **Case not handled:** browser-fetch trusts whatever the browser renders. A host
  that answers the navigation with a login form, cookie-consent interstitial, or
  captcha page (instead of the paper) renders *successfully* — so its HTML is
  saved and recorded `saved`, as if the wall were the content. US15 deliberately
  defers automating the wall (the researcher logs in by hand once), but there is
  no signal that distinguishes "captured the paper" from "captured the wall".
  `convert-html`'s "too thin" check (US5) catches a near-empty shell but **not** a
  full, content-rich login page.
- **Trigger to fix:** the first saved `.html` that is actually a wall page (a
  convert step yielding a login/consent Markdown). Add a wall-signature check
  (known login/consent markers, or a title/URL mismatch) that quarantines with a
  distinct "looks like a wall, not the paper" reason, driven by a captured
  wall-page fixture.
- **Status:** OPEN — **confirmed live by the US15 real E2E (2026-07-04).** Fetching
  `…/220320021_Spaced_Repetition_and_Long-Term_Retention` through a real dev-mode
  Chrome **not logged in to ResearchGate** saved a 939 KB HTML that was a
  Cloudflare-gated "Request PDF" page (markers `cloudflare` / `challenge-platform`,
  and a `<title>` for an *unrelated* paper) — recorded `saved`, exactly the
  wall-as-paper case. Two concrete signals a fix could use surfaced here: the
  Cloudflare challenge markers, and a **title/slug mismatch** between the URL and
  the rendered `<title>`. Operationally the precondition is that the researcher
  logs the profile into the host first (US15 defers in-script auth by design).
  **Stickiness (Codex review):** because the save writes a real file and re-runs
  skip an existing target (AC4 idempotency), a bad wall capture is *permanently*
  treated as a success — recovering it needs deleting the saved `.html` (and its
  manifest row) by hand. A future wall-signature check would need to run **before**
  the save so a wall never becomes the sticky artifact in the first place.

## browser_fetch — proxy env broke the CDP connection (fixed in the US15 E2E)

- **Where:** `src/paper_degist/browser_fetch.py::_default_fetch_rendered` /
  `_no_proxy_for`.
- **Case:** playwright's `connect_over_cdp` respects `HTTP(S)_PROXY`, so on a
  machine with a proxy set the *localhost* CDP connection was routed through the
  proxy, which 502s a loopback debug server — a perfectly reachable dev-mode
  Chrome then read as a navigation failure. The same trap `browser_up`'s probe
  dodges with `trust_env=False`; surfaced by the US15 real E2E on a proxied
  machine (`HTTP_PROXY=127.0.0.1:7897`).
- **Status:** RESOLVED. `_default_fetch_rendered` wraps the CDP session in
  `_no_proxy_for(host)`, which adds the CDP host to `NO_PROXY` for the duration
  (restoring it after) so the driver hits the endpoint directly without disabling
  the proxy for the page's own traffic. Pinned by
  `test_no_proxy_for_adds_the_cdp_host_to_no_proxy` and
  `test_no_proxy_for_restores_the_prior_no_proxy_after`.

## browser_fetch — live happy-path E2E not yet exercised against a real Chrome

- **Where:** `src/paper_degist/browser_fetch.py::_default_fetch_rendered` (the
  real `connect_over_cdp` → `page.goto(wait_until="networkidle")` → `page.content()`
  path).
- **Case not handled:** the US15 real E2E confirmed the classify/dispatch, the
  proxy-bypass fix (ws now connects), the quarantine branch (a non-conforming CDP
  endpoint quarantined cleanly with a distinct reason, exit 0, no file), and
  idempotency — but the **happy-path save through a genuine dev-mode Chrome** could
  not run: the environment had no real Chrome to attach to (the CDP server that
  answered `:9222` was not a full Chrome — `Browser context management is not
  supported`), and `browser-up` needs a real Chrome + display. The save path is
  covered only by unit + BDD with an injected renderer.
- **Trigger to fix:** the first run on a machine where `browser-up` has a real
  dev-mode Chrome up. Run `browser-fetch` against a genuinely bot-walled URL,
  confirm the rendered HTML is saved and `convert-html` consumes it; `networkidle`
  + the fixed 30s timeout may also surface a page (persistent websocket/polling)
  that never idles and quarantines as a nav timeout — retune the wait then.
- **Status:** RESOLVED (2026-07-04). Ran against a **real** dev-mode Chrome on
  `:9222` (a genuine `browser-up`-style Chrome on `.browser-profile`): `browser-fetch`
  connected over CDP, navigated, and saved a 939 KB rendered HTML with a `saved`
  manifest record (exit 0); a second run was idempotent (existing path printed, no
  duplicate manifest row). The earlier "context management not supported" was a
  non-Chrome CDP server transiently on `:9222`, not this code — a direct playwright
  `connect_over_cdp` → `new_page` → `goto` → `content()` against the real Chrome
  works. Two residuals stay open as their own flags: the saved page was a Cloudflare
  wall (see wall-as-paper flag above), and `convert-html` consumption + the
  `networkidle` timeout retune are still worth a pass on a logged-in fetch.
  NB: a second Chrome cannot launch on a `--user-data-dir` a first Chrome already
  holds (profile lock) — matches the `browser_up` locked-profile deferred flag;
  reuse the running endpoint instead.

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

## browser_fetch — batch is sequential tab reuse; real parallelism deferred (US16)

- **Where:** `src/paper_degist/browser_fetch.py::browser_fetch_batch` (the
  `for url in urls` loop over one `open_session`).
- **Case not handled:** the batch fetches URLs **one tab at a time** on the one
  warm connection. Fetching several tabs concurrently (a bounded pool with
  backpressure) could speed a large list, but risks tripping the very
  rate-limits and bot-walls the browser is meant to slip past — so US16
  deliberately keeps sequential tab reuse (named in the story's "Later stages").
- **Trigger to fix:** the first batch large enough that sequential fetching is
  the bottleneck *and* the target hosts tolerate concurrency. Add a bounded tab
  pool (N in flight) with per-host backpressure, driven by a failing test that
  asserts the cap; keep the single-connection, detach-not-close invariants.
- **Status:** OPEN (deliberate — sequential by design for US16).

## browser_fetch — a mid-batch Chrome loss quarantines each remaining URL one by one (US16)

- **Where:** `src/paper_degist/browser_fetch.py::browser_fetch_batch` /
  `_dispatch_url` (the per-URL `try/except` around `fetch_tab`).
- **Case not handled:** the batch probes the CDP endpoint **once** at the start
  (AC1). If Chrome dies *mid-batch*, the open session is now dead, so every
  remaining URL's `fetch_tab` raises and each quarantines individually with a
  `navigation failed: …` reason. This is correct and resilient (AC4 — one
  failure never aborts the run, and the loop finishes), but noisy: a lost
  browser writes one nav-failed record *per remaining URL* rather than a single
  "browser lost mid-batch" signal, and it keeps trying a connection it could
  cheaply tell is gone.
- **Trigger to fix:** the first real batch where Chrome dies partway and the
  manifest fills with redundant nav-failed rows. Detect a dropped connection
  (a re-probe, or a disconnect event on the session) and short-circuit the
  remaining URLs to a distinct `browser lost mid-batch` reason, driven by a
  failing test that kills the session partway.
- **Status:** OPEN (resilient today; the fast-fail + distinct reason deferred).

## fetch_one — filename↔title verification only flags; PDF title is metadata-only (US13)

- **Where:** `src/paper_degist/fetch_one.py::_verify_save` / `_extract_title`
  (`_pdf_title`, `_html_title`, `filename_reflects_title`).
- **Case not handled (two, both deliberate):** (1) **Auto-rename.** US13 only
  *flags* a mismatch (a `mismatch` manifest note naming file + title); deriving a
  canonical title-based filename is a larger change that collides with the US2
  idempotent-skip rule (what "already exists" means once names are title-derived),
  so it stays a hand-off for a human. (2) **PDF title depth.** `_pdf_title` reads
  the document `/Title` metadata only; a PDF whose metadata title is empty takes
  the `title-unverifiable` branch rather than falling back to first-page body
  text — that deeper extraction overlaps the not-yet-built PDF stage (US3/US4).
- **Trigger to fix:** (1) when a human tires of renaming and wants the pipeline to
  propose the title-derived name — build it against the US2 skip rule, test-first.
  (2) when the PDF stage lands and body-text extraction exists to reuse.
- **Status:** OPEN (US13 shipped the flag; auto-rename + PDF-body fallback deferred).

## fetch_one — mismatch vs title-unverifiable share stage="fetch-one" (US13)

- **Where:** `src/paper_degist/fetch_one.py::_verify_save` and the append-only
  `manifest.jsonl`.
- **Case not handled:** the two US13 verification records and the existing
  fetch-error quarantines all carry `stage="fetch-one"`; a reader tells them apart
  only by fields (`title` present ⇒ mismatch) and the `reason` prefix
  (`title-unverifiable: …`). There is no dedicated `kind`/`event` discriminator —
  the same read-side concern as the deferred resolve-oa per-paper rollup.
- **Trigger to fix:** when a consolidated manifest view needs to group records by
  event type across stages. Add an explicit discriminator field then (shared with
  the resolve-oa rollup), driven by a failing test.
- **Status:** OPEN (deferred with the resolve-oa manifest-rollup work).

## render_pdf — Ghostscript-only renderer; no PyMuPDF/poppler branch (US19)

- **Where:** `src/paper_degist/render_pdf.py::_default_render`.
- **Case not handled:** the renderer of record is Ghostscript (`png16m`, fixed
  dpi) because poppler/PyMuPDF were not installable in the report's env. There is
  no dispatch branch for an alternate engine, so a machine without `gs` on
  `$PATH` falls through to a `FileNotFoundError` inside the subprocess — caught
  and quarantined as `"unrenderable PDF: …"` (never crashes), but read as a
  corrupt-PDF case rather than a "no renderer installed" diagnostic.
- **Trigger to fix:** the first env with PyMuPDF/poppler available (for a speed
  or fidelity comparison) or one missing `gs`. Add the alternate as a dispatch
  branch and/or a distinct "renderer not found" reason, driven by a failing test.
- **Status:** OPEN (US19 shipped the gs path; alternate renderers deferred — see
  US19 "Later stages").

## render_pdf — single PDF per invocation; no directory batch (US19)

- **Where:** `src/paper_degist/render_pdf.py` (one `pdf_path` argument).
- **Case not handled:** render-pdf renders one PDF per run. Rendering a whole
  folder of PDFs (the bench at corpus scale) is a thin wrapper not yet built; the
  single-PDF step is designed to compose into it.
- **Trigger to fix:** when the OCR bench (US 20–23) drives a batch of papers. Add
  a directory/glob driver that calls `render_pdf` per file, driven by a test.
- **Status:** OPEN (deliberate — kept single-input like the sibling steps).

## render_pdf — PNG determinism relies on gs png16m being timestamp-free (US19)

- **Where:** `src/paper_degist/render_pdf.py::_default_render` (AC2, byte-stable
  re-render).
- **Case not handled:** AC2 requires a byte-identical re-render so downstream
  scores are reproducible. The US19 real E2E confirmed it (same SHA-256 across two
  renders of the same 3-page PDF at 150 dpi), but this rests on Ghostscript's
  `png16m` device emitting no timestamp/`tIME` chunk — an unversioned assumption.
  A future gs that stamps output would silently break byte-identity (the *pixels*
  would still match; a content hash that ignores PNG ancillary chunks would be
  more robust than a raw file hash).
- **Trigger to fix:** the first gs version whose re-render differs byte-for-byte.
  Compare decoded pixels (or strip ancillary chunks) instead of hashing raw
  bytes, driven by a test.
- **Status:** OPEN (low priority — verified byte-identical on the current gs).

## test suite — resolve-oa missing-email CLI test is environment-dependent (pre-existing)

- **Where:** `src/tests/test_cli.py::test_resolve_oa_cli_missing_email_exits_two`.
- **Case not handled:** this test expects `exit_code == 2` when `resolve-oa` runs
  with **no** `--email`. It **fails on a clean `master`** too (verified during the
  US19 work — not introduced here): when `UNPAYWALL_EMAIL` is set in the
  environment, the email is supplied via the env fallback, so the required-option
  path never triggers and the exit code differs. The test does not isolate the
  env var, so its result depends on the shell it runs in.
- **Trigger to fix:** when tightening the CLI gate to green. Monkeypatch
  `UNPAYWALL_EMAIL` out of the environment (`monkeypatch.delenv(...,
  raising=False)`) inside the test so it is hermetic.
- **Status:** OPEN (pre-existing; out of scope for US19, logged on discovery).

## fetch_one — filename↔title match is ASCII-slug only (US13)

- **Where:** `src/paper_degist/fetch_one.py::_slug_tokens` (`[a-z0-9]+`).
- **Case not handled:** tokenization keeps only ASCII alphanumerics, so a title
  with accented or non-Latin letters ("Café Culture") tokenizes to `{caf,
  culture}` while a basename `cafe-culture` tokenizes to `{cafe, culture}` — a
  *false* mismatch that would flag a name that actually reflects the title. The
  common paper case (English ASCII slugs) is unaffected.
- **Trigger to fix:** the first real non-ASCII title that lands a spurious
  `mismatch` in `manifest.jsonl`. Fold Unicode-normalization/transliteration
  into `_slug_tokens` (e.g. NFKD + strip combining marks) driven by a failing
  test with that title.
- **Status:** OPEN (low priority — ASCII slugs, the common case, are correct).

## ocr_page — single (page, model) per run; no batch driver (US20)

- **Where:** `src/paper_degist/ocr_page.py` (one `page_path` + one `model_id`).
- **Case not handled:** ocr-page OCRs exactly one page with one model per
  invocation, each with its own connect + retry budget. Walking a page directory
  across every registered model — honoring the sequential-with-gap rule so the
  flaky runtime never sees rapid-fire hits — is the report/US23 driver's job,
  composed from this step. The inter-*item* recovery gap therefore lives in that
  future driver; this step's `gap` is only the between-retries gap.
- **Trigger to fix:** when US23 aggregates a scorecard across a corpus. Add a
  batch driver that iterates `(page, model)` pairs calling `ocr_page`, inserting
  the recovery gap between items, driven by a test that asserts the sequencing.
- **Status:** RESOLVED by US28. `ocr-batch` walks a page directory across the
  model registry, calling `ocr_page` per `(page, model)` pair and inserting the
  report §3 recovery gap **between the pairs that actually hit the server** — the
  inter-*item* gap this flag named, distinct from ocr-page's between-retries gap.
  It classifies per pair on `output_path(...).exists()` (the shared SSOT extracted
  into `ocr_page`): exists → idempotent skip, no network, **no gap**; missing →
  dispatch to `ocr_page`. Sequencing pinned by
  `test_waits_a_recovery_gap_between_server_hitting_pairs` and
  `test_a_fully_cached_grid_waits_no_gap`. Two narrower batch scopes stay open
  below (a corpus across papers; bounded concurrency; adaptive gap).

## ocr_page — server lifecycle (LM Studio up + model loaded) is the operator's job (US20)

- **Where:** `src/paper_degist/ocr_page.py::_default_post` (assumes a reachable
  chat-completions endpoint with the model loadable).
- **Case not handled:** ocr-page does not bring the vision server up or warm a
  model — as `browser-up` is a separate step from `browser-fetch`, launching /
  loading LM Studio is out of scope. A crashed-but-`loaded` model that 502s is
  handled (retry → quarantine), but *starting* the server, or detecting a wedged
  runtime that needs a restart, is not. The report §3 recovery is retry-with-gap,
  not a relaunch.
- **Trigger to fix:** when the bench wants an unattended run that can recover a
  dead server. Add an `ocr-up`/warm step (mirroring `browser-up`) that ensures
  the endpoint answers and the model is loaded before ocr-page runs; keep it a
  separate step, not a branch inside the loop.
- **Status:** OPEN (deliberate — server lifecycle deferred by the US20 story).

## ocr_page — registry holds one DeepSeek entry; loaded variants not registered (US20)

- **Where:** `src/paper_degist/ocr_page.py::REGISTRY`.
- **Case not handled:** the registry ships `qwen/qwen3-vl-4b` and `deepseek-ocr`.
  The US20 real E2E found the live LM Studio also serving `deepseek-ocr-2`,
  `deepseek-ocr@8bit`, `deepseek-ocr@4bit`, and `unlimited-ocr-mlx` — DeepSeek
  variants the story names ("even new added models") but which are not registered
  yet, so ocr-page quarantines them as "unknown model". This is by design (a new
  model is one registry entry, not a branch), but the quant/variant entries are
  not written until the bench needs to score them.
- **Trigger to fix:** when the bench compares the DeepSeek quantizations (or the
  `unlimited-ocr` model). Add a `ModelSpec` per variant — most reuse the
  `<|grounding|>…` prompt + `_decode_grounding`, so it is a one-line data add.
- **Status:** OPEN (deliberate — registry is data; add entries on demand).

## ocr_page — model-slug output dir only rewrites '/', not other id punctuation (US20)

- **Where:** `src/paper_degist/ocr_page.py::_model_slug` (`model_id.replace("/", "_")`).
- **Case not handled:** the output dir name rewrites only `/` (so
  `qwen/qwen3-vl-4b` → `qwen_qwen3-vl-4b`). A model id carrying other punctuation
  — e.g. `deepseek-ocr@8bit` — lands its literal `@`/`:` in the path
  (`out/deepseek-ocr@8bit/…`). These are filesystem-legal on macOS/Linux so the
  save works today, but they are not normalized and could be awkward on Windows
  or in shell globs.
- **Trigger to fix:** the first registered id whose punctuation is unsafe on a
  target FS, or the first Windows run. Broaden `_model_slug` to a
  filesystem-safe transform (e.g. map any of `/ : @ \` to `_`), driven by a
  failing test on such an id.
- **Status:** OPEN (low priority — `/` is the only separator in today's ids).

## ocr bench — a model can return fluent, well-formed but hallucinated OCR (US20)

- **Where:** observed in the US20 real E2E; consumed by the US21–22 scorers.
- **Case not handled:** ocr-page trusts a 200 response — it post-processes and
  saves whatever the model returns. The US20 E2E on a clean, text-native page
  showed `deepseek-ocr` returning 2301 tokens of *fluent but entirely fabricated*
  content (unrelated math word-problems), `finish_reason: stop` — a perfect
  transport success wrapping garbage output, while `qwen/qwen3-vl-4b` transcribed
  the same page faithfully. ocr-page cannot (and should not) tell them apart; the
  manifest's `completion_tokens`/`finish_reason` are weak signals (a runaway
  hallucination shows as a high token count / `length`).
- **Trigger to fix:** this is exactly what US21 (reference-free defect metrics)
  and US22 (gold-accuracy scoring) exist to catch — a repetition/perplexity or
  edit-distance-to-gold score would flag the fabricated page. No fix belongs in
  ocr-page; logged here so the scoring stories have the concrete failure mode on
  record.
- **Status:** PARTIALLY ADDRESSED by US21. `score-ocr` now emits the
  reference-free defect panel (`dup_pct`, `hyphen_artifacts`, `citation_groups`,
  `cjk_present`) joined with US20's `finish_reason`/`latency`/`completion_tokens`.
  The US21 real E2E on the same page confirmed the limit precisely: DeepSeek's
  *fluent* hallucination did **not** trip `dup_pct` (it was coherent prose, not a
  repetition loop), but its manifest-sourced `completion_tokens` was **2301 vs
  qwen's 167** — a runaway-length signal the scorecard now carries. The gold tier
  that catches a fluent-but-wrong page on *content* now exists: US22's `score-gold`
  computes `text_edit_distance` (normalized Levenshtein vs the gold text) and
  `teds` (table fidelity) against an OmniDocBench gold page — a fabricated
  transcription scores a near-1.0 edit distance where a faithful one scores ~0.
  Remaining gap: this only fires on the *gold subset* (curated OmniDocBench
  pages), not on an arbitrary new paper, which has no reference (the deferred
  self-gold-from-arXiv source, below, is the complement).

## score_ocr — scores.jsonl is append-only; a re-run duplicates the (model, page) row (US21)

- **Where:** `src/paper_degist/score_ocr.py::score_ocr` / `_append_score`.
- **Case not handled:** `score-ocr` appends one row per run with no
  already-scored skip, so re-scoring the same `out/<model>/<page>.md` writes a
  second identical `scores.jsonl` row (confirmed in the US21 E2E: 2 rows → 3
  after a re-run). This mirrors `manifest.jsonl`'s append-only contract (and the
  resolve-oa re-run dup flag) — the results log is a stream, and the aggregator
  (US23) is expected to take the last row per (model, page). It is *not* the
  file-idempotent skip the saved-artifact steps use, because there is no
  per-target file to test for existence.
- **Trigger to fix:** when duplicate re-run rows become noise for US23, or a
  reader wants `scores.jsonl` to carry exactly one row per (model, page). Add a
  read-back-and-skip (or a last-wins compaction in the aggregator), driven by a
  failing test. Pairs with the resolve-oa/manifest per-paper rollup + dedup
  deferrals.
- **Status:** OPEN (deliberate — append-only results log, consistent with the
  manifest).

## score_ocr — dup_pct boilerplate exclusion is rules + blanks only, not affiliations (US21)

- **Where:** `src/paper_degist/score_ocr.py::_substantive_lines` (`_RULE_RE`).
- **Case not handled:** the report named two legitimately-repeated boilerplate
  kinds that inflate a naive duplicate-line count — `---` rules **and**
  affiliation lines. Only the deterministically-detectable one is excluded:
  blank lines and markdown horizontal rules. A page that genuinely repeats an
  affiliation/footer line across columns could still nudge `dup_pct` up, since
  "this line is an affiliation" is not a deterministic signal the way a `---`
  rule is.
- **Trigger to fix:** the first real page whose repeated affiliation/footer lines
  push `dup_pct` into false-positive territory. Add a boilerplate-line
  classifier (e.g. drop lines matching an affiliation/footer signature, or only
  count *runs* of consecutive duplicates so a repeated-once footer is ignored),
  driven by a captured fixture.
- **Status:** OPEN (the `---`/blank exclusion — the report's concrete case — is
  encoded; the affiliation case is deferred).

## score_ocr — manifest join keys on model-slug + page-stem, not the full path (US21)

- **Where:** `src/paper_degist/score_ocr.py::_manifest_fields`.
- **Case not handled:** the per-call fields are joined by matching the ocr-page
  record whose `model` slugifies to the output dir and whose `page` **stem**
  equals the output stem. Two page PNGs with the same stem in different
  directories (`A/p02.png`, `B/p02.png`) OCR'd by the same model would both
  match, and the last-wins pick could attribute the wrong call's latency/tokens.
  Today the bench renders one paper's pages under one dir with unique stems, so
  this cannot fire; it becomes reachable if a corpus batch reuses stems across
  papers.
- **Trigger to fix:** when a batch scores pages with colliding stems across
  papers. Carry the full source page path into the output (or into a sidecar) so
  the join is exact, driven by a failing test with two same-stem pages.
- **Status:** OPEN (low priority — current single-paper layout has unique stems).

## score_ocr — dup_pct is line-level; an intra-line (single-line) loop reads as 0 (US21)

- **Where:** `src/paper_degist/score_ocr.py::dup_pct` / `_substantive_lines`
  (`text.splitlines()`).
- **Case not handled:** `dup_pct` counts duplicate *lines* (the shape AC2 scoped:
  `unlimited-ocr`'s loop put each repeat on its own line → ~95%). A model that
  degenerates into **one physical line with no newlines** repeats phrases
  *within* that single line, so there is exactly one substantive line, `unique ==
  total`, and `dup_pct == 0.0` — the metric is blind to it. Surfaced by the US21
  real E2E: `out/deepseek-ocr/p0001.md` is a single unbroken line of ~100
  near-identical `"The sum of two numbers is $-N$ and their difference is $0$…"`
  sentences (a fluent runaway), yet scored `dup_pct: 0.0`. That page is **not**
  missed overall — the manifest-joined `completion_tokens: 2301` (vs qwen's 167)
  still flags the runaway — but the *duplication* dimension itself understates it.
- **Trigger to fix:** the first degenerated page whose repetition is intra-line
  (a single-line or few-line blob) that we want `dup_pct` to catch. Add a
  phrase/n-gram-level repetition signal (e.g. a duplicate-sentence or repeated
  n-gram ratio), or normalize a runaway single line into sentences before the dup
  count — driven by a **failing test on a captured `deepseek-ocr/p0001.md`-style
  fixture**. Keep the line-level metric too (it catches the `unlimited-ocr`
  shape); this is a second, complementary dimension, not a replacement.
- **Status:** RESOLVED (full golden run, PR pending). The trigger fired: the
  45-page gold batch produced `out/deepseek-ocr/…-j.mseb.2009.12.004.pdf_2.md`, a
  single-line runaway that repeats one sentence 10× (60% sentence-level dup) yet
  scored `dup_pct: 0.0`. `dup_pct` now dispatches through `_dup_units`: >1
  substantive line keeps the exact line-level metric (the AC2 shape, `unlimited-ocr`
  loop, no recalibration); a lone-line blob falls back to sentence segmentation
  (`_SENTENCE_SPLIT_RE`) so the intra-line loop is caught (`mseb` → 60.0). A
  single-line *non-repetitive* hallucination stays 0.0 (`…1528-1167…_3` — 429
  unique sentences, correctly not a dup defect; its fabrication is score-gold's
  lane). Pinned by `test_dup_pct_flags_a_loop_emitted_on_a_single_line`.

## score_gold — dataset is research-only; not vendored, operator supplies it (US22)

- **Where:** `src/paper_degist/score_gold.py::score_gold_batch` (reads an
  operator-supplied `annotations_path`); no OmniDocBench data under `src/tests/`.
- **Case / constraint:** OmniDocBench's license was verified at build time (HF
  card, 2026-07) as **"for research purposes only and not for commercial use,"**
  with *"content not allowed for distribution has been removed"* — a
  research-restricted license, **not** a redistributable open one (not CC-BY). So
  the dataset is deliberately **not vendored** into the repo: `score-gold` loads
  the annotation JSON and page images from the operator's own local download, and
  the tests run against a small **synthetic** fixture mirroring the verified
  schema (`page_info.page_attribute.{data_source,layout,language}`,
  `layout_dets[].{category_type,text,html,order}`). The subset filter's field
  names/values (`academic_literature` / `double_column` / `english`+`en_ch_mixed`)
  were confirmed against the dataset card.
- **Trigger to revisit:** if the license changes to permit redistribution, a tiny
  real gold fixture could be vendored for a real E2E; until then keep synthetic.
- **Status:** OPEN (deliberate — license-driven; the spec's "verify before
  building" gate was honoured, both facts confirmed pre-build).

## score_gold — model-table extraction is HTML-`<table>`-only; GFM pipe tables not converted (US22)

- **Where:** `src/paper_degist/score_gold.py::_model_tables_and_text`
  (`_extract_gfm_tables` / `_rows_to_html`).
- **Case not handled:** TEDS needs the model's table as HTML. Extraction found
  only inline `<table>…</table>` blocks (what doc-parse OCR models emit), but a
  model that renders a table as a **GFM pipe table** (`| a | b |`) produced no
  `<table>` match, so `_score_table` scored it `0.0` as if the table were omitted
  — a false low for a model that *did* transcribe the table, just in Markdown
  syntax.
- **Confirmed live** by the US22 gold smoke test (2026-07-05): `qwen/qwen3-vl-4b`
  OCR of the in-subset OmniDocBench table page `page-83587fc3-…` rendered the
  table as a GFM pipe table (13 `| … |` rows, zero `<table>` tags) and scored
  `teds: 0.0` on a table it had transcribed.
- **Status:** RESOLVED (US22 follow-up, 2026-07-05). `_model_tables_and_text`
  now extracts **both** inline HTML `<table>` blocks and GFM pipe tables: a
  header row followed by a `|---|` delimiter is parsed and rendered to
  `<table><tr><td>…</td></tr></table>` (all `<td>`, no `<th>`/`thead`, matching
  OmniDocBench's gold shape). The pipe rows are also stripped from the text so
  they no longer inflate `text_edit_distance`. Re-running the smoke test moved
  the same qwen page from `teds 0.0 → 0.7737` and `text_edit_distance 0.186 →
  0.047`. Two residual limits stay open (below): a pipe table cannot express
  `colspan`/`rowspan` (every converted cell spans 1), and an **unescaped** `|`
  inside a LaTeX cell (`$|x|$`) still mis-splits — GFM requires `\|`.

## score_gold — only the first table per page is scored; multi-table pairing deferred (US22)

- **Where:** `src/paper_degist/score_gold.py::_score_table` (`gold_tables[0]` vs
  `model_tables[0]`).
- **Case not handled:** a page with several tables scores only the first
  gold/model pair. Positional pairing breaks when the model drops or reorders a
  table, and the other tables are unscored. AC3's example is a single table, so
  this is out of scope today.
- **Trigger to fix:** the first in-subset gold page with >1 table. Pair tables
  (positionally, or by best-match), average the per-table TEDS, driven by a
  failing multi-table test.
- **Status:** OPEN (deliberate — single-table scope for AC3).

## score_gold — reading-order metric named in case handling, not implemented (US22)

- **Where:** `src/paper_degist/score_gold.py::score_gold_page` (scores text +
  table only).
- **Case not handled:** the story's "Case handling" lists reading-order → edit
  distance on the block sequence as a third dimension, but no AC requires it, and
  recovering the model's block order from flat Markdown is non-trivial. Only text
  (AC2) and table (AC3) dimensions are scored.
- **Trigger to fix:** when the scorecard (US23) wants a reading-order column.
  Derive the model's block sequence and edit-distance it against the gold `order`,
  driven by a failing test.
- **Status:** OPEN (no AC; deferred).

## score_gold — text edit distance compares raw Markdown to gold plain text (US22)

- **Where:** `src/paper_degist/score_gold.py::score_gold_page` (`normalized_edit_distance(model_output, _gold_text(...))`).
- **Case not handled:** the model output is compared as-is (Markdown syntax —
  `#`, `*`, `|`, link brackets) against the gold's plain recognition text, so even
  a perfect transcription carries a small non-zero distance from its own markup.
  Directionally fine for *ranking* models (the penalty is roughly uniform), but it
  is not the exact OmniDocBench text-normalization pipeline (which strips markup /
  normalizes whitespace before the edit distance).
- **Trigger to fix:** when a leaderboard-comparable absolute number (not just a
  ranking) is needed. Add OmniDocBench's text normalization (strip Markdown,
  collapse whitespace) before the compare, driven by a test.
- **Status:** OPEN (ranking-valid today; absolute-number parity deferred).

## score_gold — page image field assumed `image_path`; block field names verified (US22)

- **Where:** `src/paper_degist/score_gold.py::score_gold_batch`
  (`page_info["image_path"]` → output stem).
- **Case not handled:** the block-level names (`layout_dets`, `category_type`,
  `text`, `html`, `order`) and the page-attribute names were verified against the
  dataset card, but the **page image field name** (`image_path`) was assumed, not
  confirmed against a real annotation file. If the real field is `image_name` /
  `page_name`, the output-stem lookup finds nothing and every page quarantines as
  "no model output".
- **Trigger to fix:** the first real OmniDocBench run. Confirm the field against
  the downloaded JSON and adjust (or read it tolerantly), driven by a test on a
  real page record.
- **Status:** OPEN (low risk — one-line fix once the real file is in hand).

## score_gold — scores.jsonl is append-only; a re-run duplicates the gold row (US22)

- **Where:** `src/paper_degist/score_gold.py::score_gold` / `_append_score`.
- **Case not handled:** like `score-ocr` (US21), `score-gold` appends one row per
  run with no already-scored skip, so re-scoring the same page writes a second
  `gold` row. Consistent with the append-only results-log contract; the US23
  aggregator is expected to take the last row per (model, page). The `gold: true`
  discriminator distinguishes these rows from US21's reference-free rows in the
  shared `scores.jsonl`.
- **Trigger to fix:** when duplicate re-run rows become noise for US23. Add a
  read-back-and-skip or a last-wins compaction in the aggregator. Pairs with the
  US21 score_ocr append-only dup flag.
- **Status:** ADDRESSED at the aggregator (US23). The append is still last-wins on
  disk (score-ocr/score-gold still append, deliberate), but `ocr-report`'s
  `_last_wins` collapses re-scored rows to the newest per (model, page, tier)
  before aggregating, so a re-scored page is counted once — the "US23 aggregator
  takes the last row per (model, page)" expectation this flag named is now met.
  The writers' append-only dup remains OPEN by design (results-log contract).

## score_gold — model-table extraction is regex-based; nested tables mis-split (US22)

- **Where:** `src/paper_degist/score_gold.py::_model_tables` / `_MODEL_TABLE_RE`
  and the `_MODEL_TABLE_RE.sub("", …)` text strip in `score_gold_page`.
- **Case not handled (Codex US22 review):** `<table\b.*?</table>` is non-greedy,
  so a **nested** `<table>` inside a cell matches only through the *first*
  `</table>` — the outer table's tail is left as orphan `</table>` residue. That
  residue both (a) inflates `text_edit_distance` (it stays in the stripped text)
  and (b) feeds a structurally broken fragment to TEDS. Non-greedy regex cannot
  balance nested tags. Academic double-column pages rarely nest tables, so this
  is an edge case today.
- **Trigger to fix:** the first in-subset gold page (or model output) with a
  nested table. Replace the regex with an lxml parse that extracts top-level
  `<table>` subtrees (and removes them for the text compare), driven by a failing
  nested-table fixture. Pairs with the GFM-pipe-table conversion deferral.
- **Status:** OPEN (regex handles the flat-table common case; nested deferred).

## score_gold — output path keys on image stem; same stem across docs collides (US22)

- **Where:** `src/paper_degist/score_gold.py::score_gold_batch`
  (`Path(image_path).stem` → `out/<model>/<stem>.md`).
- **Case not handled (Codex US22 review):** the model output is located by the
  gold page's image **stem**. Two gold pages from different documents that share
  a base filename (`doc_A/page001.jpg`, `doc_B/page001.jpg`) map to the *same*
  `out/<model>/page001.md`, so both score against one output and append two rows
  keyed by the same stem — a silent collision, not a quarantine. This is the same
  stem-uniqueness assumption already flagged for `score_ocr`'s manifest join
  (US21) and `ocr_page`'s output dir (US20); OmniDocBench's own image names are
  globally unique, so it cannot fire on the real dataset today.
- **Trigger to fix:** the first batch whose gold images collide on stem across
  documents. Key the output on a document-qualified path (or carry the full
  image path through), driven by a failing two-same-stem test. Pairs with the
  US21 stem-collision deferral.
- **Status:** OPEN (low risk — OmniDocBench image names are unique).

## fetch_one — bot-wall table is 2 hosts; no auto-route to resolve-oa (US12)

- **Where:** `src/paper_degist/fetch_one.py::_BOT_WALLED_HOSTS` / `bot_wall_for`
  and the 403 branch of `fetch_one`.
- **Case not handled (two, both deliberate):** (1) **Auto-route.** US12 only
  *tags* a recognized 403 with `blocked_by` + an actionable reason; it does not
  itself call `resolve-oa`, because fetch-one holds only the URL, not a DOI or
  title. `recover-blocked` (US17) already consumes the `blocked_by` tag to drain
  these into the *browser* lane; auto-routing a `blocked_by` record into the
  *resolve-oa* (DOI/OA) lane is the still-open orchestration named in the
  resolve-oa rescue-lane flag above. (2) **Growing the table.** The host table
  ships `researchgate.net` and `pubmed.ncbi.nlm.nih.gov` only. A new bot-walling
  host that recurs as a bare `http 403` in the manifest is the trigger to promote
  it — a one-line addition to `_BOT_WALLED_HOSTS`, per rule 02 (the manifest is
  the queue of cases). The branch is gated on **403 specifically**: a walled
  host's non-403 error (e.g. a real 503 outage) keeps the generic record.
- **Trigger to fix:** (1) when the resolve-oa auto-route orchestrator is built —
  read a `blocked_by` record, recover a DOI/title, dispatch to `resolve-oa`.
  (2) the first recurring generic-403 host worth encoding. Both test-first.
- **Status:** OPEN (US12 shipped the recognition + tag; auto-route and table
  growth deferred by design — the story's "Later stages").

## ocr_page — transport hardened against four never-crash gaps (US20 follow-up)

- **Where:** `src/paper_degist/ocr_page.py` (`_parse_response`, `_default_post`,
  `_strip_markdown_fence`, `ocr_page` orchestrator).
- **Case:** a parallel review pass (a duplicate US20 build's self-review + Codex)
  surfaced four rule-02 "never crash" / precision gaps the merged US20 still had.
- **Status:** RESOLVED (follow-up PR). Fixed test-first: (1) a **4xx** now raises
  the new `ClientRequestError` and the orchestrator **fails fast** with a distinct
  `request rejected` reason instead of retrying a deterministic error for the full
  budget and mislabelling it "server unreachable"; (2) a 200 whose
  `choices[0].message.content` is **null/non-string** becomes a retryable
  `TransportError` rather than reaching the post-processor and `None.strip()`-ing;
  (3) `_strip_markdown_fence` normalizes **CRLF** so a `\r\n` qwen answer still
  has its outer fence stripped; (4) `_default_post` converts a **curl-missing**
  `OSError` into a `TransportError`, and `ocr_page` guards a **missing page** file
  with a distinct `page image not found` quarantine before any network call (the
  Typer CLI already rejects it up front; this guards direct library callers).

## ocr_report — verdict ranks only dimensions with a known direction (US23)

- **Where:** `src/paper_degist/ocr_report.py::_HIGHER_IS_BETTER` /
  `_LOWER_IS_BETTER` and `_leader` / `_verdicts`.
- **Case not handled (deliberate):** the models × dimensions **table** is fully
  data-driven — any dimension present in `scores.jsonl` gets a column summarized
  by value-kind, so a new metric or a new model appears with no code edit (AC3).
  The per-model **verdict** ("leads: …"), however, can only rank a dimension
  whose *direction of better* is encoded in the two frozensets. A brand-new
  dimension, or a neutral one (`completion_tokens`), still shows in the table but
  is silently absent from every verdict until its direction is taught. Categorical
  dimensions (`finish_reason`, `cjk_present`) are never leader-ranked by design.
- **Trigger to fix:** the first time a newly added dimension matters for the
  "which model wins" call — add its name to `_HIGHER_IS_BETTER` or
  `_LOWER_IS_BETTER` (a one-line change, per rule 02: the encoded case becomes a
  code branch). Test-first with a verdict scenario over that dimension.
- **Status:** OPEN (deliberate — the table is data-driven; the verdict's
  direction knowledge is per-dimension and grows one line at a time).

## ocr_report — dimensions deferred by the story's "Later stages" (US23)

- **Where:** `src/paper_degist/ocr_report.py` (`_verdicts` presents dimensions
  side by side; no cross-run history is read).
- **Case not handled (deferred by spec):** (1) **a single headline score /
  ranking** — weighting the dimensions into one ordering is a policy decision
  deferred until the dimension panel stabilizes; the verdict names per-dimension
  leaders, not one winner. (2) **trend across runs** — the report is a snapshot of
  the current `scores.jsonl`; comparing today's card to a prior run needs run
  history. (3) **feeding US3** — the card *informs* which model US3 "Converting
  PDF" adopts, but wiring the chosen model into the conversion is US3's story.
- **Trigger to fix:** (1) when the dimension panel is stable enough to defend a
  weighting; (2) when a regression-across-runs view is wanted (persist dated
  cards, diff); (3) when US3 is built.
- **Status:** OPEN (all three are the story's explicit "Later stages").

## ocr_report — count-like dimensions summarized by median, ratios by mean (US23)

- **Where:** `src/paper_degist/ocr_report.py::aggregate`.
- **Case not handled:** the summarizer is chosen by the *value kind* — pure-int
  dimensions (`hyphen_artifacts`, `citation_groups`, `completion_tokens`) get a
  representative **median** (a busy page does not skew it); any-float dimensions
  (`dup_pct`, `text_edit_distance`, `teds`, `latency`) get the **mean**;
  strings/bools get the dominant value. This matches the report's buckets, but a
  count-like dimension that happens to arrive as a float (e.g. an averaged count
  upstream) would be meaned, not medianed. No per-dimension override exists.
- **Trigger to fix:** the first dimension whose kind is mis-inferred from its
  value type — add an explicit dimension→summarizer mapping then, test-first.
- **Status:** OPEN (deliberate — value-kind dispatch keeps the aggregator
  data-driven; a name-based override is only worth it once a real dimension needs it).
## embed_text — single (text, model, role) per run; no batch driver (US24)

- **Where:** `src/paper_degist/embed_text.py` (one `text` + one `model_id` +
  one `role` per invocation).
- **Case not handled:** embed-text embeds exactly one text with one model+role
  per invocation, each with its own connect + retry budget. Walking a whole
  abstract list — honoring the sequential-with-gap rule so the flaky runtime
  never sees rapid-fire hits — is the US26 abstract-filter driver's job, composed
  from this step. The inter-*item* recovery gap therefore lives in that future
  driver; this step's `gap` is only the between-retries gap.
- **Trigger to fix:** when US26 filters a candidate list by abstract similarity.
  Add a batch driver that iterates texts calling `embed_text`, inserting the
  recovery gap between items, driven by a test that asserts the sequencing.
- **Status:** OPEN (deliberate — kept single-input like the sibling steps; named
  in the US24 "Later stages").

## embed_text — one JSON per vector; no on-disk vector index (US24)

- **Where:** `src/paper_degist/embed_text.py::_save` (writes
  `out/embeddings/<model>/<hash>.json`, one file per text).
- **Case not handled:** vectors are content-addressed as one JSON per
  `(model, role, text)`. A proper on-disk vector index (reuse across topics, ANN
  search over a corpus) is a separate design, deferred until a corpus is large
  enough to need it. The current layout is enough for US26 to load a candidate
  set's vectors and score cosine similarity in memory.
- **Trigger to fix:** the first topic run whose candidate corpus is large enough
  that per-file JSON load or linear similarity is the bottleneck. Add a vector
  store (e.g. a single packed array + id map, or an ANN index), driven by a test.
- **Status:** OPEN (deliberate — named in the US24 "Later stages").

## embed_text — server lifecycle (LM Studio up + model loaded) is the operator's job (US24)

- **Where:** `src/paper_degist/embed_text.py::_default_post` (assumes a reachable
  `/v1/embeddings` endpoint with the model loadable).
- **Case not handled:** embed-text does not bring the model server up or warm a
  model — as `ocr-page` (US20) and `browser-fetch` (US15) assume their server /
  Chrome is already up. A crashed runtime that 5xxs is handled (retry →
  quarantine), but *starting* LM Studio, or detecting a wedged runtime that needs
  a restart, is not.
- **Trigger to fix:** when the filter wants an unattended run that can recover a
  dead server. Add a warm step (mirroring `browser-up`) that ensures the endpoint
  answers and the model is loaded before embed-text runs; keep it a separate
  step, not a branch inside the loop.
- **Status:** OPEN (deliberate — server lifecycle deferred by the US24 story).

## embed_text — registry holds one nomic entry; alias id + Qwen3 not registered (US24)

- **Where:** `src/paper_degist/embed_text.py::REGISTRY`.
- **Case not handled:** the registry ships `nomic-embed-text-v1.5` only. The US24
  real E2E found the live LM Studio serves that model under the id
  `text-embedding-nomic-embed-text-v1.5` yet **also accepts the short
  `nomic-embed-text-v1.5` as an alias** (JIT model resolution) — so the AC's
  registered id works unchanged (a 768-dim vector came back). The same server
  also serves `text-embedding-qwen3-embedding-0.6b` — the `Qwen3-Embedding-0.6B`
  the story names ("Adding … later is one registry entry") — which is not
  registered yet, so embed-text quarantines it as "unknown model". This is by
  design (a new model is one registry entry, its `(query, doc)` prefix pair being
  the only per-model data), but the entry is not written until the filter needs
  to compare it.
- **Trigger to fix:** when the abstract filter compares a second embedding model,
  or a server serves nomic only under its long id (no alias). Add a `ModelSpec`
  per model id (and/or the long `text-embedding-…` id as its own key), driven by
  a failing test — a one-line data add, not a branch.
- **Status:** OPEN (deliberate — registry is data; add entries on demand).

## discover — arXiv now 301-redirects HTTP→HTTPS (fixed in the US25 E2E)

- **Where:** `src/paper_degist/discover.py` (`ARXIV_ENDPOINT`, `_arxiv_search`).
- **Case:** the first US25 real E2E hit
  `http://export.arxiv.org/api/query` and got a `301 Moved Permanently` to the
  `https://` host. httpx does **not** follow redirects by default, so the 301
  raised `HTTPStatusError` and quarantined every arXiv query as an `api-error` —
  a perfectly reachable API read as broken.
- **Status:** RESOLVED (2026-07-05). `ARXIV_ENDPOINT` is now the `https://` host
  and both adapters pass `follow_redirects=True`, so a future host/path move
  survives. Confirmed live: the same query then returned 25 real candidates.

## discover — Semantic Scholar keyless free tier is 429-rate-limited (US25)

- **Where:** `src/paper_degist/discover.py::_s2_search` (the `x-api-key` header is
  set only when `--s2-api-key`/`S2_API_KEY` is supplied).
- **Case not handled:** the US25 phase-2 bake-off found S2's shared keyless pool
  returns `429 Too Many Requests` on essentially every call from this
  environment — so `--source s2` is effectively unusable without a key (it
  cleanly quarantines as `api-error`, never crashes, but yields no candidates).
  This is *why arXiv is the default*; S2's `tldr` signal + biomedical coverage
  only pay off with a key. discover does not retry-after-`Retry-After` or back
  off on a 429 (a single call per run, quarantine on error).
- **Trigger to fix:** when the filter wants S2 candidates unattended. Add an
  `S2_API_KEY` to the environment (documented), and/or a `429`-aware
  retry-with-backoff honoring the `Retry-After` header, driven by a failing test.
- **Status:** OPEN (deliberate — key is the operator's to supply; the
  quarantine-on-429 behavior is correct today).

## discover — arXiv `all:` field match is coarse; no fielded/exact query (US25)

- **Where:** `src/paper_degist/discover.py::_arxiv_search`
  (`{"search_query": f"all:{query}"}`).
- **Case not handled:** the query is sent to arXiv's `all:` field (title +
  abstract + authors + …), which matches loosely on partial tokens — the US25
  E2E found a gibberish query `"zzqqxx nonexistent gibberish topic wwvv"` still
  returned 25 hits (the token `topic` alone matches thousands). This is *by
  design* for a high-recall wide net (US25 is deliberately coarse; US26
  narrows), but there is no option to scope to `ti:`/`abs:` or an exact phrase
  for a tighter query. A single truly-nonsense token (`"xqzptvwklmn"`) does hit
  the real `empty-result` branch.
- **Trigger to fix:** when a caller wants a precise arXiv query (a fielded or
  quoted-phrase search) rather than the wide net. Add a `--field`/exact-phrase
  option that composes the `search_query`, driven by a failing test.
- **Status:** OPEN (deliberate — wide-net recall is the US25 job).

## discover — one source per run; no query-both-and-merge driver (US25)

- **Where:** `src/paper_degist/discover.py` (one `--source` per invocation).
- **Case not handled:** discover queries exactly one source per run. A driver
  that fans a query across both adapters and merges + dedups the union (reusing
  US14's DOI normalization) is composed from this step — deferred to keep each
  adapter simple, and named in the US25 "Later stages".
- **Trigger to fix:** when the topic review wants the union of arXiv + S2 in one
  list. Add a fan-out/merge driver that calls `discover` per source and dedups by
  normalized DOI (and title fallback), driven by a test.
- **Status:** OPEN (deliberate — single-source like the sibling steps).

## discover — first page only; deep pagination deferred (US25)

- **Where:** `src/paper_degist/discover.py` (`start: 0` / `limit` — one page).
- **Case not handled:** discover returns the API's first page (up to
  `--max-results`). Deep paging for exhaustive recall (walking `start`/`offset`
  across pages, honoring arXiv's `ARXIV_MIN_INTERVAL` ~3 s inter-call delay — the
  constant is encoded but unused until a batch needs it) is a later option, gated
  on the bake-off showing the first page is too shallow.
- **Trigger to fix:** the first topic whose relevant papers fall past page one.
  Add a paginating loop that spaces arXiv calls by `ARXIV_MIN_INTERVAL`, driven
  by a test that asserts the sequencing.
- **Status:** OPEN (deliberate — named in the US25 "Later stages").

## discover — manifest is append-only; a re-run duplicates the discover row (US25)

- **Where:** `src/paper_degist/discover.py::discover` / `_manifest.append`.
- **Case not handled:** each run appends one `discover` record with no
  already-run skip, so re-running the same query appends a second row. Consistent
  with the append-only manifest contract (and the resolve-oa / score-ocr re-run
  dup flags) — a consolidated per-query rollup is the shared read-side follow-up,
  not a change to the write path.
- **Trigger to fix:** when duplicate re-run rows become noise, or a reader wants
  one row per query. Build the read-only rollup over the manifest (never
  collapsing the append-only write path), driven by a test. Pairs with the
  resolve-oa / score-ocr per-item rollup deferrals.
- **Status:** OPEN (deliberate — append-only manifest, consistent with the
  pipeline).

## ocr_batch — page discovery only matched `p*.png`, skipping `.jpg` gold pages (US28)

- **Where:** `src/paper_degist/ocr_batch.py::ocr_batch` (the page-walk glob).
- **Case (surfaced running the golden set):** discovery was
  `pages_dir.glob("p*.png")` — correct for render-pdf's `pNNNN.png` output, but
  the OmniDocBench gold subset ships pages as `.jpg` (39 of 45 in-subset pages;
  the other 6 are `page-*.png`). So pointing `ocr-batch` at the gold image
  directory silently OCR'd only the 6 `.png` and skipped all 39 `.jpg` — 86% of
  the subset — with no error.
- **Status:** RESOLVED (golden-run batch-of-1). Page discovery is now
  `_page_images`: every file whose suffix is in `_PAGE_SUFFIXES`
  (`.png`/`.jpg`/`.jpeg`, lowercase — uppercase would double-match on a
  case-insensitive FS), sorted in page order, and a missing directory yields no
  pages rather than raising (rule 02, preserving the never-crash contract), and an
  `is_file()` filter (Codex, PR #40) drops a subdirectory that happens to end in a
  page suffix. Pinned by `test_ocrs_a_jpg_page` and
  `test_a_subdirectory_named_like_a_page_is_not_ocrd`; the missing-dir guard keeps
  `test_missing_page_directory_returns_no_paths` green.

## ocr_batch — page order is lexical, wrong for unpadded numeric stems (US28)

- **Where:** `src/paper_degist/ocr_batch.py::_page_images` (`sorted(...)`).
- **Case not handled (Codex, PR #40):** pages are sorted lexically by path, so
  an unpadded numeric stem orders `..._10.jpg` **before** `..._5.jpg`. render-pdf
  zero-pads (`pNNNN.png`) so its order is correct; the OmniDocBench gold pages are
  each a standalone page from a different paper scored independently by stem
  (`out/<model>/<stem>.md`), so their processing order has **no effect on
  outputs** — only on the recovery-gap sequence and the stdout listing. Harmless
  today; a real bug only for a *single* multi-page document with unpadded,
  order-significant page numbers fed as one directory.
- **Trigger to fix:** the first input whose page order matters *and* whose stems
  are unpadded integers. Add a natural-sort key (split trailing digits) driven by
  a test with `_5`/`_10` stems.
- **Status:** OPEN (deliberate — no consumer depends on gold page order).

## ocr_batch — one page directory per run; no corpus-across-papers driver (US28)

- **Where:** `src/paper_degist/ocr_batch.py::ocr_batch` (one `pages_dir`).
- **Case not handled:** ocr-batch OCRs one paper's page directory
  (`pages/<stem>/`) across the registry per run. Fanning the whole `pages/` tree
  — every paper's pages × models — is a thin wrapper composed from this step,
  deferred exactly like `render-pdf`'s directory batch (US19, above). Sibling
  render-pdf and ocr-batch are each single-input by design; a corpus run chains a
  render-all driver into an ocr-all driver.
- **Trigger to fix:** when the bench scores a multi-paper corpus in one command.
  Add a wrapper that iterates `pages/*/` calling `ocr_batch` per paper (mind the
  US20/US21 stem-collision flags once stems repeat across papers), driven by a
  test. Pairs with the render-pdf directory-batch deferral.
- **Status:** OPEN (deliberate — single page directory, named in the US28 "Later
  stages").

## ocr_batch — grid is strictly sequential; bounded concurrency deferred (US28)

- **Where:** `src/paper_degist/ocr_batch.py::ocr_batch` (the nested
  `for page … for model …` loop over one `ocr_page` at a time).
- **Case not handled:** the grid is walked one pair at a time with a recovery gap
  between server-hitting pairs — the report §3 anti-flap rule forbids concurrent
  hits on the MLX runtime. A bounded pool (N in flight) with per-model
  backpressure could speed a large grid on a runtime that tolerates it, but risks
  the very flapping the sequential-with-gap recipe exists to avoid (mirrors the
  browser-fetch batch-concurrency deferral).
- **Trigger to fix:** the first grid large enough that sequential OCR is the
  bottleneck *and* a runtime that provably tolerates concurrency. Add a bounded
  pool with a per-model cap, driven by a test that asserts the cap; keep the
  never-concurrent invariant for the default path.
- **Status:** OPEN (deliberate — sequential by design for US28).

## ocr_batch — unregistered-model classify ordering (Codex US28 review)

- **Where:** `src/paper_degist/ocr_batch.py::ocr_batch` (the per-pair classify).
- **Case (two, both surfaced by Codex's US28 review):** (1) the batch's
  idempotency skip originally ran on `output_path(...).exists()` **before**
  checking model registration, so a **stale output for an unregistered model**
  was returned as a "cached" success — diverging from `ocr_page`, whose layer-1
  classify checks the registry *first* and quarantines an unknown model before
  the existence check. (2) The recovery gap's `hit_server` flag was set on every
  dispatch, including an unknown-model quarantine that never touches the network,
  so the next real pair over-waited a gap.
- **Status:** RESOLVED (US28 Codex follow-up). The batch now classifies in
  ocr-page's own order: `registered = model_id in registry` gates both the skip
  (`registered and target.exists()`) and the gap (`registered and hit_server`;
  `hit_server` set only when `registered`). An unregistered model therefore
  dispatches to `ocr_page` — which quarantines it (unknown model) regardless of a
  stale file — and never counts as a server hit. Pinned by
  `test_a_stale_output_for_an_unregistered_model_is_not_treated_as_cached` and
  `test_an_unregistered_model_does_not_charge_the_next_pair_a_gap`. (Codex also
  noted a library caller passing `models=[]` is a silent no-op; kept deliberate —
  an explicit empty selection parallels an empty page directory, both clean
  no-ops, and the CLI cannot produce it: omitting `--model` yields the whole
  registry.)
