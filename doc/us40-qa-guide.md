---
vmark:
  id: 019f83d9-ba8c-7b52-b508-8d54e7d9a17e
---

# US 40 — manual QA guide (live browser lane, real Chrome)

**For:** [US 40](../user-stories/us-40-browser-fetch-lazyload-interactive-wall.md)
· **What it verifies:** the lazy-load readiness gate and the `--interactive` wall
recovery **against a real headed Chrome** — the one path the unit/BDD suites cannot
exercise (they inject fakes; this env has no display). Run this on a machine with a
desktop where `browser-up` can launch a headed Chrome.

Each case is tagged **`[auto]`** (Claude drives it end to end per rule 06 phase 12)
or **`[human]`** (needs a person — here, solving the captcha in Case 4). Every step
is plain shell, so it stays **AI-free and reproducible** by a human too. It
complements the automated gates (`uv run pytest -q`, `uv run behave`) — those prove
the classify/dispatch logic; this proves the live capture.

## Preconditions

- A desktop session (headed Chrome needs a display).
- `uv sync` done in the repo (`playwright` is a repo dep; if Chromium is missing,
  `uv run playwright install chromium` — but `browser-up` prefers a system Chrome).
- No proxy trap: the loopback CDP connection bypasses `HTTP(S)_PROXY` automatically
  (`browser_fetch._no_proxy_for`), so a machine with a proxy set is fine.
- Clean the sample DOI from a prior run so idempotency does not mask a capture:
  `rm -f files/j.jbi.2018.12.005.html`.

## Step 0 — bring the dev-mode Chrome up  `[auto]`

```bash
endpoint=$(uv run browser-up)   # launches headed Chrome on a persistent profile
echo "$endpoint"                # -> http://localhost:9222
```

A Chrome window opens against `.browser-profile`. Leave it open for every step
below — `browser-fetch` **attaches**, it never launches or kills this Chrome.

---

## Case 1 — AC1: `networkidle` is retired (a heavy SPA is not falsely quarantined)  `[auto]`

The paper is `https://doi.org/10.1016/j.jbi.2018.12.005` (open-archive on
ScienceDirect). Under the old `networkidle` wait this timed out at 30 s and
quarantined as `navigation failed`. It must not now.

```bash
echo "https://doi.org/10.1016/j.jbi.2018.12.005" \
  | uv run browser-fetch --cdp "$endpoint"
```

**Expect** (no wall showing — e.g. `cf_clearance` still valid from a prior clear):

- ✅ stdout prints `files/j.jbi.2018.12.005.html`.
- ✅ the manifest has a `{"result":"saved", …}` row for the DOI — **not**
  `reason: "navigation failed … networkidle"`.
- ❌ if you instead see `navigation failed`, AC1 has regressed.

If a Cloudflare "Are you a robot?" wall shows on this fresh/expired profile, the
unattended run correctly quarantines (`looks like a wall, not the paper: …`) — that
is Case 3's default branch. Go clear it in Case 4.

## Case 2 — AC2: the lazy-loaded body must be full, never a `"Loading…"` stub  `[auto]`

Read the saved capture and convert it — the body must have **every section**, not
just the header/abstract.

```bash
uv run convert-html files/j.jbi.2018.12.005.html
md=files/j.jbi.2018.12.005.md
wc -w "$md"        # expect ~14k words (a header-only stub would be < ~800)
for s in Abstract Introduction Methods Results Discussion Conclusion References Acknowledgements; do
  grep -qi "$s" "$md" && echo "  $s YES" || echo "  $s NO  <-- FAIL";
done
```

**Expect:** all eight sections `YES`, word count in the thousands.
**Fail signal:** a few-hundred-word Markdown with only Abstract → the readiness gate
did not wait for the scroll-triggered body (or the selectors missed this host — file
a DEVLOG note and add the container to `_BODY_SELECTORS`). A **`convert-html`
quarantine "HTML too thin"** means an *unrendered shell* was saved — the readiness
gate should have polled/quarantined it (publisher-aware, `_is_lazyload_publisher`);
if a new host slips through, add its shell marker to `_LAZYLOAD_PUBLISHER_MARKERS`.
This exact case was caught by the first live QA run and fixed.

To see the gate *reject* a stub directly: if a run ever saved nothing and the
manifest reason is `body not loaded: lazy-load container holds N word(s) …`, that is
the gate working — the body never filled within the bound.

