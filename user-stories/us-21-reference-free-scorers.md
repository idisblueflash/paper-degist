# US 21 Score OCR output with reference-free defect metrics

As a *maintainer comparing OCR models on a brand-new paper*, i want *a step that
scores a saved Markdown output on deterministic defect metrics needing no gold
reference*, so that *i can rank models on any page instantly and offline, without
hand-correcting a reference first*.

## Background

The investigation report ranked models mostly **without a gold reference** — by
counting *defects* with cheap deterministic proxies, and those proxies caught the
real killers: `unlimited-ocr` degenerating into a 95 % duplicate-line loop,
`deepseek-ocr@8bit` leaking ~31 hyphen-space artifacts per page
(`"low- quality"`) and silently dropping inline citation lists, the 4-bit model
ignoring the image entirely. None of those needs a reference to detect — they are
computable from the output text (plus the `manifest.jsonl` fields US 20 recorded:
`finish_reason`, `latency`, `completion_tokens`).

Each metric is one deterministic function = one scored **dimension** = one
branch (rule 02, rule 05: one logical assertion per test). This is the
everyday, offline tier of the bench: point it at any model's output for any page
and get a scorecard row, no labeling. The gold-referenced accuracy tier (edit
distance / TEDS against OmniDocBench) is US 22.

The scope is a **new CLI step, `score-ocr`, over one saved Markdown output**. It
computes each reference-free dimension, joins the per-call fields from the
manifest, and appends one `scores.jsonl` record per (model, page). It does
**not** need or load a gold reference (US 22) and does **not** aggregate across
models (US 23).

## Acceptance Criteria

1. Given a saved output `out/qwen_qwen3-vl-4b/p02.md`
   - when score-ocr scores it
     - then it appends one `scores.jsonl` record keyed by (model, page) carrying
       every reference-free dimension below, plus the manifest-sourced
       `finish_reason` / `latency` / `completion_tokens`
2. Given an output containing a line-level repetition loop
   (e.g. a degenerated `out/unlimited-ocr-mlx/p02.md`)
   - when score-ocr computes the duplicate-line ratio
     - then the `dup_pct` dimension reflects the degeneration (the metric that
       flagged unlimited's 95 % loop), scored high
3. Given an output with dehyphenation artifacts
   (e.g. a `out/deepseek-ocr_8bit/p02.md` full of `"low- quality"`, `"L1- Chinese"`)
   - when score-ocr counts hyphen-space artifacts
     - then the `hyphen_artifacts` dimension reports the count (the metric that
       separated @8bit from qwen), independent of the dup dimension
4. Given an output with academic inline citations
   (e.g. `"semantic maps [51,53,75,82]"`)
   - when score-ocr counts citation groups
     - then the `citation_groups` dimension reports the count, so a model that
       *drops* citation lists scores lower than one that keeps them
5. Given a Markdown file score-ocr cannot parse or read
   - when it tries to score it
     - then it quarantines that (model, page) to `manifest.jsonl`
       (`stage: "score-ocr"`, `reason`), skips it, and never crashes — the batch
       still finishes

## Case handling (classify-then-dispatch)

score-ocr runs a fixed panel of deterministic scorers, each owning one dimension:
`dup_pct` (duplicate substantive-line ratio — degeneration), `hyphen_artifacts`
(count of `word- word` breaks), `citation_groups` (count of `[\d+(,\d+)*]`
lists), `cjk_present` (any CJK/IPA codepoints survived — the reads-the-language
signal), plus the manifest-sourced `finish_reason`, `latency`,
`completion_tokens`. Watch the known false-positive the report called out: the
naive duplicate-line count inflates on legitimately repeated boilerplate
(affiliation lines, `---` rules), so the `dup_pct` scorer must exclude those —
that exclusion is encoded knowledge, not a per-run judgement. An output a scorer
cannot handle is quarantined, never crashed over, never sent to an LLM.

## Later stages (deferred)

- **Gold-referenced accuracy.** Character-level correctness (`Chaoran` vs
  `Chao ran`) cannot be measured reference-free — that is edit distance / TEDS /
  reading-order against OmniDocBench, US 22.
- **Table & formula structure.** TEDS and formula edit-distance need structured
  gold; deferred to the gold tier / a dedicated structure story.
- **Tuning dimension weights.** How the dimensions combine into one headline
  score is the aggregator's concern (US 23); this story only emits the raw
  per-dimension values.
