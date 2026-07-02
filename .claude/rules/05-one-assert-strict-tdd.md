# Rule 05 — One assert per test, driven one test at a time

**Each test asserts exactly one thing, and each test is written and made green
before the next one exists.** No bulk-writing a batch of tests and then
implementing against all of them at once.

## The two disciplines

### One logical assertion per test

A test fails for exactly one reason. When a refactor turns a test red, the red
test *names* the broken behavior — no bisecting a multi-assert test to find
which line went. Split any test whose assertions are **causally independent**
(e.g. control-flow vs. data-shape: "the item is quarantined" is one test,
"the manifest record has these fields" is another).

- "One assertion" means one *logical* fact, not necessarily one `assert`
  keyword. Asserting a whole record equals an expected dict is one fact.
- Factor shared **arrange/act** into a helper or fixture so the split never
  duplicates setup. See `src/tests/test_fetch_one.py` (`_run`,
  `_run_with_existing`, `_only_record`) and `test_cli.py` (`_fetch_one_save`,
  `_fetch_one_quarantine`).
- Name the test for the one reason it can fail
  (`test_http_error_manifest_records_status`), not for a scenario bundle.

### Strict red → green → refactor, one test at a time

Write **one** failing test, watch it fail for the right reason, make it pass
with the smallest change, refactor, then write the next test. Do **not** write
many tests up front and then implement in one pass — that is TDD-shaped but
forfeits its benefits:

- **Triangulation.** When the next test you write is *already green*, that is a
  signal the behavior is covered — you drop the redundant test instead of
  keeping it. Bulk-writing hides that signal and accretes overlapping tests.
- **Design emergence.** Incremental red-green lets the interface be driven by
  the tests. Bulk-then-implement lets the code be designed first and the tests
  retrofitted to match it.

## Why

The point of a test suite is to *locate* a regression, not just detect one. One
assertion per test plus one-test-at-a-time construction means every red test
points at a single behavior, and the suite carries no dead weight — each test
earned its place by failing before the code that satisfies it existed.

This sharpens rule 01's red→green→refactor loop into its non-negotiable grain.
