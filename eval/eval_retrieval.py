"""Retrieval evaluation on the single-evidence gold set.

A question is a hit at k if any of its relevant chunks (chunks containing the
verified evidence quote) appears in the top k results.

Usage:  python eval/eval_retrieval.py  -> prints tables, writes eval/results/retrieval.json
"""

from __future__ import annotations

import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from citewise.ingest import DEMO_PROJECT_ID  # noqa: E402
from citewise.retrieval import Retriever  # noqa: E402

HERE = Path(__file__).parent
KS = (1, 5, 10)
CONFIGS = [
    # (label, method, bge query prefix)
    ("vector", "vector", True),
    ("vector (no prefix)", "vector", False),
    ("pg_ts", "pg_ts", True),
    ("bm25", "bm25", True),
    ("hybrid_pg", "hybrid_pg", True),
    ("hybrid_bm25", "hybrid_bm25", True),
    ("hybrid_bm25 (no prefix)", "hybrid_bm25", False),
]

_WORD = re.compile(r"[a-z0-9]+")
STOP = set(
    "a an the of in on for to and or is are was were be by with what which how does do did "
    "from that this as at it its into than when why who whom whose used use using between".split()
)


def overlap(q: str, e: str) -> float:
    qs = {w for w in _WORD.findall(q.lower()) if w not in STOP}
    return len(qs & set(_WORD.findall(e.lower()))) / max(1, len(qs))


def score(ranks: list[int | None]) -> dict:
    n = len(ranks)
    out = {f"recall@{k}": sum(r is not None and r <= k for r in ranks) / n for k in KS}
    out["mrr@10"] = sum(1 / r for r in ranks if r is not None and r <= 10) / n
    out["n"] = n
    return out


def main() -> None:
    gold = json.loads((HERE / "gold_single.json").read_text())
    for q in gold:
        q["final_overlap"] = overlap(q["question"], q["evidence_quote"])
    retrievers = {True: Retriever(use_query_prefix=True), False: Retriever(use_query_prefix=False)}
    retrievers[True].search(DEMO_PROJECT_ID, "warm up", k=1, method="vector")  # load the embedding model before timing

    slices = {
        "all": lambda q: True,
        "unambiguous": lambda q: not q["ambiguous"],
        "ambiguous": lambda q: q["ambiguous"],
        "kept as drafted": lambda q: q["verdict"] == "good",
        "rewritten by Tushar": lambda q: q["verdict"] == "fix",
    }
    results, per_question = {}, {}
    for label, method, prefix in CONFIGS:
        r = retrievers[prefix]
        ranks, latencies = [], []
        for q in gold:
            t0 = time.perf_counter()
            hits = r.search(DEMO_PROJECT_ID, q["question"], k=10, method=method)
            latencies.append((time.perf_counter() - t0) * 1000)
            rel = set(q["relevant_chunks"])
            rank = next((i for i, h in enumerate(hits, 1) if h.chunk_id in rel), None)
            ranks.append(rank)
            per_question.setdefault(q["id"], {})[label] = {
                "rank": rank,
                "top3": [h.chunk_id for h in hits[:3]],
            }
        results[label] = {
            name: score([rk for rk, q in zip(ranks, gold) if f(q)]) for name, f in slices.items()
        }
        results[label]["latency_ms_median"] = round(statistics.median(latencies), 1)

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "retrieval.json").write_text(
        json.dumps({"results": results, "per_question": per_question}, indent=2)
    )

    print(f"{len(gold)} questions | median question/evidence word overlap: "
          f"drafted-as-is {statistics.median(q['final_overlap'] for q in gold if q['verdict']=='good'):.2f}, "
          f"rewritten {statistics.median(q['final_overlap'] for q in gold if q['verdict']=='fix'):.2f}\n")
    hdr = f"{'config':26s} {'R@1':>6s} {'R@5':>6s} {'R@10':>6s} {'MRR':>6s} {'ms':>6s}"
    for sl in slices:
        n = results[CONFIGS[0][0]][sl]["n"]
        print(f"--- {sl} (n={n}) ---\n{hdr}")
        for label, _, _ in CONFIGS:
            s = results[label][sl]
            print(f"{label:26s} {s['recall@1']:6.2f} {s['recall@5']:6.2f} {s['recall@10']:6.2f} "
                  f"{s['mrr@10']:6.2f} {results[label]['latency_ms_median']:6.0f}")
        print()


if __name__ == "__main__":
    main()
