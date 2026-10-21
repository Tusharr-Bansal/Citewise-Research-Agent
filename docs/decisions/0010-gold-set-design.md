# 0010 — Gold test set: LLM-drafted, human-verified, anchored to evidence quotes

**Date:** 2026-10-22 · **Status:** Accepted

## Context

Retrieval quality (recall@10) needs a set of questions where we know *where* the answer is. Writing ~50 good questions with exact evidence by hand would take hours. Having an LLM write them and trusting the result would make the test set as unreliable as the system under test.

## Decision

1. **Draft with the LLM, verify by hand.** For each paper, 2 substantive chunks are sampled (≥200 tokens, mostly prose, not page 1) using a fixed per-paper random seed, so adding papers never changes another paper's sample. Gemini drafts one question per chunk, plus an answer and a verbatim **evidence quote**. 52 passages → 51 drafts (1 skipped as non-substantive).
2. **Tushar reviews every draft** in a private labeling page (`eval/labeling/index.html`, published as an artifact with a database only he can write to): **Good / Fix (rewrite) / Drop**, plus an **Ambiguous** flag for questions several papers could answer.
3. **Tushar adds ~10 questions of his own**, written without looking at any passage.
4. **Relevance is judged by evidence quote, not chunk ID** (see 0008): a retrieved chunk counts as a hit if it contains the quote.
5. **Results are reported in slices:** drafted vs. human-written, and unambiguous vs. ambiguous.

## Known biases and how they're handled

| Bias | Why it happens | Mitigation |
|---|---|---|
| **Lexical overlap** | A question written while looking at a passage tends to reuse its words, which flatters keyword search | Prompt demands paraphrase. The overlap of each question with its evidence is measured (median 0.33, 75th percentile 0.43, max 0.82). Tushar rewrites copy-paste questions. His own questions form a separate, unbiased slice. |
| **Single-answer assumption** | Many papers describe the same dataset or method, so "the" answer often exists in several places | "Ambiguous" flag; ambiguous questions are scored separately instead of silently counting as misses. |
| **Sampling only answerable, single-chunk questions** | Drafting from one chunk can't produce cross-paper questions | Tushar's own questions cover multi-paper synthesis. Agent-level evaluation (later) adds such questions too. |
| **Verbatim-quote errors** | The LLM sometimes alters text when "copying" | Each quote is checked against its passage; 3 of 51 failed and are flagged in the labeling page. |

## Alternatives considered

- **Fully synthetic test set (no human).** Fast, but you'd be grading the system with the same kind of model that built it. Rejected.
- **Fully hand-written test set.** Least biased, but too slow for a 29-paper corpus. Used as one slice instead.
- **Chunk-ID relevance labels.** Simpler, but they break whenever chunking changes (see 0008).

## Be ready to explain

- Why an eval set needs human verification, and what "golden dataset" means in practice.
- Lexical-overlap bias: why LLM-generated questions make BM25 look better than it is, and how you measured and controlled for it.
- Why ambiguous questions are separated rather than dropped (dropping them hides a real weakness; mixing them in understates recall).

## Outcome of the review (2026-10-22)

Tushar reviewed all 51 drafts: **24 kept as written, 21 rewritten, 6 dropped**; 10 of the 45 kept are flagged ambiguous. He also wrote **13 synthesis questions**, all spanning several papers.

Why drafts were rewritten or dropped (from discussing individual cards during review):
- **Vague subject on a paper-specific detail** (the most common): "the model", "the framework", "the preprocessing routine" asking for one paper's number or setting, where another paper's answer would be wrong. Fixed by naming the method (EHST, HnLTS, FunnelNet…) without naming the paper.
- **Copying the passage** (lexical overlap up to 0.82), or the opposite, **over-paraphrasing** ("a self-supervised speech representation architecture" instead of "wav2vec 2.0").
- **Reverse lookups** that list the answer's attributes and ask for its name (e.g. a dataset described by its sample count).
- **Citation summaries**: passages describing someone else's work (related-work sections), where the true source isn't in the corpus. Dropped.
- **Wrong drafted answers from flattened tables** (the ChildVox score table, where 15 of 30 cells survived extraction). Dropped. A "correct answer" that is wrong would penalise the system for being right.
- **Inflated totals** ("total features: 594" when 594 was one feature group of several). Rewritten to the sub-count.
- **A duplicate** caused by sampling two overlapping neighbouring chunks. The sampler now rejects neighbours (index distance < 2).

Lesson: an LLM-drafted question set needed human changes to 53% of its items. Unreviewed, it would also have overstated recall by about 40 points (see 0011).
