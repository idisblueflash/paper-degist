# US 20 OCR one page with a registered model

As a *maintainer benchmarking OCR models*, i want *a step that sends one page
image to one named model over the stable transport and saves its Markdown*, so
that *adding or re-testing a model is a single command and the flaky server
never crashes the bench*.

## Background

The investigation report's costliest lesson was the **transport**, not the
models (report §3): Python `urllib` on an image POST returns an empty-body 502
and takes down the MLX vision worker; rapid-fire requests flap the runtime; a
crashed model can still report `loaded` while chat 502s. The verified recipe:
**build the JSON body in Python, POST it with `curl --data @body.json`,
sequentially, with a ~6–8 s recovery gap and retry-on-502**. That recipe must be
encoded in the script once (rule 02), not rediscovered each run.

The bench also has to accept **new models over time** ("even new added models").
So the model list is a **registry**: each entry is `(model id, prompt,
post-processor)` — qwen takes a plain instruction and needs only a ```` ```markdown ````
fence stripped; DeepSeek-OCR variants take `<|grounding|>Convert the document to
markdown.` (with the literal `<image>` token **omitted**, or LM Studio 400s on a
double image) and need `decode_grounding` post-processing. Adding a model is one
registry entry, not a new code branch.

The scope is a **new CLI step, `ocr-page`, over one page image and one model
id**. It looks the model up in the registry, POSTs via the stable transport,
applies the model's post-processor, saves the Markdown to
`out/<model>/<page>.md`, and records `model`, `latency`, `finish_reason`, and
`completion_tokens` to `manifest.jsonl`. It does **not** render pages (US 19),
score output (US 21–22), or aggregate a report (US 23).

## Acceptance Criteria

1. Given a page PNG (e.g. `pages/WordCraft/p02.png`) and a registered model id
   (`qwen/qwen3-vl-4b`)
   - when ocr-page POSTs it over the stable transport and the model answers 200
     - then the (post-processed) Markdown is saved as `out/qwen_qwen3-vl-4b/p02.md`
       and its path printed to stdout, with a `ocr` record in `manifest.jsonl`
       (`stage: "ocr-page"`) carrying `model`, `latency`, `finish_reason`,
       `completion_tokens`
2. Given a page PNG whose output for that model was already saved by a prior run
   - when ocr-page runs again on the same page + model
     - then it skips and does **not** re-hit the server (model calls are the
       expensive, flaky resource — re-runs must not repeat them), mirroring
       fetch-one's idempotency
3. Given the server returns a 502 (crashed/flapping runtime)
   - when ocr-page POSTs the image
     - then it retries after a recovery gap up to the configured limit, and only
       if still failing quarantines the (page, model) to the manifest
       (`stage: "ocr-page"`, `reason` naming server-unreachable-after-retries),
       exiting cleanly — never crashes, never fires concurrently
4. Given a model id that is **not** in the registry
   (e.g. `some-unregistered-ocr`)
   - when ocr-page looks it up
     - then it quarantines with a **distinct** reason (unknown model, not a
       server error), so the manifest separates "model not configured" from
       "server down" — and still never crashes

## Case handling (classify-then-dispatch)

ocr-page dispatches in two layers. **First on the model id**: in the registry →
use its `(prompt, post-processor)`; not in the registry → quarantine (unknown
model) without touching the network. **Then on the transport result**: a 200 →
apply the post-processor and save; a 502/empty-body → wait the recovery gap and
retry, and after the retry budget quarantine (server-unreachable). The transport
itself is fixed encoded knowledge — always `curl` with a file body, never
`urllib`; always sequential with a gap, never concurrent (report §3). Per-model
quirks (the omitted `<image>` token, `decode_grounding` vs fence-strip) live in
the registry entry, so a new model is data, not a branch. No LLM is ever called
to classify or rescue an item.

## Later stages (deferred)

- **Batching pages/models in one run.** This story does one (page, model) per
  invocation with its own connect + gap. A batch driver that walks a page
  directory across every registered model — honoring the sequential-with-gap
  rule — is left to the report/US 23 driver, composed from this step.
- **The figure crop-and-embed hybrid.** The report's hybrid splices real figure
  bitmaps into qwen's text using DeepSeek layout boxes. That is a distinct
  multi-model pipeline, deferred to a later figure-scoring story.
- **Server lifecycle.** ocr-page assumes LM Studio is already up with the model
  loadable; bringing the server up / warming a model is the operator's job (as
  browser-up is for Chrome), not this step. See DEVLOG.
