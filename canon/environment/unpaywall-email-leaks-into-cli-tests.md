---
title: UNPAYWALL_EMAIL leaks into the resolve-oa CLI test
updated: 2026-07-05
status: verified
sources: []
---

# UNPAYWALL_EMAIL leaks into the resolve-oa CLI test

**What.** `test_resolve_oa_cli_missing_email_exits_two` (`src/tests/test_cli.py`) is
**env-leaky**: it asserts the CLI exits `2` when `--email` is omitted, but the `--email`
option falls back to the `UNPAYWALL_EMAIL` env var (see
[[Unpaywall contact email comes from an env var, never hardcoded]]), so a shell that exports
that variable makes the CLI exit `0` and the test **fails**. Confirmed in the repo: the test
calls `runner.invoke(resolve_oa_app, ["https://doi.org/10.1191/x"])` with **no
`monkeypatch.delenv("UNPAYWALL_EMAIL", …)`** — there is no `delenv` anywhere in the file, so
the ambient shell env leaks in.

**Not a real product bug — a test-hygiene gap.** The CLI behaves correctly (a present env var
*is* a supplied email). The failure is purely that the test does not clear the env before
`runner.invoke`. It is **environmental and reproducible**, not a clone or machine artifact:
it fails identically in any checkout whose shell exports the var.

**Recurring gotcha.** This has surfaced across at least three sessions (US16 ship, the
second-workspace clone, and the US23 build) as "1 failing test" that is safe to ignore under
a set env var — every green-gate claim in those sessions carried the caveat. The clean fix is
`monkeypatch.delenv("UNPAYWALL_EMAIL", raising=False)` in the test (a DEVLOG-deferred flag);
until then, run the suite with the var unset (`env -u UNPAYWALL_EMAIL uv run pytest`) to see a
true-green gate.

**Sources.** [[session 6e18c177-4542-45e6-aadc-d8b575a1d307]] (latent test bug surfaced),
[[session 35d1a354-a3d8-45f7-b8ff-bddc86d9cf55]] (US16 ship noted it pre-existing/environmental).
