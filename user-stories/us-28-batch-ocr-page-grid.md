# US 28 Batch-OCR a page directory across the model registry

As a *maintainer running the OCR bench*, i want *a step that walks a directory of
rendered page images and OCRs every page with every registered model, spacing the
calls with the recovery gap*, so that *one command lays down the whole
`out/<model>/<page>.md` grid the scorers and report already consume — instead of
me invoking `ocr-page` once per (page, model) pair by hand*.

## Background

The bench is built from single-item steps: `render-pdf` (US 19) turns one PDF
into `pages/<stem>/pNNNN.png`; `ocr-page` (US 20) OCRs **one** page with **one**
model into `out/<model>/<page>.md`; `score-ocr` / `score-gold` (US 21–22) score
those Markdown files; `ocr-report` (US 23) aggregates the scorecard. US 20
deliberately left the **grid** — every page × every registered model — to a
future driver ("a batch driver that walks a page directory across every
registered model, honoring the sequential-with-gap rule, is left to the report
driver, composed from this step"; DEVLOG). US 23 shipped the aggregator, so that
trigger has now fired: the one missing link is the driver that produces the OCR
corpus the aggregator reads.

The costliest encoded lesson (report §3, carried by US 20) is the **transport**:
the MLX vision runtime flaps under rapid-fire hits, so calls must be
**sequential with a recovery gap** and never concurrent. `ocr-page` owns the gap
*between its own retries*; the gap **between items** — one (page, model) call and
the next — is precisely what this driver adds. It holds no transport logic of its
own: it composes `ocr-page`, whose classify-then-dispatch (unknown model → skip
the network; 200 → save; 502 → retry then quarantine) already covers every
per-item outcome. There is no LLM in the loop (rule 02); the driver is
deterministic, offline routing over a directory.

The scope is a **new CLI step, `ocr-batch`**, over one page directory (one
paper's pages, e.g. `pages/SpacedRepetition/`). It iterates the page PNGs across
the model registry (or a caller-restricted subset), calls `ocr-page` per pair,
and inserts the recovery gap **between the calls that actually hit the server**.
It does **not** render pages (US 19), score output (US 21–22), aggregate a report
(US 23), bring the server up, or drive Chrome. It writes no manifest record of
its own — each per-item `ocr` / quarantine record is `ocr-page`'s (as
`recover-blocked` delegates its records to `browser-fetch`).

## Acceptance Criteria

1. Given a page directory holding several page PNGs (e.g. `pages/SpacedRepetition/`
   with `p0001.png`, `p0002.png`) and the model registry (`qwen/qwen3-vl-4b`,
   `deepseek-ocr`)
   - when ocr-batch runs
     - then it OCRs **every (page, model) pair** — calling `ocr-page` once per
       pair — and prints each saved `out/<model>/<page>.md` path
2. Given two consecutive pairs that both reach the server
   - when ocr-batch moves from one pair to the next
     - then it waits the **recovery gap** between them, so the flaky runtime never
       sees rapid-fire hits — the sequential-with-gap rule applied **between
       items**, not just between one page's retries
3. Given a (page, model) pair whose `out/<model>/<page>.md` a prior run already
   saved
   - when ocr-batch reaches that pair
     - then it **skips** it without re-hitting the server **and without waiting a
       recovery gap** (an idempotent skip is not a server hit, so it needs no
       cool-down) — re-running the grid stays cheap, mirroring `ocr-page`'s
       idempotency (US 20 AC 2)
4. Given one pair whose model call fails and quarantines (server unreachable after
   retries, or an unknown model)
   - when ocr-batch dispatches the rest of the grid
     - then that pair is quarantined by `ocr-page` and the batch **continues** to
       the remaining pairs — one bad pair never aborts the run (rule 02: never
       crash), and the batch's return omits only the quarantined pair
5. Given a caller who restricts the models (e.g. `--model qwen/qwen3-vl-4b`)
   - when ocr-batch runs
     - then only the named model(s) are used; with no `--model` the **whole
       registry** is the default grid (a new registered model joins the grid with
       no change here — rule 02: the registry is data)

## Case handling (classify-then-dispatch)

The grid is `pages × models`, walked in page order then model order (deterministic
output). Per pair, the driver classifies on one cheap signal — **does
`out/<model>/<page>.md` already exist?** Exists → idempotent skip, no network, **no
gap**. Missing → dispatch to `ocr-page`, which owns the transport classify
(unknown model → quarantine without touching the network; 200 → save; 502/empty →
retry-with-gap then quarantine). The recovery gap is inserted **before** a pair
that will hit the server, and only when a prior pair already hit it — so a run of
idempotent skips costs nothing and a fresh grid spaces exactly the real calls. The
driver adds no transport logic and no judgement of its own; every per-item record
is `ocr-page`'s, and no LLM is ever called to classify or rescue a pair.

## Later stages (deferred)

- **A corpus across papers.** This story walks **one** page directory (one
  paper). Fanning the whole `pages/` tree — every paper's pages × models — is a
  thin wrapper composed from this step, deferred like `render-pdf`'s directory
  batch (US 19, DEVLOG).
- **Bounded concurrency.** The grid is strictly sequential by design — the report
  §3 anti-flap rule forbids concurrent hits. A bounded pool with per-model
  backpressure is a later option, gated on a runtime that tolerates it (mirrors
  the `browser-fetch` batch-concurrency deferral).
- **A gap only when the runtime needs it.** The recovery gap is a fixed
  `--gap` seconds before every real call. Adaptively shortening it when the server
  is healthy (or lengthening it after a flap) is a refinement over the fixed
  constant, deferred until a real corpus run shows the fixed gap is wrong.
