"""Split cleaned pages into overlapping, sentence-aligned chunks.

Design notes (docs/decisions/0008):
- Sizes are measured in the embedding model's own tokens, because the model
  silently truncates input beyond 512 tokens. Word counts would be a guess.
- Chunks end on sentence boundaries where possible, so a retrieved passage
  reads as complete statements when it is shown as a citation.
- Consecutive chunks overlap by a few sentences, so a fact stated across a
  boundary appears whole in at least one chunk.
- Each chunk records the page range it came from, for page-level citations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .pdf_extract import Page

# Abbreviations that end in a period but do not end a sentence.
_ABBREV = (
    r"(?<!\bet al\.)(?<!\bFig\.)(?<!\bFigs\.)(?<!\be\.g\.)(?<!\bi\.e\.)"
    r"(?<!\bvs\.)(?<!\bEq\.)(?<!\bNo\.)(?<!\bSec\.)(?<!\bRef\.)"
)
_SENT_SPLIT = re.compile(_ABBREV + r"(?<=[.!?])\s+(?=[A-Z0-9(\[])")


@dataclass
class Sentence:
    text: str
    page: int


@dataclass
class Chunk:
    paper_key: str
    index: int
    text: str
    page_start: int
    page_end: int
    n_tokens: int

    @property
    def chunk_id(self) -> str:
        return f"{self.paper_key}:{self.index:03d}"


def _paragraphs(page: Page) -> list[str]:
    """Blank-line-separated blocks, with line breaks inside a block joined."""
    blocks = re.split(r"\n\s*\n", page.text)
    out = []
    for b in blocks:
        joined = " ".join(ln.strip() for ln in b.splitlines() if ln.strip())
        if joined:
            out.append(joined)
    return out


_NUMERIC_TOKEN = re.compile(r"[\d.,%()±/*+\-–]+")


def numeric_fraction(text: str) -> float:
    toks = text.split()
    return sum(bool(_NUMERIC_TOKEN.fullmatch(t)) for t in toks) / max(1, len(toks))


def is_number_grid(paragraph: str, max_fraction: float = 0.6, min_tokens: int = 8) -> bool:
    """A flattened table body: mostly bare numbers, headers lost in extraction."""
    return len(paragraph.split()) >= min_tokens and numeric_fraction(paragraph) > max_fraction


def sentences(pages: list[Page], drop_number_grids: bool = True) -> list[Sentence]:
    result: list[Sentence] = []
    for page in pages:
        for para in _paragraphs(page):
            if drop_number_grids and is_number_grid(para):
                continue
            for s in _SENT_SPLIT.split(para):
                s = s.strip()
                if s:
                    result.append(Sentence(s, page.number))
    return result


def _split_long(sent: Sentence, count: Callable[[str], int], max_tokens: int) -> list[Sentence]:
    """Hard-split a 'sentence' longer than max_tokens (e.g. a flattened table) by words."""
    if count(sent.text) <= max_tokens:
        return [sent]
    words, parts, cur = sent.text.split(), [], []
    for w in words:
        cur.append(w)
        if count(" ".join(cur)) > max_tokens:
            cur.pop()
            parts.append(Sentence(" ".join(cur), sent.page))
            cur = [w]
    if cur:
        parts.append(Sentence(" ".join(cur), sent.page))
    return parts


def chunk_paper(
    paper_key: str,
    pages: list[Page],
    count_tokens: Callable[[str], int],
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    sents: list[Sentence] = []
    for s in sentences(pages):
        sents.extend(_split_long(s, count_tokens, max_tokens))
    sizes = [count_tokens(s.text) for s in sents]

    chunks: list[Chunk] = []
    start = 0
    while start < len(sents):
        end, total = start, 0
        while end < len(sents) and total + sizes[end] <= max_tokens:
            total += sizes[end]
            end += 1
        end = max(end, start + 1)  # always make progress
        group = sents[start:end]
        text = " ".join(s.text for s in group)
        chunks.append(
            Chunk(
                paper_key=paper_key,
                index=len(chunks),
                text=text,
                page_start=group[0].page,
                page_end=group[-1].page,
                n_tokens=count_tokens(text),
            )
        )
        if end >= len(sents):
            break
        # Step back over whole sentences to create the overlap.
        back, overlap = end, 0
        while back > start + 1 and overlap + sizes[back - 1] <= overlap_tokens:
            back -= 1
            overlap += sizes[back]
        start = back
    return chunks
