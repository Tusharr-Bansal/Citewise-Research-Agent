"""Turn a research-paper PDF into clean per-page text.

Design notes (docs/decisions/0007):
- pdftotext (poppler) is used because it keeps two-column reading order and
  resolves ligatures (e.g. "ﬁ" -> "fi"), which keyword search depends on.
- Running headers/footers are removed: any line that appears on at least half
  of the pages is page furniture, not content.
- The reference list is removed (it would match queries on cited titles), but
  supplementary material that follows it is kept.
"""

from __future__ import annotations

import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# "References" heading, including small-caps renderings such as "R EFERENCES"
# and numbered forms such as "7. REFERENCES" or "VII. REFERENCES".
_REFS_HEADING = re.compile(
    r"^\s*(?:(?:\d{1,2}|[IVX]{1,5})\.?\s+)?"
    r"(R\s?E\s?F\s?E\s?R\s?E\s?N\s?C\s?E\s?S|References|Bibliography|Literature Cited)\s*$",
    re.IGNORECASE,
)
# Headings that mark the end of a reference list (content resumes after them).
_AFTER_REFS_HEADING = re.compile(
    r"^\s*(Supplementary (Materials?|Information)\b.*|S1 (Appendix|Text|Fig|Table)\b.*"
    r"|Appendix\b.*|Supporting information\s*)$",
    re.IGNORECASE,
)
_PAGE_NUMBER = re.compile(r"^\s*\d{1,3}(\s*/\s*\d{1,3})?\s*$")
# Signals that a line belongs to a citation entry.
_CITATION_SIGNAL = re.compile(
    r"\b(19|20)\d\d[a-z]?\b[.,;):]|doi[:.]|arXiv|\bpp\.\s*\d|\bIn (Proc|ICML|NIPS|NeurIPS|CVPR|AAAI|KDD|BMVC)"
    r"|Proceedings|Journal|Conference|vol\.\s*\d|\d+\(\d+\):"
)


def _looks_like_citations(lines: list[str], window: int = 8, min_hits: int = 3) -> bool:
    """True if the next few non-empty lines read like a reference list."""
    nxt = [ln for ln in lines if ln.strip()][:window]
    return sum(bool(_CITATION_SIGNAL.search(ln)) for ln in nxt) >= min_hits


@dataclass
class Page:
    number: int  # 1-based, as printed by the PDF viewer
    text: str


def pdf_to_pages(pdf_path: Path) -> list[str]:
    """Raw text of each page, in reading order."""
    out = subprocess.run(
        ["pdftotext", "-enc", "UTF-8", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pages = out.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


def _furniture_lines(pages: list[str], min_fraction: float = 0.5) -> set[str]:
    """Lines repeated on at least `min_fraction` of pages (headers, footers)."""
    if len(pages) < 3:
        return set()
    counts: Counter[str] = Counter()
    for page in pages:
        counts.update({ln.strip() for ln in page.splitlines() if len(ln.strip()) >= 4})
    threshold = max(3, int(len(pages) * min_fraction))
    return {ln for ln, n in counts.items() if n >= threshold}


def _strip_page_numbers(lines: list[str]) -> list[str]:
    """Drop a bare page number among the first/last two non-empty lines."""
    idx = [i for i, ln in enumerate(lines) if ln.strip()]
    edge = set(idx[:2] + idx[-2:])
    return [ln for i, ln in enumerate(lines) if not (i in edge and _PAGE_NUMBER.match(ln))]


def clean_pages(pages: list[str]) -> list[Page]:
    furniture = _furniture_lines(pages)
    cleaned: list[Page] = []
    in_refs = False
    for i, raw in enumerate(pages, start=1):
        lines = _strip_page_numbers(raw.splitlines())
        kept: list[str] = []
        for j, ln in enumerate(lines):
            s = ln.strip()
            if s in furniture:
                continue
            if _REFS_HEADING.match(s):
                in_refs = True
                continue
            # Resume only if what follows the heading is not more citations:
            # some PDFs print a "Supplementary ..." running header on pages that
            # still hold the reference list.
            if in_refs and _AFTER_REFS_HEADING.match(s) and not _looks_like_citations(lines[j + 1 :]):
                in_refs = False
            if not in_refs:
                kept.append(ln)
        cleaned.append(Page(number=i, text="\n".join(kept)))
    return cleaned


def extract(pdf_path: Path) -> list[Page]:
    return clean_pages(pdf_to_pages(pdf_path))
