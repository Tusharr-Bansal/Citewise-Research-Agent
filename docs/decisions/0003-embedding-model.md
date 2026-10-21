# 0003 — Embeddings: local `bge-small-en-v1.5` (quantized ONNX) via fastembed

**Date:** 2026-10-21 · **Status:** Accepted (revisit if retrieval recall is weak)

## Context

Vector search needs an embedding model that turns each chunk of text, and each question, into a vector so that similar meanings land close together. Constraints:
- Free hosting tiers often have ~512 MB of RAM, so the model and its runtime must be small.
- Re-embedding the whole corpus should be fast and must not burn API quota.
- Evals must be reproducible, so the same text should always give the same vector.

## Decision

`BAAI/bge-small-en-v1.5`, in the quantized ONNX build published as `Qdrant/bge-small-en-v1.5-onnx-Q` (67 MB), run locally through the `fastembed` library (ONNX Runtime, no PyTorch). It produces 384-dimensional vectors.

## Evidence

Smoke test on 2026-10-21 (cosine similarity of normalized vectors):

| Pair | Similarity |
|---|---|
| "phonocardiogram murmur detection" vs. "heart sound segmentation" | 0.835 |
| "phonocardiogram murmur detection" vs. "stock market prices" | 0.454 |

The model separates related from unrelated text, which is all a smoke test can show. Whether it retrieves the *right* passages is measured later by recall@10 on the gold set.

## Alternatives considered

- **`gemini-embedding-001` (API).** Probably stronger on scientific text, but every embedding call spends free-tier quota, ingestion would depend on the network, and the deployed app would need an API call per question just to embed it. Kept as a candidate to compare against if recall is weak.
- **sentence-transformers + PyTorch.** Same model quality but PyTorch adds hundreds of MB to the install and RAM footprint, which free hosts can't spare.
- **`bge-base` / larger models.** Typically better retrieval but ~3× slower and bigger. Revisit only if measurements say the small model is the bottleneck.

## Consequences

- Quantization (int8 weights) trades a small amount of accuracy for size and speed.
- bge models were trained mostly on general web text, not cardiology papers. Domain terms like "S3 gallop" may embed imperfectly. That's one reason the system also uses keyword search (see 0004): exact terms are where keyword search beats vectors.

## Be ready to explain

- What an embedding is, and why cosine similarity on normalized vectors equals the dot product.
- Why bge recommends a query instruction prefix for short queries vs. passages (asymmetric retrieval), and whether we use it (decided when retrieval is built and measured).
- What quantization is and its trade-off.
