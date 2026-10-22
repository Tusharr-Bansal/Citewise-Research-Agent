# Citewise

**Ask your research papers questions and get answers that cite the exact passage.**

Create a project, upload the PDFs from your literature review (any field), and ask questions. Citewise searches the papers with hybrid retrieval (BM25 + vector search in Postgres/pgvector) and answers with numbered citations that are validated in code. By default it runs one search per question (fast, one LLM call). **Deep search** is an option: an agent plans several searches, checks whether the evidence is enough, and searches again if not (including inside one specific paper). A built-in demo project holds the 29 open-access papers from my MySteth literature review on pediatric heart-sound screening.

**Live demo:** https://citewise-3i23.onrender.com

## Results

Measured on the demo corpus, against a test set I verified by hand (45 single-passage questions and 13 multi-paper synthesis questions). Each question is anchored to an evidence *quote*, so the test set survives re-chunking.

- **No invented facts.** In a blind review of 60 answers (both search modes), none contained a claim unsupported by its sources. **83% were fully faithful**; the rest were minor overstatements (for example, the paper's "may" became "primarily"), not fabrication.
- **Every citation is checked in code:** 0 invalid citations across all 174 evaluated answers.
- **It says "not found" instead of guessing** when the papers don't contain the answer.
- **91% of answers correct** with the default single search (AI-graded, against verified reference evidence).
- **Hybrid retrieval beats vector search by 14 points** (recall@10 0.78 vs 0.64):

| Retrieval (45 questions, 29 papers) | Recall@10 | MRR |
|---|---|---|
| **Hybrid: BM25 + vector, fused by RRF (default)** | **0.78** | **0.53** |
| BM25 only | 0.73 | |
| Vector only (bge-small, with query prefix) | 0.64 | |
| Postgres `ts_rank_cd` | 0.49 | |

### What the evaluation caught

- **A regression, found and fixed.** Generalizing the prompts made the agent rewrite questions worse than the user's own wording. The search logs showed why; the fix (always search the question as typed) recovered **+17 points** of evidence recall ([decision 0016](docs/decisions/0016-search-the-original-question.md)).
- **A single search is enough, so it became the default.** One hybrid search (one LLM call, ~4 s) was as accurate as the multi-step agent (3 calls, ~8 s): 0.87 correct for both. Single search is now the default and the agent is an opt-in **Deep search**, so the free tier serves about three times as many questions ([decisions 0017](docs/decisions/0017-agent-evaluation-results.md) and [0019](docs/decisions/0019-single-search-default.md)).
- **Automatic grading overstated quality,** so the reviewed figure is the one reported (98% vs 83%; [decisions 0017](docs/decisions/0017-agent-evaluation-results.md) and [0018](docs/decisions/0018-claim-level-judge.md)).
- **LLM-written test questions flatter retrieval.** On the LLM's own drafted wording, recall@10 was 0.96; on my natural rewrites of the same questions, it was 0.57. That's why the test set is hand-verified.
- A cross-encoder reranker was tested and rejected: no gain within noise, +3–7 s per question.

<sub>Evaluation details: faithfulness labels were drafted with model assistance and reviewed card by card against the cited passages; the judge never saw the labels and the reviewer never saw the judge. The reviewed answers predate the hedge-keeping answer prompt ([decision 0019](docs/decisions/0019-single-search-default.md)). Scripts and raw results are in `eval/`.</sub>

## How it works

```
upload PDF ─► pdftotext ─► clean (headers, reference lists, number grids) ─► sentence chunks ≤350 tokens
          ─► bge-small-en-v1.5 embeddings (local ONNX) ─► Postgres: vector(384) + tsvector, per project

default:  question ─► hybrid search (BM25 + vector, RRF) ─► ANSWER with [S#] citations ─► validated

deep:     question ─► PLAN search queries ─► hybrid search ─► CHECK: enough evidence?
                                                ▲                      │ no: new queries,
                                                └──────────────────────┘ or search one paper
                                                                       │ yes
                                                          ANSWER with [S#] citations ─► validated
```

Every design choice, with the alternatives rejected and the evidence measured, is in **[`docs/decisions/`](docs/decisions/README.md)**. To learn the project end to end, follow **[`docs/STUDY_GUIDE.md`](docs/STUDY_GUIDE.md)**.

## Repository layout

```
src/citewise/      the application
  pdf_extract.py     PDF → clean page text
  chunking.py        sentence-aligned, token-counted chunks
  embeddings.py      local bge-small embeddings, cached
  retrieval.py       vector, BM25 and hybrid search, scoped to a project
  agent.py           single search (default) and the plan → search → check → answer agent (deep)
  llm.py             Gemini client: retries, daily-quota detection, response cache
  ingest.py          upload pipeline and LLM-extracted metadata; builds the demo project
  app.py             FastAPI: projects, uploads, questions, rate limits
  static/index.html  the single-page web app
eval/              gold-set construction, retrieval and agent evaluations, results
tests/             unit tests (pytest)
deploy/            demo project data (loaded on start when missing or out of date)
docs/              decision records and study guide
Dockerfile, render.yaml   deployment (Render + Neon)
```

## Run it locally

Needs Python 3.12+, Postgres 16 with the pgvector extension, and `pdftotext` (poppler-utils).

```bash
pip install -r requirements.txt
cp .env.example .env            # add your GEMINI_API_KEY (never commit .env)
# set DATABASE_URL in .env if not postgresql://pcg:pcg@localhost:5432/citewise
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
python -c "from huggingface_hub import snapshot_download; snapshot_download('Qdrant/bge-small-en-v1.5-onnx-Q', local_dir='models/bge-small-en-v1.5-onnx-Q', allow_patterns=['*.json','*.onnx','vocab.txt'])"
PYTHONPATH=src uvicorn citewise.app:app --port 7860     # open http://localhost:7860
PYTHONPATH=src python -m pytest -q tests
```

On start, the app creates its tables and loads the demo project if it is missing or older than `deploy/demo_data.sql.gz` (versioned by the file's hash; user projects are never touched).

## Deploy

Render (free web service, Docker) plus Neon (free Postgres with pgvector). An external cron calls `/api/ping` every 10 minutes to keep Render awake; that endpoint never touches the database, so Neon can still sleep. See [decision 0015](docs/decisions/0015-hosting-render-neon.md).

## Limits

- No accounts: a project's link is its key (unguessable, ~96 random bits). Don't upload confidential papers.
- Scanned PDFs without a text layer are rejected; tables and figures are only partly captured.
- The free LLM tier allows a limited number of questions per day; the app says so when it runs out.
