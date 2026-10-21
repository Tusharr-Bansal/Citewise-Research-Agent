# Citewise

**Ask your research papers questions and get answers that cite the exact passage.**

Create a project, upload the PDFs from your literature review (any field), and ask questions. An agent searches the papers with hybrid retrieval (BM25 + vector search in Postgres/pgvector), checks whether the evidence is enough, searches again if not (including inside one specific paper), and answers with numbered citations that are validated in code. A built-in demo project holds the 26 open-access papers from my MySteth literature review on pediatric heart-sound screening.

**Live demo:** _link added after deployment_

## What's measured (not just built)

Evaluated on a test set I verified by hand: 45 single-passage questions plus 13 multi-paper synthesis questions over the demo corpus. Each question is anchored to an evidence *quote*, not a chunk id, so it survives re-chunking.

| Retrieval (45 questions) | Recall@10 | MRR |
|---|---|---|
| **Hybrid: BM25 + vector, fused by RRF (default)** | **0.78** | **0.54** |
| BM25 only | 0.76 | |
| Vector only (bge-small, with query prefix) | 0.64 | |
| Postgres `ts_rank_cd` | 0.49 | |

- **Synthetic test sets overstate quality.** On the LLM's own drafted wording, recall@10 was 0.96; on my natural rewrites of the same questions it was 0.57.
- A cross-encoder reranker was tested and rejected: no gain within noise, +3–7 s per question.
- **Agent vs single search, faithfulness (LLM judge) and judge–human agreement (Cohen's κ):** _being re-run on the generalized prompts; see `eval/results/`._

## How it works

```
upload PDF ─► pdftotext ─► clean (headers, reference lists, number grids) ─► sentence chunks ≤350 tokens
          ─► bge-small-en-v1.5 embeddings (local ONNX) ─► Postgres: vector(384) + tsvector, per project

question ─► PLAN search queries ─► hybrid search (BM25 + vector, RRF) ─► CHECK: enough evidence?
                                         ▲                                   │ no: new queries,
                                         └───────────────────────────────────┘ or search one paper
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
  agent.py           plan → search → check → answer loop
  llm.py             Gemini client: retries, daily-quota detection, response cache
  ingest.py          upload pipeline and LLM-extracted metadata; builds the demo project
  app.py             FastAPI: projects, uploads, questions, rate limits
  static/index.html  the single-page web app
eval/              gold-set construction, retrieval and agent evaluations, results
tests/             unit tests (pytest)
deploy/            demo project data (loaded into an empty database on first start)
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

On first start against an empty database, the app creates its tables and loads the demo project.

## Deploy

Render (free web service, Docker) plus Neon (free Postgres with pgvector). An external cron calls `/api/ping` every 10 minutes to keep Render awake; that endpoint never touches the database, so Neon can still sleep. See [decision 0015](docs/decisions/0015-hosting-render-neon.md).

## Limits

- No accounts: a project's link is its key (unguessable, ~96 random bits). Don't upload confidential papers.
- Scanned PDFs without a text layer are rejected; tables and figures are only partly captured.
- The free LLM tier allows a limited number of questions per day; the app says so when it runs out.
