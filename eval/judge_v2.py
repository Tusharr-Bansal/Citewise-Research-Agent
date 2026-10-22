"""Claim-level faithfulness judge (docs/decisions/0018), tested on the 60 human-verified answers.

Pre-registered method, run once:
  1. the judge splits the answer into atomic factual claims;
  2. for each claim: cited labels, a verbatim supporting quote, and a support label;
  3. code checks that each "supported" claim's quote is really in the cited passages;
  4. code derives the answer-level verdict from the claims.

Same judge model and inputs as eval_agent.py; only the method differs.

Run:  python eval/judge_v2.py   -> results/judge_v2.json + printed agreement with the human labels
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
from build_gold import quote_in_chunk  # noqa: E402
from citewise.llm import LLM  # noqa: E402
from eval_agent import JUDGE_MODEL, JUDGE_SYSTEM  # noqa: E402
from judge_agreement import BINARY, CLASSES, kappa  # noqa: E402

RES = HERE / "results"
# The judge looped on one answer until the server cut the request at 300 s; a short answer needs a few
# hundred tokens of claims, so 2048 caps runaway output without limiting normal judgements.
MAX_OUTPUT_TOKENS = 2048

CLAIM_PROMPT = """Question: {question}

Answer to evaluate (citations like [S2] refer to the passages below):
\"\"\"{answer}\"\"\"

Cited passages:
{passages}

Check the answer's FAITHFULNESS claim by claim.

1. Split the answer into atomic factual claims (one checkable fact each). Do NOT include:
   - statements that information is missing or not found;
   - phrases that only identify which paper or method the question is about.
2. For each claim give:
   - "claim": the claim in a few words;
   - "cited": the passage labels the answer cites for it (e.g. ["S2"]);
   - "quote": a VERBATIM span copied from the cited passages that supports the claim, or "" if none does;
   - "support", one of:
     - "supported": the quote states the claim, including its strength (hedges like "may", "likely";
       quantifiers like "some", "primarily") and every specific detail;
     - "overstated": the passage supports only a weaker, narrower, or more hedged version, or the claim
       adds a specific detail (a number, name, scope, purpose) the passage does not state;
     - "wrong_source": none of the cited passages supports it, or one of its cited passages contradicts it;
     - "unsupported": nothing in the cited passages supports it.
