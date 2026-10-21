# 0004 — One Postgres database for vectors (pgvector) and keyword search

**Date:** 2026-10-21 · **Status:** Accepted; keyword-ranking method still open

## Context

Hybrid search needs two indexes over the same chunks: a **vector index** (meaning-based search) and a **keyword index** (exact-term search). They can live in one database or two.

## Decision

A single **Postgres 16** database:
- **pgvector** extension for the embeddings column and its index.
- Postgres **built-in full-text search** (`tsvector` + GIN index) for keyword search.

Both searches run against the same `chunks` table, so the two result lists always refer to the same chunk IDs and can be merged in one query.

## Alternatives considered

- **Dedicated vector DB (Qdrant, Chroma, Weaviate) + a separate keyword engine.** Two systems to deploy, keep in sync, and pay for. Overkill for a corpus of ~100 papers.
- **FAISS in memory.** Fast, but no keyword search, no persistence story, and nothing to show about databases.
- **Postgres is also already on the resume** (PostgreSQL, RDBMS, DBMS TA), and free hosted Postgres with pgvector is common, which simplifies deployment.

## Open question (decided later, with measurements)

Postgres's built-in `ts_rank` is **not BM25**. It doesn't use inverse document frequency (how rare a term is across the corpus) the way BM25 does, so rare-but-important terms like "S3 gallop" aren't boosted as much. Options to compare once the gold set exists:
1. `ts_rank_cd` as-is (simplest)
2. True BM25 computed in Python (e.g., `rank_bm25`) over the same chunks
3. A Postgres BM25 extension (e.g., ParadeDB `pg_search`), which depends on whether the deployment host allows it

The choice will be made by recall@10, not by preference, and recorded in a new entry.

## Consequences

- Vector index type (HNSW vs. IVFFlat) barely matters at this corpus size (a few thousand chunks), where exact search is fast. The choice will still be made and explained.

## Be ready to explain

- What BM25 is (term frequency, inverse document frequency, length normalization) and why `ts_rank` differs.
- HNSW vs. IVFFlat: graph-based vs. cluster-based approximate search; build time, memory, recall trade-offs.
- Why hybrid search beats either method alone: vectors catch paraphrases, keywords catch exact rare terms.
