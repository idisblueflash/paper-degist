# US 24 Embed one text with a registered model

As a *maintainer building the abstract filter*, i want *a step that sends one
text to one named embedding model over the stable LM Studio transport and saves
its vector*, so that *the filter has a cheap, offline, deterministic similarity
signal and a flaky server never crashes it*.

## Background

The abstract filter (US 26) ranks candidates by how close their abstract is to a
topic — a **vector similarity**, not an LLM call in a loop (rule 02). That needs
one primitive: turn a text into an embedding vector, locally and repeatably. This
story adds it as `embed-text`, the near-exact sibling of `ocr-page` (US 20): the
same LM Studio server, the same **model registry** and **stable transport**, only
the `/v1/embeddings` endpoint instead of chat.

US 20's costliest lesson was the transport, and it carries over: **build the JSON
body in Python, POST it with `curl --data @body.json`, sequentially, with a
recovery gap and retry on a 5xx/empty body** — never `urllib`, never concurrent.
That recipe is encoded once here, not rediscovered.

The model list is a **registry** so new embedding models are accepted over time:
each entry is `(model id, query-prefix, doc-prefix)`. Prefixes matter — the
default `nomic-embed-text-v1.5` expects `search_query: …` for a query and
`search_document: …` for a passage, and getting it wrong silently degrades
ranking — so the prefix is registry data keyed by a `--role query|document`
flag, exactly as US 20 keeps each model's prompt quirk in its entry. Adding
`Qwen3-Embedding-0.6B` later is one registry entry, not a new branch.

The scope is a **new CLI step, `embed-text`, over one text and one model id**. It
looks the model up in the registry, applies the role's prefix, POSTs via the
stable transport, and saves the vector as JSON keyed by a hash of
`(model, role, text)`, recording `model`, `role`, `dims`, and `latency` to
`manifest.jsonl`. It does **not** compute similarity or rank (US 26), search for
candidates (US 25), or bring the server up (the operator's job, as with US 20).

## Acceptance Criteria

1. Given a text (e.g. an abstract) and a registered model id
   (`nomic-embed-text-v1.5`) with `--role document`
   - when embed-text applies the model's `search_document:` prefix and POSTs it
     over the stable transport and the model answers 200
     - then the vector is saved as JSON under
       `out/embeddings/nomic-embed-text-v1.5/<hash>.json` and its path printed to
       stdout, with an `embedding` record in `manifest.jsonl`
       (`stage: "embed-text"`) carrying `model`, `role`, `dims`, `latency`
2. Given a text whose vector for that model+role was already saved by a prior run
   - when embed-text runs again on the same text + model + role
     - then it skips and does **not** re-hit the server, mirroring `ocr-page`'s
       idempotency (the model call is the expensive, flaky resource)
3. Given the server returns a 5xx or empty body (crashed/flapping runtime)
   - when embed-text POSTs the text
     - then it retries after a recovery gap up to the configured limit, and only
       if still failing quarantines the text to the manifest
       (`stage: "embed-text"`, `reason` naming server-unreachable-after-retries),
       exiting cleanly — never crashes, never fires concurrently
4. Given a model id that is **not** in the registry (e.g. `some-unregistered-embed`)
   - when embed-text looks it up
     - then it quarantines with a **distinct** reason (unknown model, not a
       server error), without touching the network — the manifest separates
       "model not configured" from "server down"

## Case handling (classify-then-dispatch)

embed-text dispatches in two layers, like `ocr-page`. **First on the model id**:
in the registry → use its `(query-prefix, doc-prefix)` and apply the one the
`--role` selects; not in the registry → quarantine (unknown model) without
touching the network. **Then on the transport result**: a 200 → save the vector;
a 5xx/empty body → wait the recovery gap and retry, and after the retry budget
quarantine (server-unreachable). The transport is fixed encoded knowledge —
always `curl` with a file body, never `urllib`; always sequential with a gap.
Per-model quirks (the prefix pair, and later the dims) live in the registry
entry, so a new model is data, not a branch. No LLM is ever called.

## Later stages (deferred)

- **Batching texts in one run.** This story embeds one text per invocation with
  its own connect + gap. A batch driver that embeds a whole abstract list —
  honoring the sequential-with-gap rule — is left to the US 26 filter, composed
  from this step.
- **Vector store / index.** Vectors are saved as one JSON per text keyed by hash.
  A proper on-disk vector index (for reuse across topics, ANN search) is a
  separate design, deferred until a corpus is large enough to need it. See DEVLOG.
- **Server lifecycle.** embed-text assumes LM Studio is up with the model
  loadable; warming the model is the operator's job (as `browser-up` is for
  Chrome, and as US 20 already assumes), not this step.
