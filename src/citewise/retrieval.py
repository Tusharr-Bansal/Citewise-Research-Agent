"""Search over one project's chunks: vector, keyword (two rankers), and hybrid fusion.

Methods (compared on the gold set, docs/decisions/0011):
  vector       pgvector cosine distance, exact within the project
  pg_ts        Postgres full-text: OR of the query's stemmed terms, ranked by ts_rank_cd
  bm25         same stemmed terms (Postgres's own tokenizer), ranked with BM25
  hybrid_pg    reciprocal rank fusion of vector + pg_ts
  hybrid_bm25  reciprocal rank fusion of vector + bm25   (the default)

Every search is scoped to a project (docs/decisions/0014). BM25 statistics (IDF,
average length) are per project, because "rare" means rare within that collection.
"""

from __future__ import annotations

import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field

from . import db
from .embeddings import embed_query

METHODS = ("vector", "pg_ts", "bm25", "hybrid_pg", "hybrid_bm25")
_TSV_ENTRY = re.compile(r"'((?:[^']|'')+)':([0-9A-D,]+)")


@dataclass
class Hit:
    chunk_id: str
    paper_key: str          # the paper's id (citation key)
    page_start: int
    page_end: int
    text: str
    score: float
    component_ranks: dict[str, int] = field(default_factory=dict)


def _parse_tsvector(tsv: str) -> Counter:
    """"'appli':3,17 'detect':8" -> Counter({'appli': 2, 'detect': 1})"""
    return Counter({m.group(1).replace("''", "'"): len(m.group(2).split(",")) for m in _TSV_ENTRY.finditer(tsv)})


class BM25Index:
    """Okapi BM25 over pre-tokenized documents (term-frequency Counters)."""

    def __init__(self, docs: dict[str, Counter], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = docs
        self.doc_len = {d: sum(tf.values()) for d, tf in docs.items()}
        self.avg_len = sum(self.doc_len.values()) / max(1, len(docs))
        df: Counter = Counter()
        for tf in docs.values():
            df.update(tf.keys())
        n = len(docs)
        # BM25+-style non-negative IDF: rare terms weigh more, common terms ~0.
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, terms: list[str], k: int) -> list[tuple[str, float]]:
        scores: dict[str, float] = {}
        for d, tf in self.docs.items():
            s = 0.0
            for t in terms:
                f = tf.get(t, 0)
                if f:
                    norm = f + self.k1 * (1 - self.b + self.b * self.doc_len[d] / self.avg_len)
                    s += self.idf[t] * f * (self.k1 + 1) / norm
            if s > 0:
                scores[d] = s
        return sorted(scores.items(), key=lambda x: -x[1])[:k]


def rrf(rankings: dict[str, list[str]], k: int = 60) -> list[tuple[str, float, dict[str, int]]]:
    """Reciprocal rank fusion: score(d) = sum over lists of 1 / (k + rank of d)."""
    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    for name, ids in rankings.items():
        for r, cid in enumerate(ids, start=1):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + r)
            ranks.setdefault(cid, {})[name] = r
    return [(cid, s, ranks[cid]) for cid, s in sorted(scores.items(), key=lambda x: -x[1])]


@dataclass
class _ProjectIndex:
    version: str                                  # projects.updated_at when built
    chunks: dict[str, tuple]                      # id -> (id, paper_id, page_start, page_end, text)
    bm25: BM25Index


