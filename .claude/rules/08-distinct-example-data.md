# Rule 08 — Distinct, meaningful example data

**When more than one example, scenario, or doc snippet needs a value of the same
kind (a URL, a DOI, a filename), give each a *different* and *descriptive* one —
never copy-paste the same placeholder down the list.**

## The principle

Reused placeholder data reads as noise: three scenarios that all say
`.../publication/249870239_An_investigation` force the reader to diff long
identical strings to see that the scenarios differ at all, and hide which value
each case actually exercises. Distinct, recognizable values make the doc
readable at a glance and the test verbose about its own intent — the URL *is*
the label for what the case is about.

## In practice

- **Feature files (behave).** Each scenario that takes an example URL/DOI/path
  gets its own, chosen so the slug tells you what the scenario is
  (`.../Attention_Is_All_You_Need` for the happy path,
  `.../Deep_Residual_Learning_for_Image_Recognition` for the no-match path). The
  value must still satisfy the step's real precondition (e.g. a slug URL must
  carry an extractable title), so pick a *plausible* real example, not gibberish.
- **CLI manual / docs (`doc/`).** The happy-path example and the quarantine
  example use different inputs, so the reader sees two genuinely distinct cases,
  not one string pasted twice.
- **Unit tests.** When triangulating a behavior across cases, vary the fixture
  value per case rather than reusing one constant, unless the test is
  specifically about the *same* input under different conditions.

## Why

Examples are documentation. Identical repeated values make a reader work to
find the difference and make a test mute about what it covers; distinct
meaningful values turn every example into a self-describing label. This is the
readability grain under rule 06's BDD phase (`.feature` from the AC wording) and
its CLI-manual phase (happy-path + quarantine examples).
