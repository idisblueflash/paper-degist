# US 13 Verify the saved filename matches the paper's title

As a *researcher browsing `files/` by hand*, i want *fetch-one to flag when a
saved file's name does not reflect the paper's actual title*, so that *I can
spot the generic, collision-prone names (`10.pdf`, `viewcontent.cgi.pdf`) and
rename them* instead of discovering two unrelated papers saved under the same
meaningless basename.

fetch-one derives the filename from the URL basename (US 2 filename rule). For
a slug URL that basename is descriptive, but for a repository or CGI endpoint it
is not: `https://rdw.rowan.edu/cgi/viewcontent.cgi?article=1080&context=etd`
saves as `viewcontent.cgi.pdf`, and `.../Vol_3_No_1_March_2016/10.pdf` saves as
`10.pdf` — the paper's identity lives in the query string or path, not the
basename, so several distinct papers can collapse onto one name. This story does
**not** change how files are named (that stays the US 2 basename rule, which the
idempotent skip-on-re-run depends on). It adds a **verification** step: after a
successful save, compare the file's real title to its filename and, on a
mismatch, quarantine a record naming both — a hand-off for a human to rename,
never an automatic rename and never a crash.

The scope is an **additive, read-side check** on fetch-one's successful-save
path only. It does not rename files, does not change the filename rule or the
skip-on-re-run behavior, does not change stdout (the saved path still prints) or
the success exit code, and does not call an LLM — the title comes from the file
itself (HTML `<title>`, PDF metadata).

## Acceptance Criteria

1. Given a saved file whose slugified title matches its basename
   (e.g. `files/using-keyword-method-learn-vocabulary.html` whose `<title>` is
   "Using the Keyword Method to Learn Vocabulary")
   - when fetch-one verifies the save
     - then no manifest record is written — the name already reflects the title
2. Given a saved file whose title does **not** match its basename
   (e.g. `files/viewcontent.cgi.pdf` whose PDF title is "Effects of the Keyword
   Method on Vocabulary Acquisition and Retention")
   - when fetch-one verifies the save
     - then it appends a `mismatch` record to `manifest.jsonl` carrying the
       saved `file`, the extracted `title`, and a `reason` that the filename does
       not reflect the title — a rename hand-off for a human
     - and the file stays saved and the step still exits cleanly (the mismatch is
       a note, not a failure)
3. Given a saved file whose title cannot be extracted (no `<title>`, no PDF
   metadata title, or a format the check cannot read)
   - when fetch-one cannot verify
     - then it records a `title-unverifiable` reason (not a mismatch — absence of
       a title is not a wrong name) and moves on without crashing
4. Given the verification records
   - then they are additive fetch-one records — the save path, filename rule, and
     every other stage's record shape are unchanged, and the manifest stays
     append-only

## Case handling (classify-then-dispatch)

After a successful save, fetch-one classifies on the extracted title: title
present and its slug equals the basename → verified, no record; title present
and its slug differs → `mismatch` quarantine (file + title + reason); title
absent/unextractable → `title-unverifiable` quarantine. "Match" is a comparison
of *slugs* (lowercase, punctuation-stripped, hyphen-joined), not raw strings, so
trivial punctuation/case differences are not false mismatches. The extractor
dispatches on the saved type — `<title>` for HTML, document metadata for PDF —
and the unextractable case is itself a branch, so the check never crashes.

## Later stages (deferred)

- **Auto-rename to the title.** This story only *flags* a mismatch; deriving the
  canonical filename from the title is a separate, larger change that interacts
  with the US 2 idempotent-skip rule (what "already exists" means once the name
  is title-derived). Considered and deferred — see the "Derive name from title"
  option and DEVLOG.
- **PDF title extraction depth.** Reading PDF *metadata* is light; falling back
  to first-page text when metadata is empty overlaps the PDF-parsing path
  (US 3/4, not yet built). If metadata is absent, this story takes the
  `title-unverifiable` branch rather than reaching into PDF body text — that
  deeper extraction is deferred to the PDF stage.
