from citewise.agent import extract_citations, interleave
from citewise.retrieval import Hit


def test_extract_citations_handles_grouped_and_repeated():
    text = "A [S3, S5]. B [S5][S9]. C [S2; S3]. Not a cite [5] or [see S4]."
    assert extract_citations(text) == ["S3", "S5", "S9", "S2"]


def test_interleave_round_robins_and_dedupes():
    h = lambda i: Hit(i, "p", 1, 1, "t", 0.0)
    lists = [[h("a"), h("b"), h("c")], [h("x"), h("a"), h("y")]]
    assert [x.chunk_id for x in interleave(lists, 10)] == ["a", "x", "b", "c", "y"]
    assert [x.chunk_id for x in interleave(lists, 3)] == ["a", "x", "b"]
