# 0012 — Agent: a hand-written plan → search → check → answer loop with guards

**Date:** 2026-10-22 · **Status:** Accepted (behaviour to be measured in the agent evaluation)

## Context

Single-shot retrieval misses evidence in two measurable ways (0011): the right paper but the wrong passage, and questions whose wording shares little with the evidence. Tushar's 13 synthesis questions also need evidence from several papers, which one search can't gather. The agent's job is to search *iteratively* and answer only from what it found.

## Decision

`src/pcg_agent/agent.py`, about 200 lines, no framework:

1. **Plan**: the LLM writes 1–3 queries, one per part of the question, with abbreviations spelled out ("STFT short-time Fourier transform").
2. **Search**: hybrid retrieval (0011), 6 passages per query. Results are **interleaved by rank across queries**, so every part of the question is represented when the evidence budget (14 passages) is tight.
3. **Check**: the LLM decides whether the evidence is *sufficient*. If not, it writes new queries in different wording and can **restrict a query to one paper** when it can see which paper should contain the missing detail (paper-scoped search).
4. **Answer**: the LLM answers only from the passages, citing `[S#]` after every factual sentence, flags disagreements between sources, and states `answerable: yes / partly / no`. **Code** then parses the citations (`[S3]`, `[S3, S5]`, `[S3; S5]`) and verifies each one refers to a passage that was actually shown; anything else is reported as an invalid citation.

**Guards:** at most 3 search rounds and 6 LLM calls per question (a hard error beyond that); every step goes into a structured trace (queries, paper filter, hits, new hits, tokens, latency, cache status).

## Evidence that shaped it (first live runs, 2026-10-22)

| Problem observed | Fix | After |
|---|---|---|
| Gemini cited `[S3, S5, S7]`; the parser only knew `[S3]`, so no citations were recorded | Parse grouped citations; unit-tested | Citations recorded and validated |
| *"What STFT settings does the murmur-and-outcome ensemble use?"*: the paper writes "short-time Fourier transform", never "STFT". After 3 rounds the agent correctly said "not in the evidence" (it didn't hallucinate) but never found the passage. The check step *named the right paper* but couldn't search inside it. | Abbreviation rule + paper-scoped search | Found and cited `festag2022:005` in round 3; exact settings correct; 4 LLM calls, 13 s |
| *"Which papers use MC Dropout and how do they measure it?"* finds Zhang (entropy) and De Simone, but misses Bondareva (who writes "deviation of the predictions") | Not fixed. "Find every paper that…" is a known weak spot for retrieval-based QA; tuning prompts to one question would overfit | Answer correctly says it's partial. Frequency to be measured in the evaluation |

## Alternatives considered

- **LangGraph** (the common 2026 choice for stateful agents). Its strengths (checkpointing, human-in-the-loop pauses, resumable graphs) aren't needed for a 4-step, sub-20-second loop. A plain loop is easier to read, test and explain line by line. The structure maps directly onto a LangGraph graph (nodes = plan/search/check/answer, a conditional edge on `sufficient`) if those features become necessary.
- **Free-form tool calling** (the LLM decides when to call `search` with no fixed structure). More flexible, but harder to bound and to evaluate; the fixed loop makes the cost per question predictable (2–6 LLM calls).
- **Single-shot RAG** (one search, then answer). Cheapest; it's the baseline the agent must beat in the evaluation, on both evidence recall and answer quality.

## Consequences

- Latency is 9–16 s and 8–15k input tokens per question, dominated by LLM calls over the evidence. Free-tier rate limits allow roughly one question every 15–20 s.
- The agent can only be as good as what it retrieves; "find all papers that…" questions remain hard.

## Be ready to explain

- Why a fixed loop with explicit stopping conditions beats an open-ended agent for this task (bounded cost, debuggable traces, testable steps).
- What the sufficiency check is, and its failure mode (premature "sufficient" ends search too early).
- Why citations are validated in code rather than trusted (LLMs can cite passages that don't exist or don't support the claim; the second problem is what the faithfulness judge checks).
- Interleaving vs concatenating evidence from several queries.
