from citewise.agent import anchored, extract_citations, interleave
from citewise.retrieval import Hit


def test_extract_citations_handles_grouped_and_repeated():
    text = "A [S3, S5]. B [S5][S9]. C [S2; S3]. Not a cite [5] or [see S4]."
    assert extract_citations(text) == ["S3", "S5", "S9", "S2"]


def test_interleave_round_robins_and_dedupes():
    h = lambda i: Hit(i, "p", 1, 1, "t", 0.0)
    lists = [[h("a"), h("b"), h("c")], [h("x"), h("a"), h("y")]]
    assert [x.chunk_id for x in interleave(lists, 10)] == ["a", "x", "b", "c", "y"]
    assert [x.chunk_id for x in interleave(lists, 3)] == ["a", "x", "b"]


def test_anchored_keeps_the_original_query_results_first_and_whole():
    h = lambda i: Hit(i, "p", 1, 1, "t", 0.0)
    anchor = [h("q1"), h("q2"), h("q3")]
    lists = [[h("a"), h("q2"), h("b")], [h("x"), h("y")]]
    # anchor in full, then the agent's queries round-robin, skipping duplicates of the anchor
    assert [x.chunk_id for x in anchored(anchor, lists, 10)] == ["q1", "q2", "q3", "a", "x", "y", "b"]
    assert [x.chunk_id for x in anchored(anchor, lists, 5)] == ["q1", "q2", "q3", "a", "x"]
    assert [x.chunk_id for x in anchored(anchor, [], 2)] == ["q1", "q2"]
