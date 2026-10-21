from citewise.chunking import chunk_paper, sentences
from citewise.pdf_extract import Page, clean_pages


def words(text: str) -> int:
    return len(text.split())


def test_sentence_split_respects_abbreviations():
    page = Page(1, "Results follow Guo et al. (2017). See Fig. 2 for details, e.g. the ECE. Done.")
    got = [s.text for s in sentences([page])]
    assert got == [
        "Results follow Guo et al. (2017).",
        "See Fig. 2 for details, e.g. the ECE.",
        "Done.",
    ]


def test_chunks_respect_budget_and_overlap():
    text = " ".join(f"Sentence number {i} has five words." for i in range(40))
    chunks = chunk_paper("p", [Page(1, text)], words, max_tokens=30, overlap_tokens=12)
    assert all(c.n_tokens <= 30 for c in chunks)
    # consecutive chunks share at least one sentence
    for a, b in zip(chunks, chunks[1:]):
        assert a.text.split(". ")[-1].rstrip(".") in b.text
    # every sentence appears somewhere
    joined = " ".join(c.text for c in chunks)
    assert all(f"number {i} " in joined for i in range(40))


def test_overlong_sentence_is_hard_split():
    text = "word " * 100
    chunks = chunk_paper("p", [Page(1, text)], words, max_tokens=30, overlap_tokens=0)
    assert all(c.n_tokens <= 30 for c in chunks)
    assert sum(c.n_tokens for c in chunks) == 100


def test_number_grid_paragraphs_are_dropped():
    grid = "5.22% 4.29% 0.81% 1.11% 1.08% 0.61% 1.85% 4.99% 4.16%"
    prose = "Temperature scaling reduced ECE from 5.22% to 0.81% on CIFAR-100."
    got = [s.text for s in sentences([Page(1, f"{grid}\n\n{prose}")])]
    assert got == [prose]


def test_supplementary_header_inside_reference_list_does_not_resume():
    pages = [
        "Body text.\nReferences\nA. Author. A paper. In ICML, 2015.",
        "Supplementary Materials: Some Title\n"
        "B. Author. Another paper. Neural computation, 4(3): 448–472, 1992.\n"
        "C. Author. Third paper. In AAAI, pp. 2901, 2015.\n"
        "D. Author. Fourth paper. arXiv preprint, 2016.",
    ]
    out = "\n".join(p.text for p in clean_pages(pages))
    assert "Body text." in out
    assert "Author" not in out


def test_numbered_reference_headings_are_detected():
    from citewise.pdf_extract import _REFS_HEADING

    for heading in ["References", "R EFERENCES", "7. REFERENCES", "VII. REFERENCES", "Bibliography"]:
        assert _REFS_HEADING.match(heading), heading
    for not_heading in ["Reference", "see References 3-5", "7. Results"]:
        assert not _REFS_HEADING.match(not_heading), not_heading


def test_clean_pages_removes_furniture_and_references():
    header = "JOURNAL OF THINGS"
    pages = [
        f"{header}\nIntro text page one.\n1",
        f"{header}\nMethod text.\n2",
        f"{header}\nResults text.\nReferences\n[1] Some cited paper.\n3",
        f"{header}\n[2] Another cited paper.\nSupplementary Materials\nExtra results.\n4",
    ]
    out = "\n".join(p.text for p in clean_pages(pages))
    assert header not in out
    assert "cited paper" not in out
    assert "Extra results." in out and "Results text." in out
    assert not any(line.strip() in {"1", "2", "3", "4"} for line in out.splitlines())
