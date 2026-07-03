# User Stories — index

The spec is split one story per file under [`user-stories/`](user-stories/), so
a reader (or Claude Code) opens **only** the story in play instead of scrolling
the whole spec. This file is the index: it maps each US to its file, its
pipeline step, and its status. Navigate from here — don't read the others.

**Status** is tracked here (the single scannable source). Flip a US to
`✅ Done` as the last commit on its feature branch, so it merges with the story
(rule 06 phase 12) — never a dedicated PR, never a direct commit to master.
master never claims Done before the PR merges. The per-US files hold the
timeless spec and carry no status marker.

| US                                                      | Story                                    | Step / script   | Status         |
| ------------------------------------------------------- | ---------------------------------------- | --------------- | -------------- |
| [US 1](user-stories/us-01-parsing-the-links.md)         | Parsing the links                        | `parse-url`     | ✅ Done         |
| [US 2](user-stories/us-02-fetching-the-paper-file.md)   | Fetching the paper file                  | `fetch-one`     | ✅ Done         |
| [US 3](user-stories/us-03-converting-pdf.md)            | Converting PDF                           | *(PDF path)*    | —              |
| [US 4](user-stories/us-04-formatting-paper.md)          | Formatting Paper                         | *(PDF path)*    | —              |
| [US 5](user-stories/us-05-converting-html.md)           | Converting HTML                          | `convert-html`  | ✅ Done         |
| [US 6](user-stories/us-06-importing-paper.md)           | Importing Paper                          | *(wiki import)* | —              |
| [US 7](user-stories/us-07-compiling-paper.md)           | Compiling Paper                          | *(wiki skill)*  | —              |
| [US 8](user-stories/us-08-rating-paper.md)              | Rating Paper                             | *(wiki skill)*  | —              |
| [US 9](user-stories/us-09-resolving-open-access.md)     | Resolving open access for a failed fetch | `resolve-oa`    | ✅ Done         |
| [US 10](user-stories/us-10-resolving-doi-from-title.md) | Resolving a DOI from a title (Crossref)  | `resolve-oa`    | ✅ Done         |

Adding a story: create `user-stories/us-NN-<slug>.md` and add its row here
(see [rule 07](.claude/rules/07-one-file-per-user-story.md)).
