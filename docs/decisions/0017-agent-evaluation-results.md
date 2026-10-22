# 0017 — Agent evaluation: results on the shipped system

**Date:** 2026-10-22 · **Status:** Final

## What was measured

- **Systems:** the shipped agent (generalized prompts + the original-question anchor from 0016) vs a single hybrid search with the same answer prompt and evidence budget.
- **Questions:** 45 single-passage questions with a verified evidence quote, plus 13 multi-paper synthesis questions Tushar wrote (no single right passage).
- **Judge:** `gemma-4-26b-a4b-it`, a different model from the one answering (`gemini-3.5-flash-lite`), to limit self-preference bias.

**Metrics:**
- **Evidence:** did the gold passage reach the answer step?
- **Correct:** judge's verdict against the reference answer.
- **Credit:** correct = 1, partial = 0.5, incorrect = 0.
- **No unsupported claims:** judge's faithfulness verdict is "supported" or "no claims".

Scripts: `eval/eval_agent.py` (answers and judging), `eval/compare_runs.py` (paired comparison, bootstrap CIs) → `eval/results/comparison.json`.

## Results

| System | Evidence (45) | Correct (45) | Credit (45) | No unsupported claims (58) |
|---|---|---|---|---|
| Single search | 0.82 | 0.87 | 0.90 | 1.00 |
| **Agent, shipped** | **0.89** | 0.87 | 0.91 | 0.98 |
| Agent before the fix (0016), partial run | 0.71 (41) | 0.78 (41) | 0.82 (41) | 1.00 (40) |
| Agent v1, original PCG prompts | 0.82 | 0.89 (44) | 0.92 (44) | 0.98 (56) |

**Paired differences** (same questions; 95% paired-bootstrap interval; an interval containing 0 is not distinguishable from noise):

| Comparison | Evidence | Credit |
|---|---|---|
| Shipped agent − single search | +0.07 [−0.04, +0.18] | +0.01 [−0.09, +0.11] |
| Shipped agent − agent before fix | **+0.17 [+0.05, +0.32]** | +0.10 [−0.01, +0.22] |
| Shipped agent − agent v1 | +0.07 [+0.00, +0.16] | +0.00 [−0.03, +0.03] |

**Cost per question (medians):**

| | LLM calls | Input tokens | Latency |
|---|---|---|---|
| Single search | 1 | 5.1k | 4.0 s |
| Agent | 3 | 8.7k | 8.4 s |

**Synthesis questions:** the agent cites 2.6 distinct papers per answer vs 2.3 for the single search. That's breadth, not quality.

## What this means (stated plainly)

1. **The fix in 0016 worked and is the one clearly significant result.** It recovered the evidence the generalized planner was losing (+17 points).
2. **On this test set, the agent does not measurably beat a single hybrid search.** Evidence is +7 points and correctness level, both within noise, at 3× the LLM calls and 2× the latency. The likely reason is that hybrid retrieval (0011) is already strong: the plain question finds the passage 82% of the time, which leaves the agent little room. Single-passage questions are also the case where an agent should help least.
3. **Faithfulness is near the ceiling for both systems** (judge: 98–100% with no unsupported claims). A judge this lenient is only meaningful if it agrees with a human, which is the next measurement. A judge that rarely says "unsupported" is useless as a regression check if it misses real errors.
4. **Honest framing for the README and resume:** "measured", not "the agent is better". The engineering story is the regression caught by evaluation, root-caused from traces, and fixed with a code guarantee; plus a measured cost/benefit of agentic retrieval.

## Possible next decisions (not taken; Tushar decides)

- Offer a fast single-search mode, or route questions: single search first, and the agent loop only when the evidence check fails. This would cut median cost about 3× if most questions resolve in one search.
- Write harder test questions (multi-hop, cross-paper comparisons) where an agent should matter, to measure where it pays off.

## Judge–human agreement on faithfulness

**Sample:** 60 answers, 30 per system: every answer the judge didn't rate "supported", plus a random draw (seed 17). Shown **blind** (random ids, no system name, no judge verdict). Scripts: `eval/make_faith_sample.py`, `eval/judge_agreement.py` → `eval/results/judge_agreement.json`.

