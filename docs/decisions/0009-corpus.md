# 0009 — Corpus: Tushar's full 29-paper MySteth literature review

**Date:** 2026-10-21 · **Status:** Accepted (supersedes an earlier, unrecorded 5-paper plan)

## Context

The first plan used 5 hand-picked papers for a small demo. Two problems with that:
- **It reads as a toy.** "RAG over 5 papers" in a resume bullet signals a tutorial-sized project.
- **Retrieval is too easy.** With ~226 passages, almost anything relevant lands in the top 10, so recall@10 says little.

## Decision

Use all 29 papers from Tushar's literature-review spreadsheet for MySteth 2.0 (pediatric heart-murmur screening). All are open access. Each paper gets a citation key `firstauthorYEAR_shortname` (e.g., `guo2017_calibration`), and its title, authors, year and public URL (DOI, arXiv or publisher) live in `papers/manifest.json`. PDFs are not committed to git (see `.gitignore`).

## Why this corpus is a good test bed

- **A real user with real questions.** Tushar wrote this review himself, so the gold questions and his judgments come from genuine domain knowledge rather than invented examples.
- **Deliberate overlap.** Many papers use the same dataset (CirCor), the same methods (MC Dropout, temperature scaling, self-supervised pretraining) and the same vocabulary. Search has to tell apart, say, three papers that all mention calibration, which makes recall@10 meaningful.
- **Mixed genres.** Benchmark definitions, method papers, a 27-page survey, 4-page conference papers, a 2007 clinical paper and out-of-domain calibration papers (image classification, image segmentation). This tests whether retrieval handles long documents without them crowding out short ones.

## Status of acquisition

- **23 papers** were provided as PDFs and ingested on 2026-10-21.
- **6 papers** with non-Drive links still need downloading: Wu 2024 (MDPI), Feng / ChildVox (arXiv), Alotaibi (Taylor & Francis), Niizumi 2025 (arXiv), Rodrigues (SSRN), Sondermann (arXiv).

## Consequences

- **Long documents get more chunks.** Balanya et al. (99 chunks) and Ismail et al.'s review (83) together hold ~20% of the corpus. If they crowd out short papers in search results, that shows up in per-paper recall during error analysis.
- **The base paper (MySteth, Jain et al. 2025) is included.** Questions about it are fair game, since it's part of the review.

## Be ready to explain

- Why corpus size and overlap matter for an eval to mean anything (a test you can't fail tells you nothing).
- Why the corpus manifest is versioned but PDFs aren't (licensing and repo size; the manifest makes the corpus reproducible).
