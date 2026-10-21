"""End-to-end evaluation: the agent vs. a single-search baseline, on all gold questions.

Per question and system it records the answer, the passages shown, citations, cost,
and two LLM-judge verdicts (judge = a different, stronger model than the answerer):
  correctness   (single-evidence questions) vs Tushar-verified reference evidence
  faithfulness  (all questions) is every claim backed by the passage it cites?

Usage:  python eval/eval_agent.py  -> eval/results/agent_eval.json + printed summary
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from citewise.agent import AgentResult, ResearchAgent  # noqa: E402
from citewise.ingest import DEMO_PROJECT_ID  # noqa: E402
from citewise.llm import LLM, DailyQuotaExhausted  # noqa: E402

HERE = Path(__file__).parent
JUDGE_MODEL = "gemma-4-26b-a4b-it"  # 3.6-flash free tier = 20 requests/day; see docs/decisions/0014
JUDGE_SYSTEM = "You are a strict, careful evaluator of answers about research papers. You judge only against the text you are given."

FAITH_PROMPT = """Question: {question}

Answer to evaluate (citations like [S2] refer to the passages below):
\"\"\"{answer}\"\"\"

Cited passages:
{passages}

Judge FAITHFULNESS only: is every factual claim in the answer supported by the passage(s) it cites?
Ignore whether the answer is complete or whether it is true in the real world.
Statements that information is missing are not factual claims.
- supported: every factual claim is backed by its cited passage(s).
- partly: at least one claim is unsupported, overstated, or cites the wrong passage, but most are backed.
- unsupported: the main claims are not backed by the cited passages, or claims have no citation.
- no_claims: the answer makes no factual claims (it only says the evidence is insufficient).
List each unsupported claim briefly.
"""
FAITH_SCHEMA = {
    "type": "object",
    "properties": {
        "unsupported_claims": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string", "enum": ["supported", "partly", "unsupported", "no_claims"]},
    },
    "required": ["unsupported_claims", "verdict"],
}

CORRECT_PROMPT = """Question: {question}

Reference evidence (verified by a domain expert), from {paper}:
\"\"\"{evidence}\"\"\"

Answer to evaluate:
\"\"\"{answer}\"\"\"

