# 0014 — From a PCG-specific tool to Citewise: projects, uploads, any field

**Date:** 2026-10-22 · **Status:** Accepted (product direction set by Tushar)

## Context

Everything up to 0013 was built for one fixed corpus: Tushar's 29-paper MySteth literature review. Tushar redirected the product: any researcher should be able to **create a project, upload their own literature, and ask questions**, in any field. The retrieval, agent and evaluation stay; what changes is everything around them. The product is renamed **Citewise** (Tushar's choice), and the Python package `pcg_agent` becomes `citewise`. Decision records 0001–0013 refer to old paths; they're kept unchanged as history.

## Decisions

### Data model
`projects` (id, name, description, is_demo) → `papers` (status: queued / processing / ready / failed, plus an error message) → `chunks` (now carry `project_id` and `paper_id`). Deleting a project cascades to its papers and chunks. `projects.updated_at` is bumped whenever papers change, which invalidates search caches. The schema script is idempotent and **never drops data** (the old one rebuilt tables on every ingest, fine for one corpus, destructive with user data).

### The demo project
The MySteth corpus becomes the built-in, read-only project `demo-mysteth`. Its paper ids and chunk ids are **unchanged** (`guo2017_calibration:012`…), so the gold test set still refers to valid chunks.

**Evidence:** rebuilt from the embedding cache in 9 s, 985 chunks; an MD5 over all chunk ids and texts is identical to the pre-generalization database (`c9c60cda…`). The retrieval evaluation reproduces every previous number in the default configuration.

### Search scoped to a project
- **BM25 statistics are per project.** "Rare" must mean rare *within this collection*; a term common in one field may be rare in another.
- Indexes are built lazily per project and cached, keyed by `updated_at`.
- **Vector search is exact within a project (no HNSW index).** An approximate index searched across all projects and *then* filtered by project can return too few results, or the wrong ones. At a few thousand chunks per project, exact search takes milliseconds. Measured side effect: switching from HNSW to exact changed **1 of 315** rankings in the retrieval evaluation, and none in the default configuration. That's a direct measurement of what the approximation was costing.

### Uploads
- One background worker processes PDFs one at a time (embedding is CPU-bound, so parallel jobs would just contend).
- Each PDF: magic-byte check (`%PDF`), 25 MB cap, 40 papers per project; text extraction and the cleaning rules from 0007; **scanned PDFs are detected** (under 1,500 characters of text) and rejected with an explanation; then chunking and embedding.
- **Metadata** (title, first author "et al.", year) comes from one LLM call on the first page, with the filename as fallback. **Links** come from an arXiv id or DOI found in the first two pages.
- The uploaded PDF is deleted after processing; only the text chunks are kept.
- On restart, uploads that were mid-flight are marked failed with "please upload again" instead of hanging forever.

**Evidence (end-to-end test):** new project; uploaded Guo 2017, Balanya 2024 and a fake `.pdf`. The fake was rejected ("Not a PDF file."). Metadata was extracted correctly ("Guo et al. 2017", "Balanya et al. 2024" plus its DOI). A question was answered citing only that project's papers. After removing Balanya, the same question got an honest "not found", proving the cache invalidation works.

### Prompts
The system prompt no longer mentions phonocardiograms. It names the project and includes the user's own description ("Project focus: …"), so field-specific vocabulary still helps. The agent passes project context explicitly through each call, rather than storing it on the instance (which would mix projects if two questions ever ran concurrently).

### Access: the link is the key (Tushar's choice)
No accounts. A project id is `secrets.token_urlsafe(12)` (~96 random bits), so it can't be guessed or enumerated, and possessing the link grants access, like an "anyone with the link" document. The browser remembers your projects in local storage. The UI warns not to upload confidential material.

### Abuse limits
Per visitor per day: 10 projects, 120 uploads, 30 questions (5/minute). Global: 300 questions/day (free-tier LLM quota) and 300 projects (database size).

## Consequences

- **Per-request database connections:** a shared connection across request threads would let one request's statements run inside another's transaction.
- **The evaluation must be re-run** with the generalized prompts, because the shipped system must be the measured system (results in 0017).

## Be ready to explain

- Multi-tenancy at its simplest: every query filtered by project; per-tenant statistics (BM25 IDF).
- Filtered approximate-nearest-neighbour search, and why it's a trap (pgvector 0.8 added iterative index scans to mitigate it).
- Capability URLs: security by unguessable link, and its limits (links leak through sharing, browser history, screenshots).
- Why the demo kept its ids (test-set validity), and how you proved nothing changed (content hash, identical retrieval results).
