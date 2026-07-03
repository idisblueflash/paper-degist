# US 18 Launch a dev-mode Chrome for the browser lane

As a *Claude Code session about to run the browser lane*, i want *one command
that brings up a dev-mode Chrome on the CDP port (reusing one already running)
and prints its endpoint*, so that *i stop re-deriving the launch incantation
every session and the researcher only has to do the manual login once the browser
is up*.

## Background

US 15/16 attach to an **already-running** dev-mode Chrome and deliberately leave
its lifecycle to the operator. In a real run the operator that starts Chrome is
**Claude Code**, not the researcher: I locate the Chrome binary, pick the flags
(`--remote-debugging-port`, a persistent `--user-data-dir`), and launch — then the
researcher does the *manual confirmation* (log in, clear a captcha) once the
window is up. That launch is knowledge I re-investigate every session; rule 02
says to encode it once in the script, not re-derive it per run. This step is that
encoding: the browser lane's setup command, one layer *before* browser-fetch.

The step launches Chrome only — it never logs in, solves a wall, or fetches a
page (US 15's job stays US 15's). It is idempotent by design: if a dev-mode Chrome
is already reachable on the port, it **reuses** that one rather than spawning a
second, so I can safely call it at the top of every browser-lane run and it
dovetails with the warm persistent profile US 15/16 lean on.

The profile is what carries the login across runs. browser-up launches Chrome
against a **fixed** `--user-data-dir` at a known path (default `.browser-profile/`,
overridable with `--user-data-dir`) — not a throwaway temp dir — so the session
cookies the researcher writes on the first manual login are still there next run:
login is amortized to **once**, not per run. Two consequences ride along. The
profile holds live authenticated sessions for the researcher's accounts, so it is
**secrets-at-rest**: it must be **gitignored** and never committed. And "no manual
confirm next time" holds only until a session **expires** — browser-up cannot
detect expiry; it just brings the browser up and the researcher re-logs-in by hand
when a site has logged them out (the same manual-confirmation path as the first
run, not a new branch). A fixed profile is also single-instance by nature — Chrome
locks a `--user-data-dir` — which reinforces the idempotent single-Chrome design
below and is why a locked profile is one of the launch-failure branches.

It is a classify-then-dispatch step over one cheap signal: is a dev-mode Chrome
already answering on the CDP port? Reachable → reuse and report the endpoint; not
→ locate Chrome and launch it. The accreting branches are the launch-failure cases
(rule 02's "new issue → new branch"): a Chrome binary that cannot be found, a port
already held by a non-debug process, a locked profile. Unlike every other step,
this one has **no paper and no batch** to keep running, so a launch it cannot
complete is a **loud failure** — a clear diagnostic and a non-zero exit — not a
manifest quarantine: there is nothing to proceed to, and the operator needs to
notice. No LLM in the loop.

The scope is a **new setup command, `browser-up`**. It resolves the CDP endpoint
(default `http://localhost:9222`, overridable with `--cdp`), reuses a reachable
dev-mode Chrome or launches one against the fixed persistent profile (default
`.browser-profile/`, overridable with `--user-data-dir`), waits until the endpoint
answers, prints the endpoint to stdout, and returns. It does **not** log
in or solve captchas (the researcher does that by hand once the browser is up),
does **not** fetch or convert any page (US 15/16), does **not** decide which URLs
need the browser (US 17), and does **not** kill or restart a browser it did not
start.

## Acceptance Criteria

1. Given **no** dev-mode Chrome running on the CDP port
   - when browser-up launches Chrome with the remote-debugging port and the
     **fixed** persistent `--user-data-dir` (default `.browser-profile/`) and the
     endpoint comes up
     - then the reachable CDP endpoint (e.g. `http://localhost:9222`) is printed
       to stdout, so browser-fetch can attach to it — and Chrome is left running
       for the researcher to log in
2. Given a fixed profile that already holds a valid login from a prior run
   - when browser-up brings Chrome up against that same `--user-data-dir`
     - then the session cookies are already present and the researcher is **not**
       prompted to log in again — the manual confirmation is amortized to the
       first run, not repeated per run
3. Given a dev-mode Chrome **already reachable** on the CDP port
   - when browser-up runs again
     - then it reuses the running browser and does **not** spawn a second Chrome
       (idempotent — safe to call at the top of every browser-lane run), and still
       prints the same endpoint
4. Given a launch that cannot complete because the Chrome binary is not found
   - when browser-up cannot locate Chrome to start
     - then it exits non-zero with a clear diagnostic naming the missing browser —
       a **loud** failure, not a manifest quarantine (there is no batch to carry
       on), and never a stack-trace crash
5. Given the configured port is already held by a **non-debug** process
   - when browser-up cannot bring a dev-mode endpoint up on that port
     - then it exits non-zero with a **distinct** diagnostic (port occupied, not a
       missing binary), so the operator can tell "no Chrome" from "port in use" —
       and still never crashes
6. Given a dev-mode Chrome that browser-up launched (or reused)
   - when browser-up finishes
     - then it leaves Chrome **running** and detaches without killing it, so the
       warm session survives for browser-fetch and later runs (US 15/16 own the
       attach; the researcher owns the shutdown)

## Case handling (classify-then-dispatch)

browser-up classifies on one cheap signal before doing any work: is a dev-mode
Chrome already answering on the configured CDP port? **Already reachable** → reuse
it and print the endpoint (idempotent — never a second Chrome). **Not reachable**
→ locate the Chrome binary and launch it with the remote-debugging port and the
fixed persistent `--user-data-dir`, then wait until the endpoint answers. The
launch-failure cases are the encoded, accreting knowledge (rule 02): a binary that
cannot be found and a port held by a non-debug process each get their own distinct
diagnostic and a non-zero exit — a **loud** failure rather than a manifest
quarantine, because this step has no paper and no batch to keep running, so there
is nothing to proceed to and the operator must notice. Each new launch quirk we
hit becomes another branch here, so the next session runs the command instead of
re-investigating. The Chrome binary path, the port, and the profile dir are the
encoded knowledge — a different port or profile is a flag, not a new code path. No
signal beyond port-reachability and launch result is needed, so the step stays
deterministic and LLM-free.

## Later stages (deferred)

- **Secrets-at-rest for the profile.** The fixed `--user-data-dir` holds live
  authenticated sessions for the researcher's accounts, so it must be **gitignored**
  and never committed (add the profile path to `.gitignore` when this story is
  built). Encrypting or vaulting the profile beyond Chrome's own OS-keychain cookie
  encryption is a hardening concern deferred here. See DEVLOG.
- **Re-login on session expiry.** The fixed profile amortizes login to the first
  run, but sessions expire and sites invalidate them; browser-up cannot detect that
  and does not try — it brings the browser up and the researcher re-logs-in by hand
  when logged out. Detecting expiry (e.g. probing a logged-in-only element) to
  prompt re-auth proactively is deferred.
- **Detecting and relaunching a stale/crashed Chrome.** browser-up reuses a
  *reachable* endpoint and launches when there is none; noticing a Chrome that is
  up but wedged (hung tab, crashed renderer) and recycling it is a health-check
  concern deferred here. See DEVLOG.
- **Automating the manual confirmation.** browser-up gets the browser up to the
  point the researcher logs in or clears a wall by hand; scripting that
  login/consent/captcha is the same deferred script-driven-auth design US 15 names
  — the persistent profile carries the manual login forward instead.
- **Scheduling a standing browser.** Keeping a dev-mode Chrome warm across many
  unattended runs (a daemon that ensures the browser is always up) is the
  orchestration layer US 17 defers, not built here.
