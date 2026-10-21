# 0011 — Retrieval: hybrid of vector search (with bge query prefix) and true BM25, fused by RRF

**Date:** 2026-10-22 · **Status:** Accepted (settles the open questions in 0003 and 0004)

## Context

Five retrieval methods were implemented (`src/pcg_agent/retrieval.py`) and compared on the human-verified gold set (0010): 45 single-evidence questions, of which 21 were rewritten by Tushar in natural wording and 10 are flagged ambiguous. A question is a hit at k if any chunk containing its evidence quote is in the top k.

## Results (`eval/eval_retrieval.py`, 2026-10-22)

| Config | R@1 | R@5 | **R@10** | MRR@10 | R@10 on Tushar's rewrites (n=21) | Median latency |
|---|---|---|---|---|---|---|
| vector (bge prefix) | 0.33 | 0.49 | 0.64 | 0.41 | 0.52 | 90 ms |
| vector (no prefix) | 0.27 | 0.44 | 0.56 | 0.35 | 0.48 | 84 ms |
| Postgres `ts_rank_cd` | 0.11 | 0.38 | 0.49 | 0.21 | 0.29 | 22 ms |
| BM25 (Postgres stemming) | 0.36 | 0.64 | 0.76 | 0.48 | 0.57 | 2 ms |
| hybrid: vector + ts_rank | 0.27 | 0.56 | 0.69 | 0.40 | 0.57 | 106 ms |
| **hybrid: vector + BM25** | **0.47** | 0.62 | **0.78** | **0.54** | 0.57 | 87 ms |
| hybrid: vector + BM25, no prefix | 0.42 | 0.56 | 0.73 | 0.49 | 0.48 | 74 ms |

**Paired bootstrap on per-question hits@10** (5,000 resamples):

| Comparison | Difference | P(difference ≤ 0) | Verdict |
|---|---|---|---|
| hybrid_bm25 vs vector | +0.13 | 0.002 | significant |
| BM25 vs ts_rank_cd | +0.27 | 0.001 | significant |
| vector with vs without prefix | +0.09 | 0.013 | significant |
| hybrid_bm25 vs BM25 alone | +0.02 | 0.43 | **not significant** |

95% bootstrap CI for hybrid_bm25 R@10: 0.64–0.89 overall, **0.33–0.76 on the rewritten slice**.

## Decision

Default retrieval = **hybrid_bm25**: bge vector search with the query instruction prefix, plus BM25 over Postgres's stemmed tokens, fused by reciprocal rank fusion (k = 60, 50 candidates per list).

## Why, given hybrid isn't significantly better than BM25 alone

- It has the **best point estimate** on every main metric, and it is never meaningfully worse than either component.
- The two halves fail differently. BM25 depends on shared words; vectors handle paraphrase. Real users don't copy the paper's wording (see the next section), so the vector half is insurance where it matters.
- The cost is ~85 ms per query, negligible next to an LLM call.

## Biggest finding: lexical-overlap bias, measured

| Slice | Median question/evidence word overlap | hybrid R@10 | BM25 R@10 |
|---|---|---|---|
| Drafts kept as written (n=24) | 0.32 | **0.96** | 0.92 |
| Drafts rewritten by Tushar (n=21) | 0.18 | **0.57** | 0.57 |

On LLM-drafted questions retrieval looks nearly perfect; on the same facts asked in natural wording it finds the evidence about half the time. **An eval built from unreviewed synthetic questions would have overstated recall by ~40 points.** The rewritten slice is the honest estimate of real-world performance.

## Error analysis of the 10 hybrid misses

- **7 of 10: right paper, wrong passage.** The evidence was at rank 11–38, and up to all of the top 10 came from the correct paper. That's a ranking-precision problem, the case a **cross-encoder reranker** is designed for (next experiment).
- **3 of 10: general questions answered from other papers** ("standard HMM-based segmentation", "main sub-problems of PCG analysis", "CirCor recording length"). Zero top-10 results came from the source paper, but other papers plausibly answer correctly. The strict metric undercounts here; agent-level judging will check whether those passages actually answer.
- **2 of 10 aren't in the top 50 at all** (De Simone's rejection rule, Festag's STFT settings), both rewritten questions whose wording shares little with the evidence. Candidates for the agent's query rewriting.

## Consequences

- Postgres `ts_rank_cd` is dropped as a ranker; Postgres stays the store and tokenizer. BM25 runs in Python over ~1,000 chunks in ~2 ms. At ~100k+ chunks this would move into the database (e.g. a BM25 extension) or a search engine.
- With 45 questions, differences under ~10 points can't be resolved. Any later "improvement" must clear that bar on a paired test, not just move a point estimate.

## Be ready to explain

- Recall@k vs MRR (did we find it at all, vs how high).
- Reciprocal rank fusion and why it needs no score normalisation (it uses ranks, not raw scores, which live on different scales).
- Why BM25 beat `ts_rank_cd`: IDF. Rare terms like "HnLTS" or "Morlet" should dominate the score; `ts_rank_cd` doesn't weight by rarity across the corpus.
- Bootstrap confidence intervals and paired tests on small eval sets, and why "hybrid is best" had to become "hybrid is best, but not significantly better than BM25".
- Lexical-overlap bias in synthetic eval sets, with your own numbers.

## Experiment: cross-encoder reranker (2026-10-22), rejected

The error analysis pointed at ranking precision (7 of 10 misses had the evidence at ranks 11–38), the textbook case for a cross-encoder reranker. A reranker reads the question and each candidate passage *together* and re-scores the top 50 hybrid results. Small models that would fit a free host were tested (fastembed ONNX, CPU, 2 cores):

| Reranker (on top-50 hybrid) | R@1 | R@5 | R@10 | MRR | R@10 on rewrites (n=21) | Added latency / query |
|---|---|---|---|---|---|---|
| none | 0.47 | 0.62 | 0.78 | 0.54 | 0.57 | 0 |
| ms-marco-MiniLM-L-6-v2 (80 MB) | 0.44 | 0.67 | 0.76 | 0.54 | 0.67 | +3.4 s |
| ms-marco-MiniLM-L-12-v2 (120 MB) | 0.47 | 0.69 | 0.78 | 0.56 | 0.62 | +6.6 s |

jina-reranker-v1-turbo and bge-reranker-base (1 GB) didn't finish within the time budget on this hardware, which rules them out for a free host anyway.

**Decision: no reranker.** Overall recall and MRR are unchanged. The +5 to +10 points on the rewritten slice are 1–2 questions out of 21, inside the noise established above. The cost is 3–7 s per search, multiplied by up to 6 searches per agent question. These models were trained on web search queries (MS MARCO), not scientific text. A domain-matched reranker or a GPU host would change this trade-off.

The miss it was meant to fix ("right paper, wrong passage") is now handled more cheaply by the agent's paper-scoped search (0012).
