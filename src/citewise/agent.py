"""The research agent: plan searches, gather evidence, check sufficiency, answer with citations.

Loop (docs/decisions/0012):
  1. PLAN     LLM turns the question into 1-3 search queries.
  2. SEARCH   hybrid retrieval for each query; evidence is pooled and deduplicated.
  3. CHECK    LLM judges whether the evidence answers the question. If not, it
              proposes new queries and we search again (at most MAX_ROUNDS rounds).
  4. ANSWER   LLM answers ONLY from the evidence, citing passages as [S1], [S2]...
              Code then verifies every citation refers to a passage it was shown.

Guards: a hard cap on search rounds and LLM calls; every step recorded in a trace.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from .llm import LLM
from .retrieval import Hit, Retriever

MAX_ROUNDS = 3            # search rounds, including the first
MAX_LLM_CALLS = 6         # plan + up to 3 checks + answer, with headroom
HITS_PER_QUERY = 6        # passages kept per query
MAX_EVIDENCE = 14         # passages shown to the answer step

SYSTEM_TEMPLATE = (
    "You are a research assistant for the project \"{name}\": a collection of research papers "
    "uploaded by the user.{about} You only use evidence you are given from these papers. "
    "You never use outside knowledge to fill gaps."
)


def system_prompt(name: str, description: str) -> str:
    about = f" Project focus: {description.strip()}" if description.strip() else ""
    return SYSTEM_TEMPLATE.format(name=name, about=about)

PLAN_PROMPT = """Question: {question}

Write the search queries needed to find evidence for this question in the project's papers.
- One query if the question is about a single fact or method.
- Two or three queries if it compares papers or has several parts; give each part its own query.
- Write queries the way the relevant passage would phrase things: include specific terms, method names and synonyms.
- Spell out abbreviations and keep both forms (e.g. "STFT short-time Fourier transform"), because a paper may use only one.
"""
PLAN_SCHEMA = {
    "type": "object",
    "properties": {"queries": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3}},
    "required": ["queries"],
}

CHECK_PROMPT = """Question: {question}

Evidence gathered so far:
{evidence}

Does this evidence contain what is needed to answer the question well?
- sufficient: true only if the key facts are actually stated in the evidence.
- If not sufficient, write 1-2 NEW search queries for what is missing. Use different wording from these earlier queries: {past_queries}
  Spell out abbreviations and keep both forms.
- If the evidence shows WHICH paper should contain the missing detail but not the detail itself, set "paper" on that query to the paper's key (shown as key=... in the evidence) to search only inside that paper. Otherwise leave "paper" empty.
"""
CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "sufficient": {"type": "boolean"},
        "missing": {"type": "string"},
        "new_queries": {
            "type": "array",
            "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "paper": {"type": "string"}},
                "required": ["query", "paper"],
            },
        },
    },
    "required": ["sufficient", "missing", "new_queries"],
}

ANSWER_PROMPT = """Question: {question}

Evidence passages:
{evidence}

