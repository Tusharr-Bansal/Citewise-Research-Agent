# 0018 — A claim-level faithfulness judge, tested against the human-verified labels

**Date:** 2026-10-22 · **Status:** Done: the method was pre-registered and run once. **Negative result:** κ fell from 0.41 to 0.20.

## Context

Decision 0017 found the LLM judge too lenient. Against the 60 reviewed labels (model-assisted drafting, reviewed card by card; see 0017), it caught **1 of 10** answers with a faithfulness problem (κ = 0.41). Every missed error was an **overstatement**: a dropped hedge, a widened quantifier, a detail not in the passage, or a method credited to the wrong paper. The old judge read the answer *as a whole* and gave one verdict. Holistic reading is exactly where small overstatements slip through.

Tushar asked for one attempt at a stricter judge, measured against the **same 60 labels**. He doesn't need to label anything new: the answers and labels are unchanged, only the judge is new.

## Pre-registration (written before any result was seen)

The risk is tuning the judge to these 60 labels until κ looks good, which would measure overfitting, not quality. So:

- **One method, chosen in advance and run once.** No prompt iteration after seeing results. If it fails, that's the result.
- **The judge model is unchanged:** `gemma-4-26b-a4b-it`, temperature 0. The only thing being tested is the *method*.
- **Same inputs:** question, answer, and the cited passages exactly as the old judge saw them.

### The method (`eval/judge_v2.py`)

1. **Claims, not answers.** The judge splits the answer into atomic factual claims. Excluded: statements that information is missing, and identifying which paper is meant.
2. **For each claim** it gives the cited labels, a **verbatim quote** from the cited passages that supports it (empty if none), and one support label:
   - `supported`: the quote states the claim, including its strength (hedges such as *may* or *likely*, quantifiers such as *some* or *primarily*) and every specific detail;
   - `overstated`: the passage supports only a weaker, narrower or more hedged version, or the claim adds a specific detail the passage doesn't state;
   - `wrong_source`: no cited passage supports the claim, or one of its cited passages contradicts it;
   - `unsupported`: nothing in the cited passages supports it.
3. **Quote check in code:** a claim labelled `supported` must have a quote that is actually found in the cited passages. The fuzzy matcher from the gold set (0010) is reused: alphanumeric normalisation, ≥ 85% coverage. If the quote isn't found, the claim counts as not fully supported (partly backed). The model can't certify full support it can't point to.
4. **The verdict is computed in code, not chosen by the model,** mirroring the rubric on the labelling page:
   - no claims → `no_claims`
   - every claim `supported` (with its quote found) → `supported`
   - more than half the claims `unsupported` (nothing backs them; "the main claims aren't backed") → `unsupported`
   - anything in between → `partly`. Overstated, wrong-source, and supported-but-quote-not-found claims all count as *partly backed*.

   **Amendment before the first run:** the first draft said "more than half supported → partly, else unsupported". Unit-testing it showed that a one-claim answer with a small overstatement would be `unsupported`, while the rubric (written on the labelling page *before* any labels existed) defines unsupported as "the main claims aren't backed". The rule was corrected to the rubric's definition. No judge output had been generated or seen when this was changed.

