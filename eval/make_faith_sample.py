"""Pick the blind sample of answers Tushar labels for faithfulness (docs/decisions/0017).

- 60 answers, 30 per system, from the shipped run (results/agent_eval.json).
- Every answer the judge did NOT rate "supported" is included (so disagreements on the rare
  classes can show up at all); the rest are drawn at random with a fixed seed.
- Blind: the labeling page gets a random id per answer, never the system name or the judge's
  verdict. The mapping stays here, in results/faith_sample.json.
- Shown passages = the passages the answer cites, exactly what the judge saw.

Run:  python eval/make_faith_sample.py   (writes results/faith_sample.json and faith_sample_docs.json)
"""
from __future__ import annotations

import json
import random
import secrets
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))
from citewise import db  # noqa: E402
from citewise.ingest import DEMO_PROJECT_ID  # noqa: E402

PER_SYSTEM = 30
SEED = 17


def main() -> None:
    rows = json.loads((HERE / "results" / "agent_eval.json").read_text())
    rng = random.Random(SEED)
    picked = []
    for system in ("single_shot", "agent"):
        R = [r for r in rows.values() if r["system"] == system]
        must = [r for r in R if r["faithfulness"]["verdict"] != "supported"]
        rest = [r for r in R if r["faithfulness"]["verdict"] == "supported"]
        picked += must + rng.sample(rest, PER_SYSTEM - len(must))
    rng.shuffle(picked)

    with db.connect() as c:
        papers = {r[0]: (r[1], r[2]) for r in c.execute(
            "SELECT id, authors, year FROM papers WHERE project_id = %s", (DEMO_PROJECT_ID,))}
        chunks = {r[0]: (r[1], r[2], r[3], r[4]) for r in c.execute(
            "SELECT id, paper_id, page_start, page_end, text FROM chunks WHERE project_id = %s", (DEMO_PROJECT_ID,))}

    docs, key = [], []
    for order, r in enumerate(picked):
        blind_id = "a_" + secrets.token_hex(6)
        passages = []
        for s in r["sources"]:
            if s["label"] not in r["cited"]:
                continue
            paper, p0, p1, text = chunks[s["chunk_id"]]
            authors, year = papers[paper]
            pages = f"p. {p0}" if p0 == p1 else f"pp. {p0}–{p1}"
            passages.append({"label": s["label"], "citation": f"{authors} ({year}), {pages}", "text": text})
        docs.append({"id": blind_id, "order": order, "question": r["question"], "answer": r["answer"],
                     "passages": passages})
        key.append({"blind_id": blind_id, "row": f"{r['id']}|{r['system']}", "system": r["system"],
                    "judge_verdict": r["faithfulness"]["verdict"]})
    (HERE / "results" / "faith_sample.json").write_text(json.dumps(key, indent=1))
    (HERE / "results" / "faith_sample_docs.json").write_text(json.dumps(docs, ensure_ascii=False))
    from collections import Counter
    print(len(docs), "answers;", Counter(k["system"] for k in key), Counter(k["judge_verdict"] for k in key))
    print("doc sizes (KB): max", max(len(json.dumps(d)) for d in docs) // 1024,
          "total", sum(len(json.dumps(d)) for d in docs) // 1024)


if __name__ == "__main__":
    main()