Answer the question using ONLY these passages.
- Put a citation like [S3] after every sentence that states a fact, pointing to the passage(s) that support it.
- If passages disagree, say so and cite both.
- If the evidence does not answer the question, or only partly, say exactly what is missing. Do not guess.
- Be concise: a few sentences, or a short list for multi-part questions.
"""
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "answerable": {"type": "string", "enum": ["yes", "partly", "no"]},
    },
    "required": ["answer", "answerable"],
}

_CITE_GROUP = re.compile(r"\[(S\d+(?:\s*[,;]\s*S\d+)*)\]")  # [S3] or [S3, S5] or [S3; S5]


def extract_citations(text: str) -> list[str]:
    """Citation labels in order of first use: "[S3, S5] ... [S3][S9]" -> ["S3", "S5", "S9"]."""
    seen: list[str] = []
    for group in _CITE_GROUP.findall(text):
        for label in re.split(r"\s*[,;]\s*", group):
            if label not in seen:
                seen.append(label)
    return seen


def interleave(ranked_lists: list[list[Hit]], limit: int) -> list[Hit]:
    """Round-robin by rank across queries (1st of each, then 2nd of each...), deduplicated.

    Keeps every query represented when the evidence budget is tight, instead of
    letting the first query's results fill it.
    """
    out, seen = [], set()
    for rank in range(max((len(lst) for lst in ranked_lists), default=0)):
        for lst in ranked_lists:
            if rank < len(lst) and lst[rank].chunk_id not in seen:
                seen.add(lst[rank].chunk_id)
                out.append(lst[rank])
                if len(out) == limit:
                    return out
    return out


@dataclass
class Source:
    label: str          # "S1"
    hit: Hit
    title: str
    authors: str
    year: int
    url: str


@dataclass
class AgentResult:
    project: str
    question: str
    answer: str
    answerable: str
    sources: list[Source]                 # every passage shown to the answer step
    cited: list[str]                      # labels actually cited, in order of first use
    invalid_citations: list[str]          # cited labels that don't exist (should be empty)
    trace: list[dict] = field(default_factory=list)
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0


class ResearchAgent:
    """Stateless across questions: one instance serves every project."""

    def __init__(self, retriever: Retriever | None = None, llm: LLM | None = None,
                 retrieval_method: str = "hybrid_bm25"):
        self.retriever = retriever or Retriever()
        self.llm = llm or LLM()
        self.method = retrieval_method

    def _project(self, project: str) -> tuple[str, dict]:
        """(system prompt, {paper_id: (title, authors, year, url)}) for one project."""
        conn = self.retriever.conn
        row = conn.execute("SELECT name, description FROM projects WHERE id = %s", (project,)).fetchone()
        if row is None:
            raise KeyError(f"no such project: {project}")
        papers = {
            r[0]: r[1:]
            for r in conn.execute(
                "SELECT id, title, authors, year, url FROM papers WHERE project_id = %s AND status = 'ready'",
                (project,))
        }
        return system_prompt(*row), papers

    # --- helpers ---------------------------------------------------------------
    def _call(self, res: AgentResult, system: str, step: str, prompt: str, schema: dict) -> dict:
        if res.llm_calls >= MAX_LLM_CALLS:
            raise RuntimeError(f"LLM call budget ({MAX_LLM_CALLS}) exhausted at step {step!r}")
        r = self.llm.generate(prompt, system=system, json_schema=schema, purpose=f"agent_{step}")
        res.llm_calls += 1
        res.input_tokens += r.input_tokens
        res.output_tokens += r.output_tokens
        out = r.json()
        res.trace.append({"step": step, "output": out, "tokens": [r.input_tokens, r.output_tokens],
                          "latency_s": round(r.latency_s, 2), "cached": r.cached})
        return out

    @staticmethod
    def _format(evidence: list[Hit], titles: dict) -> str:
        blocks = []
        for i, h in enumerate(evidence, 1):
            title, authors, year, _ = titles[h.paper_key]
            pages = f"p.{h.page_start}" if h.page_start == h.page_end else f"pp.{h.page_start}-{h.page_end}"
            who = f"{authors} ({year})" if authors and year else (authors or (str(year) if year else "Unknown authors"))
            blocks.append(f"[S{i}] {who}, \"{title}\", {pages}, key={h.paper_key}\n{h.text}")
        return "\n\n".join(blocks)

    # --- baseline: one search, no planning or checking (for evaluation) ---------
    def single_shot(self, project: str, question: str) -> AgentResult:
        """Same answer prompt and evidence budget as `run`, but one search with the raw question."""
        t0 = time.perf_counter()
        system, papers = self._project(project)
        res = AgentResult(project, question, "", "no", [], [], [])
        evidence = self.retriever.search(project, question, k=MAX_EVIDENCE, method=self.method)
        res.trace.append({"step": "search", "round": 1, "query": question, "paper": None,
                          "hits": [h.chunk_id for h in evidence], "new": [h.chunk_id for h in evidence]})
        self._finish(res, question, evidence, t0, system, papers)
        return res

    def _finish(self, res: AgentResult, question: str, evidence: list[Hit], t0: float,
                system: str, papers: dict) -> None:
        out = self._call(res, system, "answer", ANSWER_PROMPT.format(
            question=question, evidence=self._format(evidence, papers)), ANSWER_SCHEMA)
        res.answer, res.answerable = out["answer"], out["answerable"]
        for i, h in enumerate(evidence, 1):
            title, authors, year, url = papers[h.paper_key]
            res.sources.append(Source(f"S{i}", h, title, authors, year, url))
        seen = extract_citations(res.answer)
        valid = {s.label for s in res.sources}
        res.cited = [c for c in seen if c in valid]
        res.invalid_citations = [c for c in seen if c not in valid]
        res.latency_s = round(time.perf_counter() - t0, 2)

    # --- the loop --------------------------------------------------------------
    def run(self, project: str, question: str) -> AgentResult:
        t0 = time.perf_counter()
        system, papers = self._project(project)
        res = AgentResult(project, question, "", "no", [], [], [])
        if not papers:
            res.answer = "This project has no processed papers yet. Upload PDFs first."
            res.latency_s = round(time.perf_counter() - t0, 2)
            return res
        ranked_lists: list[list[Hit]] = []   # one ranked list per query, in search order
        past_queries: list[str] = []

        plan = self._call(res, system, "plan", PLAN_PROMPT.format(question=question), PLAN_SCHEMA)
        queries: list[tuple[str, str | None]] = [(q, None) for q in plan["queries"][:3]]
        for round_no in range(1, MAX_ROUNDS + 1):
            for q, paper in queries:
                past_queries.append(q)
                hits = self.retriever.search(project, q, k=HITS_PER_QUERY, method=self.method, paper=paper)
                seen_ids = {h.chunk_id for lst in ranked_lists for h in lst}
                new = [h.chunk_id for h in hits if h.chunk_id not in seen_ids]
                ranked_lists.append(hits)
                res.trace.append({"step": "search", "round": round_no, "query": q, "paper": paper,
                                  "hits": [h.chunk_id for h in hits], "new": new})
            if round_no == MAX_ROUNDS:
                break
            evidence = interleave(ranked_lists, MAX_EVIDENCE)
            check = self._call(res, system, "check", CHECK_PROMPT.format(
                question=question, evidence=self._format(evidence, papers),
                past_queries="; ".join(past_queries)), CHECK_SCHEMA)
            queries = [
                (nq["query"], nq["paper"] if nq.get("paper") in papers else None)
                for nq in check.get("new_queries", [])
                if nq.get("query") and nq["query"] not in past_queries
            ][:2]
            if check["sufficient"] or not queries:
                break

        self._finish(res, question, interleave(ranked_lists, MAX_EVIDENCE), t0, system, papers)
        return res
