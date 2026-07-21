# Rule 07 — One file per user story, indexed

**Each user story lives in its own file under `user-stories/`, and
[`user-stories.md`](../../user-stories.md) is the index that maps every US to
its file, its pipeline step, and its status. Navigate to the one story in play
via the index — never read the whole spec to find it.**

## The principle

The spec grows one story at a time; a single monolithic file forces every
reader (a human, or Claude Code between sessions) to scroll past nine unrelated
stories to reach the tenth. Splitting one-file-per-US means a task that touches
US 9 opens `user-stories/us-09-resolving-open-access.md` alone — smaller context,
no unrelated ACs, no accidental edits to a neighbouring story. The index is the
map; the files are the territory.

## The shape

- **`user-stories.md`** is the **index only**: an intro plus a table with one
  row per US — number (linked to the file), story name, pipeline step/script,
  and status. It carries no acceptance criteria.
- **`user-stories/us-NN-<slug>.md`** holds one story: the `# US N Title`
  heading, the "As a … i want … so that …" statement, its `## Acceptance
  Criteria`, and any `## Case handling` / `## Later stages` sections. `NN` is
  zero-padded (`us-01`, …, `us-10`) so the directory sorts in story order.
- The per-US file carries the **timeless spec** and **no status marker** —
  status is the index's job (single scannable source of truth), so a shipped
  story and its spec never drift apart in two places.

## Adding or changing a story

- **New US** → create `user-stories/us-NN-<slug>.md` (copy a sibling's shape)
  and add its row to the index table. Do both in the same change.
- **Status** → update only the index table's Status column. Flip a US to
  `✅ Done` as the **last commit on its own feature branch**, so the flip rides
  that PR and merges atomically with the story (rule 06 phase 13) — never a
  dedicated PR for the flip, and never a direct commit to `master`. `master`
  still never claims Done before the PR merges, because the flag lives on the
  branch until then.
- **Renaming/renumbering** → keep the file's `NN` slug and the index row in
  lockstep, and fix any `[US N](user-stories/…)` links.

## Why

Navigation cost is real: the value of the spec is that the *relevant* story is
cheap to find and safe to edit in isolation. The index keeps the whole map in
one glance (what exists, what step, what is shipped) while each file keeps its
story self-contained — so Claude reads exactly one US, and a status change is a
one-cell edit in one place.
