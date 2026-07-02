# Rule 04 — Anchor review findings to the diff line

**When a code-review finding names a specific `file:line`, post it as an inline
review comment on that line — not as a PR-level (issue) comment that only
mentions the location in prose.**

## The principle

A finding read next to the code it describes needs no hunting: the reader sees
`[^\s)]+` and "this truncates `paper_(v2).pdf`" together. The same text in the
PR comment stream forces the reader to open the file and scroll to the line.
The review tool (Codex, `/code-review`, a human) has already computed the
anchor; posting inline puts the comment where the anchor points instead of
describing the anchor in words. Inline comments also resolve, collapse, and
travel with the code as review threads; issue comments do none of that.

## Classify-then-dispatch (the shape)

Mirror the pipeline's own discipline (rule 02): classify each finding by
whether it has a usable anchor, then dispatch.

- **Has `file:line` that is in the PR diff at the current head SHA** → inline
  review comment (`path`, `line`, `side: RIGHT`, `commit_id: <head sha>`).
- **Anchor is stale or outside the diff** (line drifted since the review ran,
  or points at unchanged context GitHub won't accept) → quarantine to a
  PR-level comment; state that the anchor did not resolve. Never force an
  inline comment onto the wrong line.
- **No single line** (overall verdict, summary, cross-cutting concern) →
  PR-level comment by design.

Verify each anchor against `gh pr diff` before posting; do not trust line
numbers from a review that ran against a local tree that may differ from the
pushed diff.

## Runnable form

Inline comments post via
`gh api repos/{owner}/{repo}/pulls/{n}/comments` with `path`, `line`, `side`,
`commit_id`, and `body` (batchable through `gh pr review`). Post each finding
independently and capture per-comment success/failure, so one rejected anchor
quarantines itself without dropping the rest of the batch.

## Why

A review is only as useful as it is easy to act on. Findings stranded in the
comment stream get skimmed and lost; findings pinned to the line get fixed. The
classify-then-dispatch split keeps the anchoring honest — a comment lands on the
diff only when the diff actually contains the cited line, and everything else is
named as unanchored rather than faked onto a wrong location.