## Case 3 — AC4: unattended default never blocks on a human  `[auto]`

With a wall present and **no** `--interactive`, the batch must quarantine and move
on (never hang waiting for a person). Verify the batch does not block: give it two
URLs and confirm it returns promptly.

```bash
printf '%s\n%s\n' \
  "https://doi.org/10.1016/j.jbi.2018.12.005" \
  "https://doi.org/10.1016/j.artmed.2021.102083" \
  | uv run browser-fetch --cdp "$endpoint"
```

**Expect:** the command **returns** (does not hang); any walled/unloaded URL is
quarantined with a distinct reason on the manifest; stderr notes the quarantine
count. A URL that loaded is saved. The run exits `0`.

## Case 4 — AC3: `--interactive` clears the wall by hand once, then auto-resumes  `[human]` (you solve the captcha)

Force a wall if you do not have one: quit Chrome, delete the clearance cookie by
removing the profile (`rm -rf .browser-profile`), and `browser-up` again — the fresh
profile will hit the Cloudflare interstitial.

```bash
rm -f files/j.jbi.2018.12.005.html          # so the capture is not skipped
echo "https://doi.org/10.1016/j.jbi.2018.12.005" \
  | uv run browser-fetch --cdp "$endpoint" --interactive
```

**Expect the interactive loop:**

1. ✅ stderr prints `>>> ACTION NEEDED: a bot-wall is showing … Clear it by hand …`.
2. 👉 **You** solve the captcha in the Chrome window. Do **not** touch the terminal —
   the tool never solves it for you and never asks you to type anything.
3. ✅ within a few polls the tool auto-resumes: the body loads, the file saves, the
   command exits `0` and prints the saved path.
4. ✅ re-run **without** `--interactive` — it should now go straight through with **no
   wall** (the `cf_clearance` cookie persists in the profile). Confirms the
   restart-persistence finding.

**Fail signals:** the tool solves/clicks the captcha itself (it must not); it hangs
past \~4 min with no resume after you cleared the wall (the bound is 240 s —
`_INTERACTIVE_MAX_WAIT_S`); or it quarantines as `navigation failed` while you were
mid-clear (the transient-redirect resilience regressed).

**External block (not a tool fail):** if the Cloudflare **managed challenge loops in
an animation and never shows a checkbox**, you cannot clear it by hand — Cloudflare
flags the automation-launched `browser-up` Chrome and refuses to present the
challenge. The tool is behaving correctly (it polls, then quarantines the wall with
no sticky file); this is the permanently-out-of-scope evasion boundary, not a bug.
Work around it at the **browser** level: solve the challenge once in a *non-automation*
Chrome profile and point `browser-up --user-data-dir` at it so the `cf_clearance`
cookie is seeded, then re-run. (Observed 2026-07-21 on `doi.org/10.1016/j.jbi.2018.12.005`.)

## Case 5 — regression: US15/US16/US35 still hold  `[auto]`

The lazy-load lane is additive; the existing lane must be unchanged.

```bash
# US15/16 — an ordinary (non-lazy) page still saves through one warm session:
echo "https://www.researchgate.net/publication/220320021_Spaced_Repetition_and_Long-Term_Retention" \
  | uv run browser-fetch --cdp "$endpoint"
# US35 — a login/Cloudflare wall on a non-logged-in host still quarantines *before*
# the save (no sticky bad file); the manifest reason mentions "wall".
# Idempotency — re-run any saved URL: it is skipped, file untouched, no new manifest row.
```

**Expect:** ordinary page saves; a wall quarantines before any file is written; a
second run of a saved URL prints the existing path and appends **no** manifest row.

---

## Sign-off checklist

- [ ] Case 1 — DOI capture saved, not a `networkidle` nav-timeout.
- [ ] Case 2 — converted Markdown has all 8 sections (\~14k words), no `"Loading…"` stub.
- [ ] Case 3 — unattended batch returns promptly and never blocks on a human.
- [ ] Case 4 — `--interactive` notifies, you clear by hand, it auto-resumes; re-run needs no clear.
- [ ] Case 5 — US15 save / US35 wall-quarantine / idempotency all unchanged.

Record the run (date, Chrome version, whether a wall appeared) in the DEVLOG flag
*"the live domcontentloaded + readiness/interactive loop not unit-run against a real
Chrome (US40)"* to mark it RESOLVED once all five cases pass.
