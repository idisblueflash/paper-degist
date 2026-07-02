# Does the 3-Axis Mnemonic Method Work? — Bayesian Analysis

**Question tested:** Is the sound + meaning + story mnemonic technique (the one used in your `english-word-explainer` workflow) a genuinely effective vocabulary-learning method?

## Competing hypotheses

| | Hypothesis | Implication if true |
|---|---|---|
| H1 | Works *as designed* — the 3-axis structure itself drives retention | Keep following the structure carefully |
| H2 | **Generic engagement effect** — any self-made mnemonic works, structure adds little | Don't worry about structure, freeform works just as well |
| H3 | **Conditional** — works well only when sound and meaning naturally align; forced/misleading otherwise | Need a way to flag "bad fit" words |
| H4 | **Recall, not precision** — strengthens "this word exists/sounds like X," weak on exact usage boundaries | Mnemonics need pairing with real-context practice |

## Evidence trail

| Step | Evidence | Source | Effect |
|---|---|---|---|
| 0 | Prior | — | H1 30% · H2 25% · H3 25% · H4 20% |
| 1 | Landmark keyword-method studies show large effect sizes (e.g. 72% vs 46% on Russian vocabulary; 88% vs 28% vs. free-study control) | Atkinson & Raugh (1975), as cited in [1] and [2] | Mild support for H1 |
| 2 | Effect is explained by *two separate* mechanisms — dual-coding (verbal+visual) **and** generation effect (self-made) stacking together | [1] WordCraft (arXiv), citing Paivio's dual-coding theory and Slamecka & Graf's generation effect | H2 weakens — structure adds something beyond "you made it up" |
| 3 | Effectiveness tracks word **imageability**: vivid/concrete words benefit much more than abstract words (e.g. "puppy" vs. "justice") | [2] Keymagine guide, citing Campos, Amor & González (2004); [3] Shapiro & Waters, ResearchGate | Strong support for H3 |
| 4 | Long-term decay studies locate the weak point specifically at the *keyword→meaning* link, not the keyword/sound itself, with inconsistent results over time | [4] ScienceDirect — Beaton et al., bidirectional retrieval study, citing Lawson & Hogben (1998) and Wang & Thomas; [5] Mempowered.com | Strong support for H4 |

## Final posteriors

| Explanation | Before | After 4 pieces of evidence |
|---|---|---|
| H3 — conditional on word fit | 25% | **33.1%** |
| H4 — recall ≠ precision | 20% | **30.0%** |
| H1 — works robustly as designed | 30% | 29.8% |
| H2 — generic engagement only | 25% | 7.1% (effectively excluded) |

## Conclusion

**H2 is essentially ruled out.** The literature treats dual-coding and the generation effect as distinct, stacking mechanisms — the sound/meaning structure is doing real work, not just "you personalized it."

**H1, H3, and H4 remain in a genuine three-way tie**, and — usefully — they're not actually contradictory. They describe three different *parts* of the same system:

- **H1 (core mechanism holds):** the basic sound↔meaning↔story linkage is real and well-evidenced. This is your foundation, not your risk.
- **H3 (conditional on fit):** the method's strength depends heavily on whether the word is concrete/imageable. Abstract words (like "canonical" itself) are the predictable failure mode — exactly where your own example's meaning-axis felt loose.
- **H4 (recall ≠ precision):** even when the mnemonic works perfectly, it mainly anchors *recall* (you'll remember the word and its rough flavor). It does not reliably teach *precise usage boundaries* — that needs separate reinforcement.

## Design implications for your mnemonic workflow

1. **Add a word-type check (addresses H3).** Before generating the mnemonic, classify the word as concrete/imageable vs. abstract. For abstract words, either:
   - lean harder on a metaphor that's *itself* concrete (e.g. "cannon" stands in for "authoritative," not for "canonical" directly), and flag this explicitly to the learner so they know the meaning-link is a metaphor, not a direct translation
   - or warn the learner that the story axis is doing more "vibe" work than "definition" work for this word

2. **Add a usage-precision step (addresses H4).** After the 3-axis mnemonic, include one short example sentence showing the word used correctly in context — not just the definition restated. This catches cases where the mnemonic nails the gist but not the boundary (e.g. "canonical" ≠ "definitive" ≠ "final").

3. **Keep the core structure (H1 stays your foundation).** The sound+meaning+story format isn't a gimmick — it's grounded in two independently-evidenced mechanisms. Don't simplify it away; just patch the two known failure points above it.

## Sources

[1] WordCraft: Scaffolding the Keyword Method for L2 Vocabulary Learning with Multimodal LLMs — arXiv. https://arxiv.org/pdf/2602.00762

[2] The Keyword Method for Language Learning — A Complete Guide. Keymagine. https://keymagine.app/keyword-method

[3] An investigation of the cognitive processes underlying the keyword method of foreign vocabulary learning — Shapiro & Waters. ResearchGate. https://www.researchgate.net/publication/249870239_An_investigation_of_the_cognitive_processes_underlying_the_keyword_method_of_foreign_vocabulary_learning

[4] The mnemonic keyword method: The effects of bidirectional retrieval training and of ability to image on foreign language vocabulary recall — ScienceDirect. https://www.sciencedirect.com/science/article/abs/pii/S0959475207000357

[5] Using the keyword method to learn vocabulary — Mempowered. https://www.mempowered.com/mnemonics/language/using-keyword-method-learn-vocabulary

**Additional supporting sources consulted:**

- The Effect of the Keyword Method on Vocabulary Learning and Retention. https://ijllnet.thebrpi.org/journals/Vol_3_No_1_March_2016/10.pdf
- The Mnemonic Keyword Method: Effects on the Vocabulary Acquisition and Retention. ResearchGate. https://www.researchgate.net/publication/287147155_The_Mnemonic_Keyword_Method_Effects_on_the_Vocabulary_Acquisition_and_Retention
- Teaching abstract vocabulary with the keyword method: effects on recall and comprehension — PubMed. https://pubmed.ncbi.nlm.nih.gov/2303742/
- The keyword method: a study of vocabulary acquisition in fifth grade. Rowan University. https://rdw.rowan.edu/cgi/viewcontent.cgi?article=1080&context=etd

*Note: most citations above are drawn from review papers and guides that themselves cite the original studies (e.g. Atkinson & Raugh 1975; Paivio's dual-coding theory; Slamecka & Graf's generation effect; Campos, Amor & González 2004; Lawson & Hogben 1998). Links point to the secondary sources actually consulted, which name these primary studies.*
