# US 22 Score accuracy against an OmniDocBench gold subset

As a *maintainer who wants a true accuracy ranking, not just a defect count*, i
want *a step that scores each model against a curated subset of OmniDocBench's
gold annotations using its official per-element metrics*, so that *"which model
is most faithful" is a reproducible number comparable to the public leaderboard,
with no hand-labeling*.

## Background

Reference-free proxies (US 21) rank models by *fewest defects*, but cannot settle
*accuracy* — whether `deepseek-ocr-2` really beats qwen on author names, or how
faithfully a model reconstructs a table. That needs a **gold reference**.
Hand-correcting pages is avoidable: **OmniDocBench** (CVPR 2025;
`opendatalab/OmniDocBench` on HuggingFace; 1651 annotated PDF pages) ships gold
text, tables (LaTeX + HTML), formulas, and reading-order, stratified by page
attributes. We take a **subset filtered to our use case** — `data_source =
academic literature`, `layout = double-column`, `language ∈ {en, mixed}` — so the
gold pages statistically match the two-column, embedded-CJK papers this pipeline
targets, and drop newspapers/receipts/handwriting.

The metrics are OmniDocBench's own per-element scheme: **normalized edit
distance** for text and reading-order, **TEDS** for tables (compared as HTML).
Each is deterministic and reference-anchored — computed by comparing a model's
output (via US 20) to the gold, no LLM judge.

The scope is a **new CLI step, `score-gold`, over the filtered gold subset**. It
loads the subset, runs each **registered** model (US 20) on each gold page,
computes the per-element metrics against the annotations, and appends
gold-scored records to `scores.jsonl` alongside US 21's reference-free rows. It
does **not** define the reference-free dimensions (US 21) or render the final
report (US 23).

> **Verify before building:** OmniDocBench's redistribution **license** and the
> exact **metadata field names** for the attribute filter must be confirmed at
> build time (the HF card did not state the license plainly). Treat both as
> unverified until checked — do not vendor the dataset until the license is read.

## Acceptance Criteria

1. Given the OmniDocBench subset filtered to `academic literature` +
   `double-column` + `en/mixed`
   - when score-gold loads it
     - then only pages matching that filter are selected (newspaper, receipt,
       handwriting, single-column pages excluded), so the gold set matches the
       pipeline's target distribution
2. Given a selected gold page and a registered model
   - when score-gold runs the model on the page and compares its text output to
     the gold text
     - then it records the **normalized edit distance** for text as a gold
       dimension in `scores.jsonl`, keyed by (model, gold-page)
3. Given a gold page annotated with a table
   - when score-gold compares the model's table (as HTML) to the gold table
     - then it records the **TEDS** score as a separate gold dimension (table
       structure fidelity is scored independently of prose text)
4. Given a gold page **missing** an annotation type a metric needs (e.g. no table
   on a text-only page)
   - when score-gold reaches that metric
     - then it skips just that metric for that page (records it as not-applicable,
       not zero), quarantining nothing and crashing on nothing — the other
       dimensions and pages still score

## Case handling (classify-then-dispatch)

score-gold classifies each gold page by which annotation types it carries, and
dispatches one metric per present type: text → normalized edit distance; table →
TEDS (+ edit distance) on the HTML form; reading-order → edit distance on the
block sequence. A page missing a type simply skips that metric (recorded
not-applicable) rather than scoring it zero — a false zero would poison the
average. The subset **filter** (doc-type/layout/language) is encoded knowledge;
widening or narrowing it is a config change, not a code branch. Model calls reuse
US 20's stable transport and idempotent cache, so a re-run re-scores from stored
outputs without re-hitting the flaky server. No LLM is used to judge accuracy —
every metric is a deterministic comparison to the gold annotation.

## Later stages (deferred)

- **Formula scoring (CDM / BLEU).** OmniDocBench scores formulas too; wiring the
  formula metric is deferred until a model in the registry is a serious formula
  contender.
- **The full 1651-page run.** This story scores the filtered subset; running the
  whole benchmark for leaderboard-comparable headline numbers is a scale concern
  left to the report driver.
- **Second gold source.** Self-generating gold from a paper's own arXiv
  HTML/LaTeX (reusing `convert-html`) would let *any* new paper act as its own
  reference; deferred as a complementary source to the curated subset. See
  DEVLOG.
