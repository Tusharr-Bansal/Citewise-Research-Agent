"""Combine LLM drafts with Tushar's verdicts into the gold test set.

Inputs:
  eval/gold_candidates.json        drafts (question, evidence quote, source chunk)
  eval/labels_snapshot.json        Tushar's verdicts + rewrites, exported from the labeling page
  eval/own_questions_snapshot.json Tushar's own synthesis questions
Outputs:
  eval/gold_single.json     single-evidence questions (dropped drafts removed, fixes applied)
  eval/gold_synthesis.json  Tushar's multi-paper questions (no single evidence passage)

Also resolves, for each single-evidence question, *every* chunk that contains its
evidence quote (overlapping neighbours can both contain it). Matching is tolerant of
PDF-extraction noise: compare letters and digits only, and fall back to fuzzy matching
when a caption or stray glyph has been inserted into the quoted sentence.
"""

from __future__ import annotations

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from citewise import db  # noqa: E402
from citewise.ingest import DEMO_PROJECT_ID  # noqa: E402

HERE = Path(__file__).parent
FUZZY_MIN_COVERAGE = 0.85  # share of the quote's characters found, in order, in the chunk


def alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def quote_in_chunk(quote: str, chunk: str) -> tuple[bool, float]:
    q, c = alnum(quote), alnum(chunk)
    if not q:
        return False, 0.0
    if q in c:
        return True, 1.0
    blocks = SequenceMatcher(None, q, c, autojunk=False).get_matching_blocks()
    # only count reasonably long runs, so scattered single letters don't add up
    covered = sum(b.size for b in blocks if b.size >= 8)
    cov = covered / len(q)
    return cov >= FUZZY_MIN_COVERAGE, cov


def main() -> None:
    drafts = {d["id"]: d for d in json.loads((HERE / "gold_candidates.json").read_text())}
    labels = json.loads((HERE / "labels_snapshot.json").read_text())
    own = json.loads((HERE / "own_questions_snapshot.json").read_text())

    conn = db.connect()
    chunks_by_paper: dict[str, list[tuple[str, str]]] = {}
    for cid, paper, text in conn.execute(
        "SELECT id, paper_id, text FROM chunks WHERE project_id = %s ORDER BY id", (DEMO_PROJECT_ID,)):
        chunks_by_paper.setdefault(paper, []).append((cid, text))

    single, missing_label, unmatched = [], [], []
    for did, d in drafts.items():
        lab = labels.get(did)
        if lab is None:
            missing_label.append(did)
            continue
        if lab["verdict"] == "drop":
            continue
        relevant, best_cov = [], 0.0
        for cid, text in chunks_by_paper.get(d["paper_key"], []):
            ok, cov = quote_in_chunk(d["evidence_quote"], text)
            best_cov = max(best_cov, cov)
            if ok:
                relevant.append(cid)
        if not relevant:
            unmatched.append((did, round(best_cov, 2)))
        single.append(
            {
                "id": did,
                "question": lab["fixed_question"] if lab["verdict"] == "fix" else d["question"],
                "draft_question": d["question"],
                "verdict": lab["verdict"],
                "ambiguous": bool(lab.get("ambiguous")),
                "paper_key": d["paper_key"],
                "evidence_quote": d["evidence_quote"],
                "relevant_chunks": relevant,
            }
        )

    synthesis = [
        {"id": f"own:{k}", "question": v["question"], "paper_key": v.get("paper_key"), "where": v.get("where")}
        for k, v in sorted(own.items(), key=lambda kv: kv[1]["created_at"])
    ]

    (HERE / "gold_single.json").write_text(json.dumps(single, indent=2, ensure_ascii=False))
    (HERE / "gold_synthesis.json").write_text(json.dumps(synthesis, indent=2, ensure_ascii=False))

    n_amb = sum(q["ambiguous"] for q in single)
    print(f"single-evidence questions: {len(single)} ({len(single) - n_amb} unambiguous, {n_amb} ambiguous)")
    print(f"  verdicts kept: good={sum(q['verdict']=='good' for q in single)} fix={sum(q['verdict']=='fix' for q in single)}")
    print(f"  relevant chunks per question: {sorted(len(q['relevant_chunks']) for q in single)}")
    print(f"synthesis questions: {len(synthesis)}")
    if missing_label:
        print(f"WARNING drafts without a verdict: {missing_label}")
    if unmatched:
        print(f"WARNING evidence not found in any chunk (best coverage): {unmatched}")


if __name__ == "__main__":
    main()
