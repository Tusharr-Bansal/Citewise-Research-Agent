"""Draft candidate gold questions from sampled chunks, for human verification.

Each candidate is anchored to an *evidence quote* (verbatim text from the
passage), not to a chunk id. Relevance is later judged as "does a retrieved
chunk contain this quote?", so the gold set stays valid when chunking changes.

Usage:  python eval/make_gold_candidates.py  -> eval/gold_candidates.json
"""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from citewise import db  # noqa: E402
from citewise.ingest import DEMO_PROJECT_ID  # noqa: E402
from citewise.chunking import numeric_fraction  # noqa: E402
from citewise.llm import LLM  # noqa: E402

OUT = Path(__file__).with_name("gold_candidates.json")
PER_PAPER = 2
SEED = 7

SYSTEM = (
    "You help build a test set for a search engine over heart-sound (phonocardiogram) "
    "and model-calibration research papers. You write questions that a researcher in "
    "this field would genuinely ask."
)

PROMPT = """Paper: {title} ({authors}, {year})

Passage:
\"\"\"{text}\"\"\"

Write ONE question that this passage answers.

Rules:
1. The question must be answerable from the passage alone.
2. Make it specific enough that the answer would not be found in most papers on this topic. You may mention a method, dataset, or model by name, but do NOT name the paper, its title, or its authors.
3. Paraphrase. Do not copy distinctive phrases from the passage into the question; ask it the way a person who has not read the passage would.
4. Do not refer to "the passage", "this study" or "the authors".
5. evidence_quote must be copied EXACTLY, character for character, from the passage: one or two consecutive sentences that support the answer.
6. If the passage has no substantive research content (author lists, acknowledgments, funding, affiliations, a figure's axis labels), set skip to true and give a reason.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "skip": {"type": "boolean"},
        "skip_reason": {"type": "string"},
        "question": {"type": "string"},
        "answer": {"type": "string"},
        "evidence_quote": {"type": "string"},
    },
    "required": ["skip", "question", "answer", "evidence_quote"],
}

_WS = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9]+")
STOP = set(
    "a an the of in on for to and or is are was were be by with what which how does do did "
    "from that this as at it its into than when why who whom whose used use using between".split()
)


def norm(s: str) -> str:
    return _WS.sub(" ", s).strip().lower()


def overlap(question: str, evidence: str) -> float:
    """Share of the question's content words that also appear in the evidence."""
    q = {w for w in _WORD.findall(question.lower()) if w not in STOP}
    e = set(_WORD.findall(evidence.lower()))
    return len(q & e) / max(1, len(q))


def main() -> None:
    conn = db.connect()
    papers = {
        r[0]: r[1:]
        for r in conn.execute("SELECT id, title, authors, year FROM papers WHERE project_id = %s ORDER BY id",
                              (DEMO_PROJECT_ID,)).fetchall()
    }
    rows = conn.execute(
        "SELECT id, paper_id, page_start, page_end, n_tokens, text FROM chunks WHERE project_id = %s ORDER BY id",
        (DEMO_PROJECT_ID,)
    ).fetchall()

    sampled = []
    for key in papers:
        # one RNG per paper: adding a paper later never changes another paper's sample
        rng = random.Random(f"{SEED}:{key}")
        # substantive chunks only: full-size, mostly prose, not the title page
        pool = [
            r for r in rows
            if r[1] == key and r[4] >= 200 and numeric_fraction(r[5]) < 0.25 and r[2] > 1
        ]
        # never pick neighbouring chunks: they overlap, so they can yield the same question
        picked: list = []
        for r in rng.sample(pool, len(pool)):
            idx = int(r[0].rsplit(":", 1)[1])
            if all(abs(idx - int(p[0].rsplit(":", 1)[1])) >= 2 for p in picked):
                picked.append(r)
            if len(picked) == PER_PAPER:
                break
        sampled += picked

    llm = LLM()
    out, skipped, bad_quote = [], 0, 0
    for i, (cid, key, p0, p1, _, text) in enumerate(sampled, 1):
        title, authors, year = papers[key]
        r = llm.generate(
            PROMPT.format(title=title, authors=authors, year=year, text=text),
            system=SYSTEM,
            json_schema=SCHEMA,
            temperature=0.3,
            purpose="gold_draft",
        ).json()
        if r.get("skip"):
            skipped += 1
            print(f"[{i}/{len(sampled)}] skip {cid}: {r.get('skip_reason', '')[:60]}")
            continue
        quote_ok = norm(r["evidence_quote"]) in norm(text)
        bad_quote += not quote_ok
        out.append(
            {
                "id": f"g:{cid}",  # stable: tied to the source chunk, not to run order
                "source": "llm_draft",
                "paper_key": key,
                "source_chunk": cid,
                "pages": [p0, p1],
                "question": r["question"],
                "answer": r["answer"],
                "evidence_quote": r["evidence_quote"],
                "quote_verified": quote_ok,
                "lexical_overlap": round(overlap(r["question"], r["evidence_quote"]), 3),
                "passage": text,
            }
        )
        print(f"[{i}/{len(sampled)}] {cid}: {r['question'][:90]}")

    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    ov = sorted(c["lexical_overlap"] for c in out)
    print(
        f"\n{len(out)} candidates written ({skipped} skipped, {bad_quote} with an inexact quote) | "
        f"question/evidence word overlap: median {ov[len(ov) // 2]:.2f}"
    )


if __name__ == "__main__":
    main()
