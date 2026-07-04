# US 23 Aggregate a model comparison scorecard

As a *maintainer deciding which OCR model the PDF path (US 3) should adopt*, i
want *a step that aggregates all per-page scores into one Markdown scorecard of
models × dimensions*, so that *comparing models — including a newly added one —
is a single regenerated report, not a manual re-read of raw outputs*.

## Background

US 21 and US 22 emit per-(model, page) score records into `scores.jsonl`; on
their own they are a pile of rows. The value the investigation report delivered
was the **scorecard** — a models × dimensions table with a per-model verdict
("qwen is the primary text converter; `deepseek-ocr-2` is the fast-draft +
figure/layout source"). This story reproduces that artifact *deterministically*
from the stored scores, so it regenerates in seconds and never re-hits the model
server.

The core requirement, from the original ask, is that **a newly added model needs
no code change**: register it (US 20), run the scorers (US 21/22), regenerate the
report → it appears as a new column with its own verdict. The aggregation is pure
data: group by model, summarize each dimension across pages, rank.

The scope is a **new CLI step, `ocr-report`, over `scores.jsonl`**. It reads the
score records, aggregates per (model, dimension), renders a Markdown scorecard
(one row per model or dimension, one column per the other) plus a short verdict
line per model, and writes it to a report file. It does **not** run models
(US 20) or compute any score itself (US 21/22) — it only summarizes stored
scores, so it stays offline and instant.

## Acceptance Criteria

1. Given a `scores.jsonl` with reference-free (US 21) and gold (US 22) records
   for several models across several pages
   - when ocr-report aggregates it
     - then it writes a Markdown scorecard table of **models × dimensions**, each
       cell the dimension summarized across that model's pages
2. Given the same `scores.jsonl` regenerated twice
   - when ocr-report runs again with no new scores
     - then the report is byte-identical (deterministic aggregation — no server
       call, no timestamp churn in the compared body), so the artifact is stable
       to diff
3. Given a **new** model's score records appended to `scores.jsonl` (no code
   change — it was only registered and scored)
   - when ocr-report regenerates
     - then the new model appears as its own column/row with its dimensions
       summarized, proving the report is data-driven, not hard-coded per model
4. Given a (model, dimension) cell with **no** score (a metric that was
   not-applicable or an output that quarantined upstream)
   - when ocr-report renders that cell
     - then it shows an explicit gap marker (not a silent `0`, which would read
       as "scored badly"), so a missing measurement is visibly distinct from a
       poor one — and rendering never crashes on the gap

## Case handling (classify-then-dispatch)

ocr-report groups the score records by model, then by dimension, and dispatches a
summarizer per dimension kind: count-like dimensions (`hyphen_artifacts`,
`citation_groups`) summarize by a representative value across pages; ratio/score
dimensions (`dup_pct`, edit distance, TEDS) by their average; categorical ones
(`finish_reason`, `cjk_present`) by their dominant value. A missing cell is
rendered as an explicit gap, never coerced to zero (a false zero would rank a
model as *bad* where it was merely *unmeasured*). The dimension list is derived
from the records present, not hard-coded, so a new dimension or a new model flows
through without a code edit. Pure summarization — no model call, no LLM, fully
deterministic and offline.

## Later stages (deferred)

- **A single headline score / ranking.** Weighting the dimensions into one
  ordering (and defending the weights) is a policy decision deferred until the
  dimension panel stabilizes; this story presents the dimensions side by side.
- **Trend across runs.** Comparing today's scorecard to a prior run (did the new
  model regress a dimension?) needs run history; deferred.
- **Feeding US 3.** The report *informs* which model US 3 "Converting PDF"
  adopts, but wiring the chosen model into the actual PDF→Markdown conversion is
  US 3's own story, not this one.
