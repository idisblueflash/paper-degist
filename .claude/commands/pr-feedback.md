---
description: Process my PR review feedback — fix what I approved, discuss what I asked about, note what I deferred
argument-hint: "[pr number (optional)]"
allowed-tools: Bash(python3 *), Bash(gh *), Bash(git *), Bash(uv *), Read, Edit, Write, Glob, Grep
---

You are processing my review feedback on the pull request for the current
branch. My feedback lives as **replies** to the review findings; each reply
encodes a decision. Your job is to act on each decision, then record what you
did on the PR thread itself.

## The feedback (fetched live)

!`python3 .claude/scripts/pr_feedback.py $ARGUMENTS`

## How to act on each `NEEDS ACTION` thread

Read the finding and my reply together, then classify my reply into exactly one
of three intents and dispatch. When my reply is ambiguous, do NOT guess — treat
it as **discuss**.

1. **FIX** — my reply agrees to change it ("sure", "yes", "we should add this
   case", "do it", "agreed", or a concrete instruction).
   - Implement it following the project rules: **TDD red→green→refactor**
     (`.claude/rules/01-tech-stack.md`) — write/extend the failing test first,
     then the smallest change to pass. Keep steps CLI-runnable
     (`.claude/rules/03-cli-runnable.md`) and consolidate case-handling in the
     script, never an in-loop LLM call (`.claude/rules/02-consolidate-cases-in-script.md`).
   - Run `uv run pytest -q` and `uv run behave` before considering it done.

2. **DISCUSS** — my reply asks a question or requests options ("is there a
   package for this?", anything ending in "?", "what do you think").
   - Do **not** silently implement. Research the question, then answer me here
     in the session with a concrete recommendation and tradeoffs.
   - Also post that answer as a reply on the PR thread (so the discussion is on
     the record). Do not mark it handled beyond posting the answer — I will
     reply again with a decision, which will show up as a new `NEEDS ACTION`
     thread next run.

3. **IGNORE / DEFER** — my reply declines or postpones ("let's not touch this",
   "later", "skip", "won't fix", "consider it when we hit the issue").
   - Do **not** change the code.
   - Leave a note recording the decision: add an entry to `DEVLOG.md` (a
     deferred flag per `.claude/rules/02-consolidate-cases-in-script.md`) with
     the finding location and the trigger that should make us revisit it.

## After acting, record it on the PR

For every thread you handled with a **FIX** or an **IGNORE/DEFER** (and for the
**DISCUSS** answer you posted), reply on that thread so a re-run sees it as
HANDLED. Post the reply to the thread root id shown as `reply-to id for posting`:

```
gh api repos/<owner>/<repo>/pulls/<pr>/comments/<root_id>/replies \
  -f body="<one-line summary of what you did><newline><newline><!-- claude-code:handled --> "
```

Every reply you post **must** end with exactly one marker, on its own line:

- Resolved (FIX, DEFER) → `<!-- claude-code:handled -->`
- Answered-but-open (DISCUSS) → `<!-- claude-code:awaiting-reply -->`

The fetch script flags a thread `NEEDS ACTION` only when its last comment has
**no** marker — i.e. the last word is mine. So marking your DISCUSS answer with
the *awaiting* marker keeps it from being re-answered on the next run, yet the
thread reopens automatically the moment I reply (my reply has no marker).
Suggested bodies:

- FIX:      `Fixed in this branch: <what changed> (test: <test name>).` + handled marker
- DISCUSS:  `<your recommendation / answer, ending in a question to me>.` + awaiting marker
- DEFER:    `Noted as deferred in DEVLOG per your call; will revisit when <trigger>.` + handled marker

## Order of work

1. Group the threads by file so related FIX edits land together.
2. Do all FIX threads first (one focused change + test each), running the suites
   once at the end.
3. Post the DISCUSS answers and DEFER notes.
4. Summarize for me: what you fixed, what you're waiting on my decision for, and
   what you deferred — with the DEVLOG entries you added.

Do not commit or push unless I ask.
