---
title: Unpaywall contact email comes from an env var, never hardcoded
updated: 2026-07-05
status: verified
sources: []
---

# Unpaywall contact email comes from an env var, never hardcoded

**Decision.** The contact email Unpaywall/Crossref require is supplied through the
`UNPAYWALL_EMAIL` environment variable, bound to the `resolve-oa` Typer `--email` option —
never hardcoded in source. Confirmed in the repo: `src/paper_degist/resolve_oa.py:312`
declares `typer.Option(envvar="UNPAYWALL_EMAIL", …)`, so the flag falls back to the env var
and the code still *requires* a value (a missing one is a usage error).

**Why.**

- The email is **per-user config and PII** — hardcoding it commits a personal address to
  version control. An env var keeps it out of the tree while still making it mandatory.
- Supplied via a shell export (appended to `~/.zshrc`), so it applies to every new shell
  without a flag on each invocation.

**No `.env` file yet.** A dotenv loader/dependency was deliberately *not* added: only one
env var exists today. The trigger to revisit is a **second or secret** variable appearing —
then a dotenv mechanism earns its place, not before.

**Known consequence — it leaks into the test suite.** Because the CLI reads the env var, a
shell that exports `UNPAYWALL_EMAIL` changes CLI test outcomes; see
[[UNPAYWALL_EMAIL leaks into the resolve-oa CLI test]].

**Sources.** [[session 6b2b71c9-76ea-46dc-94d9-5755c4ed11e4]] (email/env decision + download run).
