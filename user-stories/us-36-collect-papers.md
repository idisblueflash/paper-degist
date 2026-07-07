# US 36 Collect converted papers to a target folder

As a *researcher who has run the full convert pipeline for a topic*, i want
*all converted Markdown files under `files/<topic>/` to be copied into a target
folder in one command*, so that my downstream research workspace receives a
clean, complete set of paper MDs without manual file-picking.

## Background

After `fetch-one` → `convert-html` / `convert-pdf`, each paper's `.md` lives
at `files/<topic>/<stem>.md`. The topic subfolder (e.g. `files/mnemonic-method/`)
is already the natural grouping unit — it is the `--files-dir` value passed to
`fetch-one` (US 2) and `browser-fetch` (US 15) when the batch was fetched:

```
uv run fetch-one <url> --files-dir files/mnemonic-method
uv run browser-fetch <url> --files-dir files/mnemonic-method
```

`recover-blocked` (US 17) drains bot-walled records through the same
`--files-dir`, so all lanes for a topic converge on one folder. The convert
steps (`convert-html` US 5, `convert-pdf` US 3) write their `.md` alongside
the source file, so `files/<topic>/<stem>.md` is the settled contract.

`collect-papers` closes the loop: given a topic name, it finds every `.md`
inside `files/<topic>/` and copies it to the target directory
(e.g. `/Users/husongtao/Projects/research-room/raw`). No JSONL manifest is
needed — the folder is the list.

The step is **read-only with respect to `files/`**: it copies, never moves or
modifies, so re-running is safe and idempotent.

## Acceptance Criteria

1. Given a topic folder `files/mnemonic-method/` containing several `.md` files,
   when `collect-papers mnemonic-method --dest /path/to/raw` runs,
   then every `.md` in that folder is copied into `/path/to/raw/` and the step
   exits 0
2. Given the topic folder contains no `.md` files (all papers still pending
   conversion),
   when `collect-papers` runs,
   then it exits 0 with a warning and copies nothing — never crashes
3. Given a `.md` that already exists in `--dest` on a previous run
   (idempotency),
   when `collect-papers` runs again,
   then the file is overwritten and the step exits 0 — no duplicate is created;
   with `--skip-existing` it is skipped instead
4. Given a topic name that does not match any subfolder under `files/`,
   when `collect-papers` runs,
   then it exits non-zero with a clear error message — never silently copies
   nothing

## Case handling (classify-then-dispatch)

- Topic folder does not exist → exit non-zero, print error.
- Topic folder exists, no `.md` files → exit 0, print warning.
- `.md` found, dest file absent → copy.
- `.md` found, dest file present, `--skip-existing` off → overwrite.
- `.md` found, dest file present, `--skip-existing` on → skip.

## Arguments and options

```
uv run collect-papers TOPIC
                      --dest DIR              (required: target folder)
                      [--files-dir DIR]       (default: files/)
                      [--skip-existing]       (skip instead of overwrite)
```

`TOPIC` is the subfolder name under `--files-dir` (e.g. `mnemonic-method`).

## Later stages (deferred)

- **Move mode.** A `--move` flag that moves instead of copies, for operators
  who want to clear `files/<topic>/` after staging.
- **Summary report.** Print a one-line count of copied vs. skipped at exit.
- **Multi-topic.** Accept multiple TOPIC arguments or a glob to collect across
  several topics in one invocation.
