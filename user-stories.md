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
| [US 3](user-stories/us-03-converting-pdf.md)            | Converting PDF                           | *(PDF path)*    | — *(model TBD by bench US 19–23)* |
| [US 4](user-stories/us-04-formatting-paper.md)          | Formatting Paper                         | *(PDF path)*    | —              |
| [US 5](user-stories/us-05-converting-html.md)           | Converting HTML                          | `convert-html`  | ✅ Done         |
| [US 6](user-stories/us-06-importing-paper.md)           | Importing Paper                          | *(wiki import)* | —              |
| [US 7](user-stories/us-07-compiling-paper.md)           | Compiling Paper                          | *(wiki skill)*  | —              |
| [US 8](user-stories/us-08-rating-paper.md)              | Rating Paper                             | *(wiki skill)*  | —              |
| [US 9](user-stories/us-09-resolving-open-access.md)     | Resolving open access for a failed fetch | `resolve-oa`    | ✅ Done         |
| [US 10](user-stories/us-10-resolving-doi-from-title.md) | Resolving a DOI from a title (Crossref)  | `resolve-oa`    | ✅ Done         |
| [US 11](user-stories/us-11-clickable-doi-in-manifest.md) | Clickable DOI link in the manifest record | `resolve-oa`    | ✅ Done         |
| [US 12](user-stories/us-12-recognize-bot-walled-sources.md) | Recognize bot-walled sources on a blocked fetch | `fetch-one`     | ✅ Done         |
| [US 13](user-stories/us-13-verify-filename-matches-title.md) | Verify the saved filename matches the paper's title | `fetch-one`     | ✅ Done |
| [US 14](user-stories/us-14-dedup-inputs-by-doi.md) | Dedup inputs by normalized DOI before fetching | `dedup-inputs`  | —              |
| [US 15](user-stories/us-15-browser-fetch-bot-walled.md) | Fetch a bot-walled page through a dev-mode browser | `browser-fetch` | ✅ Done         |
| [US 16](user-stories/us-16-warm-browser-across-batch.md) | Reuse one warm browser across a batch of URLs | `browser-fetch` | ✅ Done         |
| [US 17](user-stories/us-17-recover-blocked-to-browser.md) | Recover bot-walled records through the browser lane | `recover-blocked` | ✅ Done         |
| [US 18](user-stories/us-18-launch-dev-mode-browser.md) | Launch a dev-mode Chrome for the browser lane | `browser-up`    | ✅ Done         |
| [US 19](user-stories/us-19-render-pdf-pages.md) | Render a PDF to per-page images (OCR bench input) | `render-pdf`    | ✅ Done         |
| [US 20](user-stories/us-20-ocr-one-page-registry.md) | OCR one page with a registered model (stable transport) | `ocr-page`      | ✅ Done         |
| [US 21](user-stories/us-21-reference-free-scorers.md) | Score OCR output with reference-free defect metrics | `score-ocr`     | ✅ Done         |
| [US 22](user-stories/us-22-omnidocbench-gold-accuracy.md) | Score accuracy against an OmniDocBench gold subset | `score-gold`    | ✅ Done         |
| [US 23](user-stories/us-23-aggregate-scorecard-report.md) | Aggregate a model comparison scorecard | `ocr-report`    | ✅ Done         |
| [US 24](user-stories/us-24-embed-text-registry.md) | Embed one text with a registered local model (LM Studio transport) | `embed-text`    | ✅ Done         |
| [US 25](user-stories/us-25-discover-candidates.md) | Discover candidate papers by topic (arXiv / Semantic Scholar) | `discover`      | ✅ Done         |
| [US 26](user-stories/us-26-abstract-filter-embedding.md) | Filter candidates by abstract similarity (deterministic + embedding) | `abstract-filter` | —            |
| [US 27](user-stories/us-27-serpapi-google-scholar.md) | Discover via SerpAPI Google Scholar (topic + author, direct PDF links) | `discover`      | —              |

Adding a story: create `user-stories/us-NN-<slug>.md` and add its row here
(see [rule 07](.claude/rules/07-one-file-per-user-story.md)).