*Implementation fix during the run:* the judge occasionally appended a stray ```` ``` ```` after valid JSON, which crashed parsing at answer 10. The parser now reads the first JSON object and ignores trailing text. This changes no judgement: earlier answers were served from the response cache, unchanged.

*Second fix during the run:* on one answer (a 285-character single-search answer), the judge generated without stopping until the server dropped the request at 300 s, every time, so the run could never finish. Two changes, both about running the judge, not about how it judges:
- **An output cap of 2048 tokens.** A normal claim list is a few hundred tokens. The cap applies to all 60 answers, so all 60 were re-judged under it, at temperature 0, for one consistent run.
- **Dropped connections (`httpx` transport errors) are now retried** like 5xx errors in `llm.py`. That's useful in production too.

*Third fix:* the run then hit the judge model's per-minute token limit (16,000 input tokens a minute), and the retries gave up because they ignored the server's "retry in 25s". `llm.py` now waits at least as long as the server's `RetryInfo` delay (tested in `tests/test_llm.py`). Daily-quota errors still fail fast (0015).

Any answer whose output is still unusable is recorded as **`judge_failed`** and reported. Agreement is computed on the answers the judge could handle, and the failures are listed. A failed answer is never assigned a guessed label.

### What will be reported

- **Primary:** Cohen's κ (4 classes) vs the 60 human-verified labels, with a bootstrap 95% CI.
- Also: binary κ (problem / no problem); errors caught out of 10; false alarms out of 50.
- **Secondary, no extra model calls:** the same run *without* the quote check (step 3), to show what that check contributes.
- Old judge, same 60: κ = 0.41 [0.12, 0.67], binary κ = 0.16, 1/10 caught, 0/50 false alarms.

### Known limitation, stated in advance

The rubric categories (hedge, quantifier, added detail, wrong source) were written down *while labelling these same 60 answers*. A judge built around that rubric is being tested on the data the rubric came from, so the κ will be **optimistic**. An honest confirmation needs a **held-out** set: answers not used to shape the rubric, labelled the same way. That isn't part of this run. It will be listed as the next step, and the result will be described as "on the development set".

## Results (single run, as pre-registered)

The judge failed on 1 of 60 answers (`own:svqmmp8yvn19i2vmf63h|single_shot`: it looped until the 2048-token cap). Agreement is on the other **59**; the old judge is re-scored on the same 59 for a fair comparison.

| Judge (same model, same 59 answers) | Cohen's κ [95% CI] | Raw | Binary κ | Problems caught | False alarms |
|---|---|---|---|---|---|
| Old: holistic verdict | **0.41** [0.12, 0.67] | 0.81 | 0.16 | 1 / 10 | 0 / 49 |
| **New: claim-level + quote check** | **0.20** [−0.03, 0.42] | 0.73 | −0.05 | 1 / 10 | 7 / 49 |
| New, without the quote check | 0.28 [0.06, 0.51] | 0.78 | 0.02 | 1 / 10 | 4 / 49 |

**The pre-registered method made the judge worse.** It still caught only 1 of the 10 problems, and it added false alarms.

## Why it failed (diagnosis from the judge's own claim-by-claim output; nothing re-run)

1. **It finds the right evidence but doesn't notice the claim is stronger than it.** In every one of the 9 missed answers, the judge split out the overstated claim and **quoted the exact sentence that contains the hedge** (quote match 1.00), then labelled the claim `supported`. Examples:
   - claim "differs **primarily due to** noise", with the quote "the difference… **may stem** from data";
   - claim "**specifically trained on infant** and child-centered…", with the quote "trained **primarily** on child-centered";
   - claim "averaging… [S1, S2]", where it quoted only S1 and never checked that S2 contradicts it.

   Getting the judge to point at evidence didn't make it compare *strength*. That's a limit of this judge model (a 26B mixture-of-experts with ~4B active parameters), not of the instructions, which named hedges and quantifiers explicitly.
2. **False alarms came from two mechanical sources:**
   - **"Not found" statements split into claims:** 3 of the 4 "no claims" answers were turned into "unsupported" because the judge listed "the passages do not mention X" as a claim, against an explicit instruction. That's an instruction-following failure.
   - **The quote check is brittle on table text:** 3 false alarms were claims taken from garbled PDF tables (e.g. parameter counts), where the quote is paraphrased or reordered and matches only 0.38–0.84. Without the check, these three pass.

## Decision

- **Keep the old judge as the automatic metric, and keep its κ = 0.41 as the reported number.** The README and resume figures don't change: human-verified faithfulness of 83%, with the judge's agreement disclosed.
- **No further prompt changes on these 60 labels.** The two mechanical fixes (filtering "not found" statements in code; relaxing the quote check for table text) are obvious, but making them after seeing these results and re-scoring the same 60 would be tuning to the test set. They would need a **held-out labelled set**.
- **What would most likely work, not done:** a **stronger judge model**. Every miss was a reasoning failure on evidence the judge had already found. Cost is the obstacle: the stronger Gemini models allow ~20 free requests a day, so this means a paid key (a few cents for 60 answers) or three days of free quota.

## What this shows (the interview version)

- **Validate the evaluator, not just the system.** The holistic judge looked fine at 98%. Checking it against labels showed it misses overstatement, and checking the fix showed that the "obvious" fix (claim decomposition) doesn't help with this model.
- **Pre-registration plus a single run** is what makes a negative result trustworthy. Without it, the temptation is to adjust prompts until the 60 labels agree.
- **Small open models find evidence well but compare meaning poorly:** they spot the right sentence but don't notice "may" became "primarily". That's a concrete, demonstrated failure mode, not a general claim.
