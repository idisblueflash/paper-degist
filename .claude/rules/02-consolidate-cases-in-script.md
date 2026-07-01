# Rule 02 — Consolidate case knowledge into the script

**Encode case-handling in the script, not in a per-run LLM call. Claude is the
author who encodes a case once — not a runtime dependency called every run.**

## The principle

When Claude figures out how to handle a case, that knowledge becomes a code
branch. From then on the script decides — deterministically, offline, for free.
Claude is only needed again for a *genuinely new* case, which then also becomes
code. This keeps the workflow runnable when Claude is offline and saves tokens.

Never call an LLM inside a processing loop to classify or rescue an item.

## Classify-then-dispatch (the shape)

A step that faces varied inputs (e.g. `fetch-one`) classifies what actually
came back (cheap signal first — headers, byte sniff, status) and dispatches to
a handler. Known cases each get a branch.

## The unknown case must not crash and must not call an LLM

The last branch is the fallthrough: an unrecognized input is **quarantined** —
appended to a manifest (`manifest.jsonl`: input, status, signal, reason) and
skipped — so the batch still finishes. The manifest is the queue of cases the
script does not yet know. That queue is where Claude re-enters, once, to add
the next handler branch.

## Deferred flags

Small known-but-unhandled cases are logged in [`DEVLOG.md`](../../DEVLOG.md)
with a location and a trigger to fix, rather than silently carried.
