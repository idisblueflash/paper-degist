# Bugs

Known defects awaiting a fix. One row per bug; the dedicated write-up lives in `bugs/<slug>.md`
with repro, root cause (file:line), impact, and a suggested fix.

| Bug | Component | Severity | Status | Report |
|---|---|---|---|---|
| OA papers reported as "closed access" when Unpaywall has no `url_for_pdf` | `resolve-oa` | High | Fixed | [resolve-oa-false-closed-when-no-url-for-pdf](bugs/resolve-oa-false-closed-when-no-url-for-pdf.md) |

## Conventions

- **Filename:** kebab-case slug describing the defect, not the symptom-of-the-day.
- **Each report carries:** summary · severity · environment · reproduction · expected vs. actual · root cause (with `file:line`) · impact · suggested fix · tests to add.
- **Status:** `Open` → `In progress` → `Fixed` (link the commit/PR when fixed). Keep fixed rows for history; don't delete.