Judge only against the passages shown. Ignore completeness and real-world truth.
"""
CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "cited": {"type": "array", "items": {"type": "string"}},
                    "quote": {"type": "string"},
                    "support": {"type": "string", "enum": ["supported", "overstated", "wrong_source", "unsupported"]},
                },
                "required": ["claim", "cited", "quote", "support"],
            },
        }
    },
    "required": ["claims"],
}


def verdict_from_claims(claims: list[dict], passages: str, check_quotes: bool) -> str:
    """Mirror the labelling rubric: supported = every claim backed; unsupported = the main claims are
    not backed at all; partly = anything in between (overstated, wrong source, or unverifiable quote)."""
    if not claims:
        return "no_claims"
    fully, unbacked = 0, 0
    for c in claims:
        if c["support"] == "unsupported":
            unbacked += 1
        elif c["support"] == "supported" and (not check_quotes or quote_in_chunk(c["quote"], passages)[0]):
            fully += 1
        # overstated / wrong_source / supported-but-quote-not-found: partly backed
    if fully == len(claims):
        return "supported"
    return "unsupported" if unbacked / len(claims) > 0.5 else "partly"


def main() -> None:
    rows = json.loads((RES / "agent_eval.json").read_text())
    key = {k["blind_id"]: k for k in json.loads((RES / "faith_sample.json").read_text())}
    human = json.loads((RES / "faith_labels_human.json").read_text())
    judge = LLM(model=JUDGE_MODEL, max_attempts=8)
    ids = sorted(key)
    results = {}
    for n, i in enumerate(ids, 1):
        r = rows[key[i]["row"]]
        resp = judge.generate(CLAIM_PROMPT.format(question=r["question"], answer=r["answer"],
                                                  passages=r["cited_passages_text"]),
                              system=JUDGE_SYSTEM, json_schema=CLAIM_SCHEMA, purpose="judge_v2_claims",
                              max_output_tokens=MAX_OUTPUT_TOKENS)
        try:
            # The model sometimes appends a stray ``` after valid JSON: read the first JSON object only.
            out, _ = json.JSONDecoder().raw_decode(resp.text.strip().removeprefix("```json").strip())
            claims = out["claims"]
        except (ValueError, KeyError):  # truncated or malformed: a judge failure, reported, never guessed
            results[i] = {"row": key[i]["row"], "claims": None, "verdict": "judge_failed",
                          "verdict_no_quote_check": "judge_failed", "raw": resp.text[-300:]}
            print(f"[{n}/60] JUDGE FAILED (output not parseable, {resp.output_tokens} tokens)", flush=True)
            continue
        results[i] = {
            "row": key[i]["row"], "claims": claims,
            "quote_found": [quote_in_chunk(c["quote"], r["cited_passages_text"])[1] for c in claims],
            "verdict": verdict_from_claims(claims, r["cited_passages_text"], check_quotes=True),
            "verdict_no_quote_check": verdict_from_claims(claims, r["cited_passages_text"], check_quotes=False),
        }
        print(f"[{n}/60] {results[i]['verdict']:11s} human={human[i]['verdict']:11s} claims={len(claims)}", flush=True)
    (RES / "judge_v2.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))

    failed = [i for i in ids if results[i]["verdict"] == "judge_failed"]
    print(f"\njudge failures: {len(failed)} {[results[i]['row'] for i in failed]}")
    ids = [i for i in ids if i not in failed]   # agreement is computed on the answers the judge could judge
    N = len(ids)
    H = [human[i]["verdict"] for i in ids]
    summary = {"n_judged": N, "judge_failures": [results[i]["row"] for i in failed]}
    for name, J in (("old_judge", [key[i]["judge_verdict"] for i in ids]),
                    ("judge_v2", [results[i]["verdict"] for i in ids]),
                    ("judge_v2_no_quote_check", [results[i]["verdict_no_quote_check"] for i in ids])):
        rng = random.Random(0)
        boots = sorted(kappa([J[k] for k in idx], [H[k] for k in idx])
                       for idx in ([rng.randrange(N) for _ in range(N)] for _ in range(5000)))
        hb, jb = [BINARY[x] for x in H], [BINARY[x] for x in J]
        s = {"kappa": round(kappa(J, H), 3), "ci95": [round(boots[125], 3), round(boots[4874], 3)],
             "raw": round(sum(a == b for a, b in zip(J, H)) / N, 3), "kappa_binary": round(kappa(jb, hb), 3),
             "caught": sum(h == "flag" and j == "flag" for h, j in zip(hb, jb)), "of_flagged": hb.count("flag"),
             "false_alarms": sum(h == "ok" and j == "flag" for h, j in zip(hb, jb)), "of_clean": hb.count("ok"),
             "counts": dict(Counter(J))}
        summary[name] = s
        print(f"{name:24s} kappa {s['kappa']:.2f} [{s['ci95'][0]:.2f}, {s['ci95'][1]:.2f}] raw {s['raw']:.2f} "
              f"binary kappa {s['kappa_binary']:.2f} | caught {s['caught']}/{s['of_flagged']} "
              f"| false alarms {s['false_alarms']}/{s['of_clean']} | {s['counts']}")
    cm = {h: {j: 0 for j in CLASSES} for h in CLASSES}
    for h, i in zip(H, ids):
        cm[h][results[i]["verdict"]] += 1
    summary["judge_v2_confusion_human_rows"] = cm
    (RES / "judge_v2_summary.json").write_text(json.dumps(summary, indent=1))
    print("\nconfusion (rows human, cols judge_v2):")
    for h in CLASSES:
        print(f"  {h:12s}", [cm[h][j] for j in CLASSES])


if __name__ == "__main__":
    main()
