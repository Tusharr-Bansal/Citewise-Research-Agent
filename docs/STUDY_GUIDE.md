# Study guide

How to learn this project well enough to defend every part of it in an interview. Plan on 4–6 focused hours, spread over a few days. Each step lists what to read and what you should be able to explain afterwards.

## 0. The one-minute pitch (memorise this)

> I built and deployed Citewise, a research assistant where you create a project, upload the papers from your literature review, and ask questions. Every claim in the answer cites the exact passage it came from, and the citations are checked in code. Retrieval is hybrid (BM25 plus vector search in Postgres with pgvector), which beat vector-only search by 14 points. I evaluated it on my own literature review on pediatric heart-sound screening, with a test set I verified myself. In a blind review of 60 answers, none contained invented facts and 83% were fully faithful. The evaluation also earned its keep: it caught a regression, which I traced and fixed (+17 points), and it showed that a single search matched a multi-step agent at a third of the cost, so single search became the default. And it showed that test questions written by an LLM make retrieval look 40 points better than natural questions do.

## 1. The big picture (30 min)

```
PDFs ──► pdf_extract.py ──► chunking.py ──► embeddings.py ──► Postgres (pgvector + text index)
                                                                      │
default ("fast"): question ──► retrieval.py ──► ANSWER  (agent.single_shot, 1 LLM call)   │
                                                                                     │
deep: question ──► agent.py: PLAN ──► retrieval.py (BM25 + vector, RRF) ◄────────────┘
                        │              ▲
                        ▼              │ new queries / search inside one paper
                      CHECK ───────────┘
                        │ sufficient
                        ▼
                      ANSWER (cites [S#]) ──► citations validated in code ──► app.py ──► web page
```

Read: `README.md`, then `docs/decisions/README.md` (the index of decisions).

You should be able to explain: what RAG is, why it's used instead of fine-tuning (knowledge changes; citations; no training cost), and what each box above does.

## 2. Ingestion: from PDF to searchable chunks (60 min)

| Read | Then explain |
|---|---|
| `src/citewise/pdf_extract.py` + decision 0007 | Why pdftotext; ligatures (`ﬁ`) breaking keyword search; how headers and reference lists are removed; the Guo "Supplementary" bug and its fix |
| `src/citewise/chunking.py` + decision 0008 | Why sizes are counted in model tokens (silent truncation at 512); sentence packing; overlap; why gold labels use quotes instead of chunk IDs |
| `src/citewise/embeddings.py` + decision 0003 | What an embedding is; cosine similarity; the bge query prefix (and its measured +9 points); the embedding cache |
| `src/citewise/schema.sql`, `ingest.py` + decision 0004 | The `chunks` table; `vector(384)`; the generated `tsvector` column; HNSW vs IVFFlat |

Exercise: run `python -m citewise.ingest demo` and read its output line by line; then upload a paper in the local app and watch it go queued → processing → ready.

## 3. Retrieval: finding the right passage (60 min)

Read `src/citewise/retrieval.py` and decision 0011, which is the most important one.

You should be able to explain:
- **BM25:** term frequency, inverse document frequency, length normalisation, and why it beat Postgres's `ts_rank_cd` by 27 points (IDF).
- **Reciprocal rank fusion:** `score = Σ 1/(60 + rank)`, and why ranks rather than raw scores (the two lists' scores aren't comparable).
- **Recall@k and MRR**, and the actual numbers.
- **Why hybrid** is the default even though it isn't *significantly* better than BM25 alone (insurance against paraphrase; the bootstrap test).
- **The reranker experiment** and why it was rejected (no gain within noise, +3–7 s).

## 4. The agent (45 min)

