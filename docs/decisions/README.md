# Decision log

Every design decision in this project gets an entry here, written at the time the decision was made. Each entry follows the same shape:

- **Context**: the situation and constraints that forced a choice
- **Decision**: what was chosen
- **Alternatives considered**: what was rejected and why
- **Consequences**: the trade-offs accepted, and what would make us revisit
- **Evidence**: commands run or numbers measured that support the choice (where any exist)
- **Be ready to explain**: the concepts an interviewer is likely to probe

Entries are never rewritten after the fact. If a decision changes, a new entry supersedes the old one and both stay, so the history of the reasoning is preserved.

| # | Decision | Status |
|---|----------|--------|
| [0001](0001-build-environment.md) | Where the code is built, run and delivered | Accepted |
| [0002](0002-llm-provider.md) | LLM provider: Gemini free tier, pinned to `gemini-3.5-flash-lite` | Accepted |
| [0003](0003-embedding-model.md) | Embeddings: local `bge-small-en-v1.5` (quantized ONNX) via fastembed | Accepted |
| [0004](0004-database.md) | One Postgres database with pgvector for vectors and built-in full-text search for keywords | Accepted (keyword ranking settled by 0011) |
| [0005](0005-secrets.md) | API key handling | Accepted |
| [0006](0006-documentation-format.md) | Documentation lives in the repo as decision records | Accepted |
| [0007](0007-pdf-extraction.md) | PDF extraction with pdftotext; remove headers, references and number grids | Accepted |
| [0008](0008-chunking.md) | Sentence-aligned chunks of ≤350 model tokens with ~60-token overlap | Accepted |
| [0009](0009-corpus.md) | Corpus: the full 29-paper MySteth literature review | Accepted |
| [0010](0010-gold-set-design.md) | Gold test set: LLM-drafted, human-verified, anchored to evidence quotes | Accepted |
| [0011](0011-retrieval-method.md) | Retrieval: hybrid vector (bge prefix) + true BM25, fused by RRF; reranker tested and rejected | Accepted |
| [0012](0012-agent-loop.md) | Agent: hand-written plan → search → check → answer loop, with paper-scoped search and validated citations | Accepted |
| [0013](0013-deployment.md) | Deployment guardrails; single container on Hugging Face Spaces | Hosting superseded by 0015 |
| [0014](0014-generalize-to-projects.md) | Citewise: projects, uploads, any field; the MySteth corpus becomes the demo | Accepted |
| [0015](0015-hosting-render-neon.md) | Hosting: Render (app) + Neon (Postgres), DB-free keep-alive ping, free-tier quota handling | Accepted |
| [0016](0016-search-the-original-question.md) | The agent always searches the user's question as typed (half the evidence budget) | Accepted; amends 0012 |
| [0017](0017-agent-evaluation-results.md) | Agent evaluation: fix recovers evidence (+17 pts); single search matches the agent at 1/3 the cost; 83% fully faithful, 0% unsupported; LLM judge lenient (caught 1 of 10 overstatements) | Final |
| [0018](0018-claim-level-judge.md) | Claim-level judge with quote check, pre-registered and run once: worse (κ 0.41 → 0.20); misses come from the judge model, not the prompt | Negative result; old judge kept |
| [0019](0019-single-search-default.md) | Single search is the default, the agent becomes opt-in Deep search; budget counted in LLM calls; hedge-keeping answer prompt; demo completed to 29 papers, versioned reload | Accepted; amends 0012, 0015 |

Records 0001–0013 were written when the project was the PCG-only "PCG Research Agent" (package `pcg_agent`); their file paths now live under `src/citewise/`. They're left as written, because they record what was true then.