{ambiguity_note}
Does the answer correctly answer the question?
- correct: contains the key facts the reference supports, with nothing contradicting it.
- partial: some of the key facts, or correct but missing an important part.
- incorrect: states something that contradicts the reference or answers a different question.
- abstained: says the information was not found / cannot answer.
"""
AMBIGUOUS_NOTE = ("Note: several papers in the corpus answer this question. An answer based on a different "
                  "paper that is consistent with the reference also counts as correct.")
CORRECT_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "verdict": {"type": "string", "enum": ["correct", "partial", "incorrect", "abstained"]},
    },
    "required": ["reason", "verdict"],
}


def cited_passages(r: AgentResult) -> str:
    by = {s.label: s for s in r.sources}
    return "\n\n".join(
        f"[{c}] {by[c].authors} ({by[c].year}), p.{by[c].hit.page_start}\n{by[c].hit.text}" for c in r.cited
    ) or "(no passages cited)"


def record(r: AgentResult) -> dict:
    return {
        "answer": r.answer, "answerable": r.answerable,
        "sources": [{"label": s.label, "chunk_id": s.hit.chunk_id} for s in r.sources],
        "cited": r.cited, "invalid_citations": r.invalid_citations,
        "llm_calls": r.llm_calls, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
        "latency_s": r.latency_s, "trace": r.trace,
    }


def main() -> None:
    single = json.loads((HERE / "gold_single.json").read_text())
    synth = json.loads((HERE / "gold_synthesis.json").read_text())
    drafts = {d["id"]: d for d in json.loads((HERE / "gold_candidates.json").read_text())}
    gold = {q["id"]: q for q in single}
    agent = ResearchAgent()
    judge = LLM(model=JUDGE_MODEL, max_attempts=4)
    papers = {r[0]: f"{r[1]} ({r[2]})" for r in agent.retriever.conn.execute(
        "SELECT id, authors, year FROM papers WHERE project_id = %s", (DEMO_PROJECT_ID,))}

    out_path = HERE / "results" / "agent_eval.json"
    rows = json.loads(out_path.read_text()) if out_path.exists() else {}
    save = lambda: out_path.write_text(json.dumps(rows, indent=1, ensure_ascii=False))  # noqa: E731
    questions = [("single", q) for q in single] + [("synthesis", q) for q in synth]

    # Pass 1: answers (resumable). Agent and judge are independent passes, so an
    # overloaded judge model can't stop answer generation.
    # If the answer model's daily quota runs out, stop answering but still judge what exists;
    # the next run (after the quota resets) picks up where this one stopped.
    quota_hit = False
    for i, (kind, q) in enumerate(questions, 1):
        for system in ("single_shot", "agent"):
            key = f"{q['id']}|{system}"
            if key in rows or quota_hit:
                continue
            try:
                r = (agent.single_shot(DEMO_PROJECT_ID, q["question"]) if system == "single_shot"
                     else agent.run(DEMO_PROJECT_ID, q["question"]))
            except DailyQuotaExhausted as e:
                quota_hit = True
                print(f"[answer] stopping: {e}. Re-run after the quota resets to finish.", flush=True)
                continue
            row = {"id": q["id"], "kind": kind, "system": system, "question": q["question"], **record(r)}
            row["cited_passages_text"] = cited_passages(r)
            if kind == "single":
                rel = set(q["relevant_chunks"])
                row["evidence_hit"] = any(s.hit.chunk_id in rel for s in r.sources)
                row["evidence_cited"] = any(s.hit.chunk_id in rel for s in r.sources if s.label in r.cited)
                row["ambiguous"] = q["ambiguous"]
                row["reference_answer"] = drafts[q["id"]]["answer"]
            rows[key] = row
            save()
            print(f"[answer {i}/{len(questions)}] {system:11s} {r.llm_calls} calls {r.latency_s:5.1f}s "
                  f"{r.answerable:6s} {q['question'][:70]}", flush=True)

    # Pass 2: judging (resumable; a call that still fails after retries is left for the next run).
    failed = 0
    for key, row in rows.items():
        try:
            if row["kind"] == "single" and "correctness" not in row:
                q = gold[row["id"]]
                row["correctness"] = judge.generate(CORRECT_PROMPT.format(
                    question=q["question"], paper=papers[q["paper_key"]], evidence=q["evidence_quote"],
                    answer=row["answer"], ambiguity_note=AMBIGUOUS_NOTE if q["ambiguous"] else ""),
                    system=JUDGE_SYSTEM, json_schema=CORRECT_SCHEMA, purpose="judge_correctness").json()
                save()
            if "faithfulness" not in row:
                row["faithfulness"] = judge.generate(FAITH_PROMPT.format(
                    question=row["question"], answer=row["answer"], passages=row["cited_passages_text"]),
                    system=JUDGE_SYSTEM, json_schema=FAITH_SCHEMA, purpose="judge_faithfulness").json()
                save()
            row["judge_model"] = JUDGE_MODEL
            save()
            print(f"[judge] {key[:60]:60s} {row.get('correctness', {}).get('verdict', '-'):9s} "
                  f"{row['faithfulness']['verdict']}", flush=True)
        except Exception as e:  # noqa: BLE001 - keep going, report at the end
            failed += 1
            print(f"[judge] {key[:60]} FAILED ({type(e).__name__}); will retry on next run", flush=True)
    print(f"\njudge failures this run: {failed}")
    print(f"answered {len(rows)}/{2 * len(questions)} question-system pairs")
    summarize({k: r for k, r in rows.items() if "faithfulness" in r and (r["kind"] != "single" or "correctness" in r)})


def summarize(rows: dict) -> None:
    def pct(xs, v):
        return sum(x == v for x in xs) / max(1, len(xs))

    print()
    for system in ("single_shot", "agent"):
        R = [r for r in rows.values() if r["system"] == system]
        S = [r for r in R if r["kind"] == "single"]
        corr = [r["correctness"]["verdict"] for r in S]
        faith = [r["faithfulness"]["verdict"] for r in R]
        print(f"=== {system} ===")
        print(f"  single-evidence (n={len(S)}): evidence reached answer {sum(r['evidence_hit'] for r in S)/len(S):.2f}, "
              f"evidence cited {sum(r['evidence_cited'] for r in S)/len(S):.2f}")
        print("  correctness: " + ", ".join(f"{v} {pct(corr, v):.2f}" for v in ("correct", "partial", "incorrect", "abstained")))
        print(f"  faithfulness (all n={len(R)}): " + ", ".join(f"{v} {pct(faith, v):.2f}" for v in ("supported", "partly", "unsupported", "no_claims")))
        print(f"  invalid citations: {sum(len(r['invalid_citations']) for r in R)} | "
              f"LLM calls/question median {statistics.median(r['llm_calls'] for r in R)} | "
              f"input tokens median {statistics.median(r['input_tokens'] for r in R):.0f} | "
              f"latency median {statistics.median(r['latency_s'] for r in R):.1f}s")


if __name__ == "__main__":
    main()
