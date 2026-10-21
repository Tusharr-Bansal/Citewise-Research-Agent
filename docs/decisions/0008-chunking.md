# 0008 — Chunking: sentence-aligned, ≤350 model tokens, ~60-token overlap

**Date:** 2026-10-21 · **Status:** Accepted (size is a candidate for a later experiment)

## Context

Search returns *chunks*, not papers. Chunk size is a trade-off:
- **Too big:** one chunk covers several topics, its embedding becomes a blurry average, and the LLM receives a lot of irrelevant text.
- **Too small:** a fact gets split from the context that explains it, and citations show fragments.

There's also a hard limit: `bge-small-en-v1.5` reads at most **512 tokens**. Anything longer is **silently truncated**, so the end of an over-long chunk would be invisible to vector search without any error.

## Decision

- **Measure size in the embedding model's own tokens** (its `tokenizer.json`), not in words. Scientific text tokenizes unevenly: "phonocardiogram" is several tokens, so word counts would misjudge the limit.
- **Max 350 tokens per chunk**, comfortably under 512.
- **Split on sentence boundaries** and pack whole sentences, so citations read as complete statements. The splitter knows common abbreviations ("et al.", "Fig.", "e.g.", "i.e.", "vs.", "Eq.") so they don't end a sentence. A "sentence" longer than the budget (usually a flattened table) is hard-split by words.
- **~60 tokens of overlap** (whole sentences) between neighbouring chunks, so a fact that spans a boundary appears whole in at least one chunk.
- **Track the page range** of every chunk for page-level citations ("Guo 2017, p.4").
- **Stable IDs** `paper_key:index` (e.g., `guo2017_calibration:012`).

## Evidence

Corpus of 23 papers (2026-10-21): see the build summary printed by `python -m pcg_agent.ingest`, which reports chunk counts and min/median/max tokens and asserts that none exceed 512. The 5-paper pilot gave 226 chunks, tokens min/median/max = 88/306/334, **0 over 512**.

Unit tests (`tests/test_chunking.py`) cover: abbreviation-aware splitting, the token budget, overlap between neighbouring chunks, no sentence lost, and hard-splitting over-long text.

## Alternatives considered

- **Fixed-size windows** (every N tokens, ignoring sentences). Simplest, but cuts sentences in half, which hurts both embeddings and readable citations.
- **Section-aware chunking** (split on headings like "Methods"). Better boundaries, but heading detection on PDF text is unreliable across 29 different layouts. Revisit if error analysis shows chunks mixing sections hurts.
- **Semantic chunking** (split where consecutive sentence embeddings diverge). Costs an embedding per sentence, and published comparisons show mixed gains over simple sentence packing.
- **Parent–child retrieval** (search small chunks, return the larger surrounding section). A known upgrade if answers lack context; not needed before measuring.

## Why gold labels aren't tied to chunks

The gold set anchors each question to an **evidence quote**, and a retrieved chunk counts as relevant if it contains that quote. If gold labels were chunk IDs, changing chunk size would invalidate the whole test set, so chunk size could never be tuned with the same eval. With quotes, chunk size becomes a fair experiment.

## Be ready to explain

- The chunk-size trade-off (precision of the embedding vs. completeness of context).
- Why token limits matter and what silent truncation does to retrieval.
- Why overlap exists, and its cost (duplicate text in the index; neighbouring chunks may both be retrieved and waste context slots).
