# 0016 — The agent always searches the user's question as typed

**Date:** 2026-10-22 · **Status:** Accepted (Tushar approved; to be measured) · Amends 0012

## Context

Re-running the evaluation with the generalized prompts (0014) produced a regression. The run was cut short by the daily quota, so these are partial numbers: ~40 single-passage questions per system, same gold set, same judge.

| | Correct | Evidence reached the answer step |
|---|---|---|
| Single search (the question as typed) | 0.88 | 0.81 |
| Agent, generalized prompts | **0.78** | **0.72** |
| Agent, original PCG prompts (v1, same questions) | 0.89 | 0.82 |

Per question against v1: **5 agent answers went correct → incorrect, 1 incorrect → correct.** In 4 of the 5, the gold passage never reached the answer step.

**Root cause, from the traces.** The agent's only first-round searches were the ones its planner wrote. For "How can S1 and S2 be told apart using timing alone?":
- v1 planned *"differentiating S1 and S2 using timing alone"*, close to the user's words, and found Taipalmaa 2018.
- v2 planned only *"systolic time interval S1 and S2 differentiation timing heart sound phonocardiogram"*: keyword-stuffed, it pulled in generic passages and missed the answer.

The plain question found the passage. The agent was throwing away its best query.

This is a *design* flaw that the prompt change exposed, not a prompt bug: any planner, under any prompt, can rewrite a question worse than the original. Tuning the prompt until the numbers recover would just hide the flaw again.

## Decision

In the first round, the agent always searches the user's question **exactly as typed**, alongside the planned queries. That search's results are **guaranteed half the evidence budget** (`ORIGINAL_QUERY_HITS = MAX_EVIDENCE // 2` = 7 passages, placed first). The planned and follow-up queries fill the rest, interleaved as before (`anchored()` in `agent.py`).

- **Cost:** none in LLM calls. A search is local (BM25 + vector); only the plan, check and answer steps call the model.
- **Guarantee:** the agent's evidence always contains the plain search's top 7. Its own queries can add to that but can't push it out.
- The check step sees the original question among "queries already run", so it won't suggest it again.
- A planned query identical to the question is skipped (no duplicate search).

**Why half (7), and how it was chosen.** It's a principle: the user's own wording gets half the budget, the agent's exploration the other half. In the interest of disclosure, I also looked at where the gold passage ranks in the plain search on this test set: rank 1–7 in 31 of 34 found cases, ranks 9–14 in 3. A cutoff picked by looking at test-set ranks is mild tuning on the test set, so 7 was kept at the principled value rather than raised to cover every case. The proper check is a held-out set (future work).

## Alternatives considered

- **Revert to the PCG-specific prompt:** it worked for v1 because its wording happened to keep queries close to the user's. But Citewise is general now, so this isn't an option.
- **Tune the planning prompt** ("keep the first query close to the user's wording"): it asks the model to do what code can guarantee, and it's not verifiable without re-running the evaluation for each wording.
- **Give the original search the full budget, as in the single search:** then the agent can't add anything without displacing it, which defeats the purpose.
- **Skip planning when the question looks simple:** this saves calls, but needs a classifier, which is a separate decision.

## Evidence so far

- **Unit test:** `test_anchored_keeps_the_original_query_results_first_and_whole`.
- **Stub-LLM run** of the S1/S2 question (planner forced to return the bad v2 query): the gold passage `taipalmaa2018_cycle_segmentation:010` is now in the agent's evidence (it was missing before), with the same 3 LLM calls.
- **The real measurement is the evaluation re-run (0017).** Pre-fix agent rows are archived in `eval/results/agent_eval_v2a_before_anchor.json`, so the before/after comparison is paired on identical questions.

## Be ready to explain

- Query rewriting in RAG (multi-query, HyDE-style expansion) and its failure mode: the rewrite drifts from the user's intent.
- "Guarantee in code, don't ask the model": the same principle as validating citations in code (0012).
- How a prompt change silently moved a downstream metric, and how a paired per-question comparison with the search traces found the cause.
- Test-set tuning: why you resist picking hyperparameters from the test set's own ranks, and say so when you've looked.
