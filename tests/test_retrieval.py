from collections import Counter

from citewise.retrieval import BM25Index, _parse_tsvector, rrf


def test_parse_tsvector_counts_positions():
    tf = _parse_tsvector("'appli':3,17 'detect':8 'o''brien':2A")
    assert tf == Counter({"appli": 2, "detect": 1, "o'brien": 1})


def test_bm25_prefers_rare_term_and_handles_misses():
    docs = {
        "a": Counter({"murmur": 3, "detect": 1}),
        "b": Counter({"murmur": 1, "calibr": 1}),
        "c": Counter({"murmur": 1, "detect": 2}),
    }
    idx = BM25Index(docs)
    # 'calibr' appears in one doc only, so it outweighs the ubiquitous 'murmur'
    assert idx.search(["calibr", "murmur"], k=3)[0][0] == "b"
    assert idx.search(["nonexistent"], k=3) == []


def test_rrf_rewards_agreement_between_lists():
    fused = rrf({"vector": ["x", "y", "z"], "bm25": ["y", "w", "x"]})
    order = [cid for cid, _, _ in fused]
    assert order[0] == "y"  # rank 2 + rank 1 beats rank 1 + rank 3
    assert set(order) == {"x", "y", "z", "w"}
    ranks = {cid: r for cid, _, r in fused}
    assert ranks["y"] == {"vector": 2, "bm25": 1}
