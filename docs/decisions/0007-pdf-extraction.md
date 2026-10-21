# 0007 — PDF text extraction and cleaning

**Date:** 2026-10-21 · **Status:** Accepted

## Context

Everything downstream (search, answers, citations) depends on the extracted text. Research PDFs are hard: two-column layouts, ligature characters, running headers on every page, reference lists, and tables that lose their structure.

## Decision

1. **Extractor: `pdftotext` (poppler), default mode.**
2. **Remove page furniture:** any line that appears on at least half the pages (minimum 3) is treated as a header or footer and dropped. Bare page numbers in the first or last two lines of a page are dropped.
3. **Remove the reference list**, from the "References" heading (including small-caps forms like `R EFERENCES`) until a "Supplementary…", "Appendix…" or "S1 …" heading, but only if the lines after that heading don't themselves look like citations.
4. **Drop "number grids":** paragraphs of 8+ tokens where more than 60% of tokens are bare numbers. These are table bodies whose column headers were lost in extraction.

## Evidence

**Extractor comparison** on page 2 of Guo et al. (a two-column ICML paper):

| Extractor | Column order | Ligatures | Line-end hyphens |
|---|---|---|---|
| `pdftotext` default | correct | resolved (`classification`) | joined (`probabilities`) |
| `pypdf` | correct | **kept as `ﬁ`** (`classiﬁcation`) | **kept** (`proba-` / `bilities`) |
| `pymupdf`, `sort=True` | **interleaved: left and right columns mixed line by line** | resolved | kept |

The ligature issue matters for keyword search. The single character `ﬁ` is not the letters `f` + `i`, so a search for "classification" would not match `classiﬁcation`.

**Reference cutting** first leaked 4 chunks of citations from Guo et al. The PDF prints "Supplementary Materials: On Calibration…" as a header on the last page, *in the middle of* the reference list, which switched cutting off. Fix: only resume after such a heading when the next 8 lines contain fewer than 3 citation signals (years, `pp.`, `doi`, venue names). Both cases are unit-tested (`tests/test_chunking.py`).

**Number grids** found in the first 5-paper build, for example a chunk of Guo et al. that was 88% numbers: `5.22% 4.29% 0.81% 1.11% …`. Retrieved as evidence, such a chunk can't support any claim.

## Alternatives considered

- **Layout-aware ML parsers (Docling, Marker, GROBID).** Better at tables and section structure, but they need PyTorch or a Java service, are slow on CPU, and are heavy to deploy. Worth it for a large corpus or table-heavy questions, not for v1.
- **Keep number grids.** Rejected for v1. Some of the same numbers appear in the papers' prose ("ECE dropped from 5.22% to 0.81%"), which is kept.

## Consequences and known limitations

- **Questions answered only by a table will fail.** This is a known limitation and should show up in error analysis. If it's common, a table-aware parser is the next step.
- **Figure axis labels** ("Avg. confidence 0.8 0.6") survive when mixed with prose. Their effect is checked in error analysis, not assumed.
- **Equations** extract as flattened symbols.

## Be ready to explain

- Why text extraction quality caps retrieval quality ("garbage in, garbage out"), and how you'd detect extraction errors (inspect chunks, error analysis on failed questions).
- What a ligature is, and why a visually identical character can break exact-match search.
- Why references are removed: a query about a method would match the *titles* of cited papers rather than passages that explain the method.