class Retriever:
    def __init__(self, use_query_prefix: bool = True, candidates: int = 50):
        self.conn = db.connect()
        self.use_query_prefix = use_query_prefix
        self.candidates = candidates  # depth of each list before fusion
        self._indexes: dict[str, _ProjectIndex] = {}
        self._lock = threading.Lock()

    # --- per-project index (rebuilt only when the project's papers change) -------
    def index(self, project: str) -> _ProjectIndex:
        row = self.conn.execute("SELECT updated_at::text FROM projects WHERE id = %s", (project,)).fetchone()
        if row is None:
            raise KeyError(f"no such project: {project}")
        with self._lock:
            cached = self._indexes.get(project)
            if cached and cached.version == row[0]:
                return cached
            rows = self.conn.execute(
                "SELECT c.id, c.paper_id, c.page_start, c.page_end, c.text, c.tsv::text "
                "FROM chunks c JOIN papers p ON p.id = c.paper_id "
                "WHERE c.project_id = %s AND p.status = 'ready'",
                (project,),
            ).fetchall()
            idx = _ProjectIndex(row[0], {r[0]: r[:5] for r in rows},
                                BM25Index({r[0]: _parse_tsvector(r[5]) for r in rows}))
            self._indexes[project] = idx
            return idx

    # --- components --------------------------------------------------------------
    def query_terms(self, query: str) -> list[str]:
        tsv = self.conn.execute("SELECT to_tsvector('english', %s)::text", (query,)).fetchone()[0]
        return list(_parse_tsvector(tsv).keys())

    def vector_ids(self, project: str, query: str, k: int, paper: str | None = None) -> list[str]:
        q = embed_query(query, use_prefix=self.use_query_prefix)
        rows = self.conn.execute(
            "SELECT id FROM chunks WHERE project_id = %s AND (%s::text IS NULL OR paper_id = %s) "
            "ORDER BY embedding <=> %s LIMIT %s",
            (project, paper, paper, q, k),
        ).fetchall()
        live = self.index(project).chunks
        return [r[0] for r in rows if r[0] in live]  # skip chunks of papers not yet 'ready'

    def pg_ts_ids(self, project: str, query: str, k: int, paper: str | None = None) -> list[str]:
        terms = self.query_terms(query)
        if not terms:
            return []
        tsq = " | ".join("'" + t.replace("'", "''") + "'" for t in terms)
        rows = self.conn.execute(
            "SELECT id FROM chunks, to_tsquery('english', %s) q WHERE tsv @@ q AND project_id = %s "
            "AND (%s::text IS NULL OR paper_id = %s) ORDER BY ts_rank_cd(tsv, q) DESC, id LIMIT %s",
            (tsq, project, paper, paper, k),
        ).fetchall()
        live = self.index(project).chunks
        return [r[0] for r in rows if r[0] in live]

    def bm25_ids(self, project: str, query: str, k: int, paper: str | None = None) -> list[str]:
        idx = self.index(project)
        if paper is None:
            return [d for d, _ in idx.bm25.search(self.query_terms(query), k)]
        # filter after scoring (IDF stays project-wide); fetch deep enough to fill k
        ranked = idx.bm25.search(self.query_terms(query), len(idx.chunks))
        return [d for d, _ in ranked if idx.chunks[d][1] == paper][:k]

    # --- public API --------------------------------------------------------------
    def search(self, project: str, query: str, k: int = 10, method: str = "hybrid_bm25",
               paper: str | None = None) -> list[Hit]:
        """Top-k chunks of `project` for `query`. `paper` restricts the search to one paper."""
        if method not in METHODS:
            raise ValueError(f"unknown method {method!r}; choose from {METHODS}")
        n, pr, p = self.candidates, project, paper
        if method == "vector":
            fused = rrf({"vector": self.vector_ids(pr, query, n, p)})
        elif method == "pg_ts":
            fused = rrf({"pg_ts": self.pg_ts_ids(pr, query, n, p)})
        elif method == "bm25":
            fused = rrf({"bm25": self.bm25_ids(pr, query, n, p)})
        elif method == "hybrid_pg":
            fused = rrf({"vector": self.vector_ids(pr, query, n, p), "pg_ts": self.pg_ts_ids(pr, query, n, p)})
        else:
            fused = rrf({"vector": self.vector_ids(pr, query, n, p), "bm25": self.bm25_ids(pr, query, n, p)})
        chunks = self.index(project).chunks
        hits = []
        for cid, score, ranks in fused[:k]:
            _, paper_id, p0, p1, text = chunks[cid]
            hits.append(Hit(cid, paper_id, p0, p1, text, score, ranks))
        return hits
