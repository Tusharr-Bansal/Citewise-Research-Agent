"""Judge-human agreement on faithfulness (docs/decisions/0017).

Joins Tushar's blind labels (exported from the labeling page's `faith_labels` collection to
results/faith_labels_human.json) with the judge's verdicts (results/faith_sample.json, the blind key).
Reports raw agreement, Cohen's kappa (4-class and binary), the confusion matrix, and a bootstrap CI.

Labelling method: model-assisted drafts (results/faith_labels_drafts.json), each reviewed against the
cited passages and finalised by Tushar (results/faith_labels_human.json).

Run:  python eval/judge_agreement.py
"""
from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

RES = Path(__file__).parent / "results"
CLASSES = ["supported", "partly", "unsupported", "no_claims"]
BINARY = {"supported": "ok", "no_claims": "ok", "partly": "flag", "unsupported": "flag"}


def kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main() -> None:
    key = {k["blind_id"]: k for k in json.loads((RES / "faith_sample.json").read_text())}
    human = json.loads((RES / "faith_labels_human.json").read_text())
    sugg = json.loads((RES / "faith_labels_drafts.json").read_text())
    ids = sorted(key)
    H = [human[i]["verdict"] for i in ids]
    J = [key[i]["judge_verdict"] for i in ids]
    S = [sugg[i] for i in ids]
    out: dict = {"n": len(ids)}

    def report(name: str, a: list[str], b: list[str]) -> None:
        agree = sum(x == y for x, y in zip(a, b)) / len(a)
        ab = [BINARY[x] for x in a]
        bb = [BINARY[x] for x in b]
        rng = random.Random(0)
        boots = []
        for _ in range(5000):
            idx = [rng.randrange(len(a)) for _ in a]
            boots.append(kappa([a[i] for i in idx], [b[i] for i in idx]))
        boots.sort()
        r = {"raw_agreement": round(agree, 3), "kappa_4class": round(kappa(a, b), 3),
             "kappa_4class_ci95": [round(boots[125], 3), round(boots[4874], 3)],
             "binary_agreement": round(sum(x == y for x, y in zip(ab, bb)) / len(ab), 3),
             "kappa_binary": round(kappa(ab, bb), 3)}
        out[name] = r
        print(f"{name}: raw {r['raw_agreement']:.2f} | kappa {r['kappa_4class']:.2f} "
              f"[{r['kappa_4class_ci95'][0]:.2f}, {r['kappa_4class_ci95'][1]:.2f}] | "
              f"binary (problem vs no problem) raw {r['binary_agreement']:.2f}, kappa {r['kappa_binary']:.2f}")

    print(f"n = {len(ids)} answers (30 per system)\n")
    report("judge_vs_human", J, H)
    report("draft_vs_final", S, H)
    # The reviewed labels as the reference: how well does the judge classify against them?
    hb, jb = [BINARY[x] for x in H], [BINARY[x] for x in J]
    tp = sum(h == "flag" and j == "flag" for h, j in zip(hb, jb))
    fn = sum(h == "flag" and j == "ok" for h, j in zip(hb, jb))
    tn = sum(h == "ok" and j == "ok" for h, j in zip(hb, jb))
    fp = sum(h == "ok" and j == "flag" for h, j in zip(hb, jb))
    ref = {"accuracy": round(sum(a == b for a, b in zip(J, H)) / len(H), 3),
           "baseline_always_supported": round(H.count("supported") / len(H), 3),
           "recall": round(tp / (tp + fn), 3) if tp + fn else None,
           "specificity": round(tn / (tn + fp), 3) if tn + fp else None,
           "precision": round(tp / (tp + fp), 3) if tp + fp else None}
    ref["balanced_accuracy"] = round((ref["recall"] + ref["specificity"]) / 2, 3)
    out["judge_vs_reference"] = ref
    print("\njudge vs reviewed labels as reference:", ref)
    print("\nConfusion matrix (rows = human, cols = judge):")
    print(" " * 12 + "".join(f"{c[:9]:>11s}" for c in CLASSES))
    cm = {h: {j: 0 for j in CLASSES} for h in CLASSES}
    for h, j in zip(H, J):
        cm[h][j] += 1
    for h in CLASSES:
        print(f"{h:12s}" + "".join(f"{cm[h][j]:11d}" for j in CLASSES))
    out["confusion_human_rows_judge_cols"] = cm
    out["label_counts"] = {"human": Counter(H), "judge": Counter(J)}
    print("\nlabel counts  human:", dict(Counter(H)), " judge:", dict(Counter(J)))

    by_sys = {}
    for sysname in ("single_shot", "agent"):
        sel = [k for k, i in enumerate(ids) if key[i]["system"] == sysname]
        hs = [H[k] for k in sel]
        by_sys[sysname] = {"n": len(sel), "human_supported_or_no_claims": round(sum(BINARY[x] == "ok" for x in hs) / len(hs), 3),
                           "human_partly": sum(x == "partly" for x in hs), "human_unsupported": sum(x == "unsupported" for x in hs)}
    out["human_by_system"] = by_sys
    print("\nhuman labels by system (unblinded):", json.dumps(by_sys))
    missed = [(key[i]["row"], human[i].get("note")) for i in ids
              if BINARY[human[i]["verdict"]] == "flag" and BINARY[key[i]["judge_verdict"]] == "ok"]
    out["judge_missed"] = missed
    print(f"\nanswers the human flagged but the judge passed: {len(missed)}")
    for row, note in missed:
        print("  ", row, "|", note)
    (RES / "judge_agreement.json").write_text(json.dumps(out, indent=1, default=dict))


if __name__ == "__main__":
    main()