**Labelling method:** labels were drafted with model assistance (a verdict and a one-line reason per card) and reviewed card by card against the cited passages by Tushar, who set each final label. The labelling rules were made explicit along the way:
- a claim not in the cited passage, stated as fact, is at least Partly;
- a marked interpretation is fine;
- naming which paper is meant is fine;
- a cited passage that *contradicts* a grouped claim is Partly;
- "No claims" only when an answer says nothing factual.

*Limitation:* reviewed drafts can anchor the reviewer towards the draft, so the labels may lean towards the drafting model's reading; independent labelling would remove that.

**The judge measured against the reviewed labels** (the labels as the reference):

| Metric | LLM judge |
|---|---|
| Accuracy (4 classes) | 0.82 |
| Accuracy of always answering "supported" (baseline) | 0.77 |
| Specificity: clean answers passed | **1.00** (50/50) |
| Precision: answers it flagged that really had a problem | **1.00** (1/1) |
| Recall: answers with a problem that it flagged | **0.10** (1/10) |
| Balanced accuracy | 0.55 |
| Cohen's κ (secondary; distorted by the 46/60 class imbalance) | 0.41 [0.12, 0.67] |

**Confusion matrix** (rows = human, columns = judge):

| | Supported | Partly | Unsupported | No claims |
|---|---|---|---|---|
| Supported | 44 | 0 | 0 | 2 |
| Partly | **9** | 1 | 0 | 0 |
| No claims | 0 | 0 | 0 | 4 |

**What this shows:**
1. **The judge is reliable when it flags, and lenient otherwise.** It passed every clean answer and every flag it raised was right, but it caught 1 of the 10 answers with an overstatement. Its 82% accuracy is only 5 points above always saying "supported", so it can't be the faithfulness metric on its own.
2. **The real error type is overstatement, not invention.** None of the 60 answers was Unsupported. The 10 Partly answers all have the same subtle pattern:
   - a hedge dropped ("may stem" → "primarily due to");
   - a quantifier widened ("some" → all; "primarily" → "specifically");
   - a detail from the question presented as the passage's ("standard", "infant", "segment-level");
   - one method attributed to the wrong paper (averaging vs majority vote);
   - two sentences of the same passage merged into one wrong purpose.

   These are exactly the errors an LLM judge tends to miss.
3. **Faithfulness is lower than the judge reported.** Human-verified "no unsupported claims": 0.83 overall (50/60) vs the judge's 0.98.
4. **By system (unblinded after labelling):**

   | | Clean (supported or no claims) | Partly |
   |---|---|---|
   | Single search | 0.90 | 3/30 |
   | Agent | 0.77 | 7/30 |

   The agent writes longer, more synthetic answers across more passages, which gives more room to overstate. With 30 per side this is a direction, not a significant difference, but it adds to the cost side of the agent's ledger (3× calls, 2× latency, no measured accuracy gain).

**Consequences:**
- The automatic faithfulness score **is not trusted on its own**. The README reports the reviewed figure (83% fully faithful, 0% unsupported).
- **Tried afterwards (0018):** a claim-level judge with a quote check, pre-registered and run once on the same labels. It did worse (κ 0.20) and still caught 1 of 10. The judge model quotes the right evidence but misses the overstatement. The old judge and κ = 0.41 stay.
- Not done: tell the answer prompt to keep the source's hedges and quantifiers. Every Partly error falls into that category.

## Be ready to explain

- Paired bootstrap confidence intervals, and why 45 questions can't resolve a 7-point difference.
- Why a null result is still worth reporting, and how it changes the design (routing).
- Cost/latency trade-offs of agentic RAG.
- Judge leniency, ceiling effects, and why judge–human agreement has to be measured before trusting the judge.
- Evaluating a judge against a reference: accuracy vs a majority baseline, recall/specificity/precision, and why κ is distorted under class imbalance.
- Model-assisted labelling: drafting plus card-by-card review, and the anchoring limitation.