Read `src/citewise/agent.py` top to bottom (it's short) and decisions 0012 and 0019.

You should be able to explain:
- **Why single search is the default and the agent is opt-in ("Deep search"; 0019):** equal correctness on this corpus at a third of the LLM calls, so the free daily quota serves about three times as many questions; the budget counts LLM calls (fast = 1, deep = 3), not questions.
- The four steps and the stopping conditions (max rounds, max LLM calls).
- Why a hand-written loop instead of LangGraph, and how it would map to a LangGraph graph.
- **Paper-scoped search**, with the STFT example ("short-time Fourier transform" vs "STFT").
- Interleaving evidence across queries.
- Why citations are checked in code, and what that check *can't* catch (a real citation that doesn't support the claim; that's what the faithfulness judge measures).
- A failure it still has: "which papers do X?" questions (the Bondareva example).

## 5. Evaluation (60 min)

Read decisions 0010, 0016, 0017, 0018 and 0019; `eval/build_gold.py`, `eval/eval_retrieval.py`, `eval/eval_agent.py`, `eval/compare_runs.py`, `eval/judge_agreement.py`; and the results in `eval/results/`.

You should be able to explain:
- How the gold set was built, and *your own* labelling decisions (the patterns: vague subject, copying, reverse lookups, citation summaries, wrong table answers, inflated totals, duplicates).
- **Lexical-overlap bias**, with your numbers (96% vs 57%).
- Ambiguous questions and why they're scored separately.
- **The regression (0016):** how a prompt change silently lowered evidence recall, how the per-question comparison and the search traces found the cause, and why the fix is a guarantee in code rather than a prompt tweak.
- **Agent vs single search (0017):** same correctness at 3× the calls, the paired bootstrap, and why 45 questions can't resolve a 7-point difference.
- **Faithfulness review:** the rubric (unbacked claim = Partly; marked interpretation fine; naming the paper fine; contradicted grouped citation = Partly), the 0 unsupported / 83% fully faithful result, and the overstatement patterns you found.
- **LLM-as-judge:** a different model as judge (self-preference bias); judged against the reviewed labels it passed every good answer but caught 1 of 10 overstatements (recall 0.10, specificity 1.00, accuracy 0.82 vs a 0.77 always-"supported" baseline); why κ is a secondary figure here.
- **The hedge-keeping prompt and the 29-paper rerun (0019):** why it was checked only on the answers that motivated it (a development-set check, not a new faithfulness number); the swapped-number error it introduced on one answer; and the one question that lost its evidence to top-k competition from the new papers.
- **The claim-level judge (0018):** pre-registration, running once, and why it failed (it quoted the right evidence but missed the overstatement).

## 6. Production concerns (30 min)

Read `src/citewise/llm.py`, `src/citewise/app.py`, `Dockerfile`, `render.yaml`, and decisions 0013, 0014 and 0015 (with their addenda: quota, `pdftotext`, memory, progress bar, 7-day expiry).

You should be able to explain:
- Retries with exponential backoff and jitter; why 503/429 are retried and 400 isn't.
- The response cache and why it matters for reproducible evals.
- Model pinning (the `-latest` alias, and `gemini-3.5-flash` silently serving 3.6).
- Every guardrail in 0013, especially why "no write tools" limits prompt injection.
- Multi-tenancy (0014): every query scoped to a project, per-project BM25 statistics, why vector search is exact rather than HNSW-then-filter, capability URLs.
- Hosting (0015): Render + Neon, why the keep-alive ping must not touch the database, pooled vs direct connection strings, first-start demo loading.
- Rate limit vs daily quota: why a per-day 429 isn't retried, and capacity planning (500 calls/day ÷ ~3 per question → a 120-question cap).
- Bugs found by testing: the container socket directory and WORKDIR ownership (0013), the shared DB connection across threads (0014), and `pdftotext` missing from the deploy image (0015).
- Cost: tokens per question, and how you'd cut them (smaller evidence budget, caching, routing easy questions to single-shot).

## Likely interview questions → where the answer is

| Question | Where |
|---|---|
| "Walk me through what happens when I ask a question." | §1 diagram, `agent.py`, `app.py` |
| "How do you know it works?" | 0010, 0011, results; say "measured on a set I verified" |
| "Why hybrid search?" | 0011 |
| "What was the hardest bug?" | Reference lists leaking (0007), or the overlap bias (0011), or the socket dir (0013) |
| "How does it handle many users / projects?" | 0014 (project scoping, link-as-key, limits) and 0015 (quota, single worker) |
| "How do you prevent hallucination?" | Answer-only-from-evidence prompt, `answerable` field, citation validation, faithfulness judge |
| "Why not LangChain / LangGraph?" | 0012 |
| "How would you scale it to 100k papers?" | BM25 in-database or a search engine; HNSW tuning; async ingestion; a reranker on GPU (0011, 0013) |
| "What would you do next?" | Table-aware PDF parsing (0007); better "find all papers" recall; a domain reranker; more human-labeled questions |
| "Did you write all this yourself?" | Be honest: built with an AI coding agent; *you* defined the scope, chose the corpus, verified and wrote the test set, labeled faithfulness, and can explain every decision in this log |
