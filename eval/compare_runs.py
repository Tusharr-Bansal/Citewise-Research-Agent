"""Paired comparison of agent-evaluation runs on identical questions (docs/decisions/0017).

Runs compared:
  v1  - agent with the original PCG-specific prompts            (agent_eval_v1_pcg_prompts.json)
  v2a - agent with generalized prompts, before the fix in 0016  (agent_eval_v2a_before_anchor.json)
  v3  - agent with generalized prompts + original-query anchor  (agent_eval.json)
and the single-search baseline from the v3 run, plus
  v4  - single search with the hedge-keeping answer prompt, 29-paper demo (agent_eval_v4_fast.json):
        the default mode since decision 0019.

Confidence intervals: paired bootstrap over questions (10,000 resamples). With 45 questions,
differences under ~10 points are usually not distinguishable from noise; the intervals say so.

Run:  python eval/compare_runs.py
"""

from __future__ import annotations

import json
import random
import statistics
from pathlib import Path

HERE = Path(__file__).parent
RES = HERE / "results"
SCORE = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0, "abstained": 0.0}


def load(name: str) -> dict:
    return json.loads((RES / name).read_text())


def boot_diff(a: list[float], b: list[float], n: int = 10_000, seed: int = 0) -> tuple[float, float, float]:
    """Mean of (b - a) over paired items, with a 95% bootstrap interval."""
    rng = random.Random(seed)
    d = [y - x for x, y in zip(a, b)]
    means = sorted(statistics.fmean(rng.choices(d, k=len(d))) for _ in range(n))
    return statistics.fmean(d), means[int(0.025 * n)], means[int(0.975 * n)]


def main() -> None:
    v3 = load("agent_eval.json")
    v2a = load("agent_eval_v2a_before_anchor.json")
    v1 = load("agent_eval_v1_pcg_prompts.json")
    v4 = load("agent_eval_v4_fast.json")
    single_ids = sorted({r["id"] for r in v3.values() if r["kind"] == "single"})
    all_ids = sorted({r["id"] for r in v3.values()})

    def value(run: dict, system: str, i: str, f):
        try:
            return f(run[f"{i}|{system}"])
        except (KeyError, TypeError):  # question missing, or not judged, in this run
            return None

    evidence = lambda r: float(r["evidence_hit"])  # noqa: E731
    correct = lambda r: float(r["correctness"]["verdict"] == "correct")  # noqa: E731
    credit = lambda r: SCORE[r["correctness"]["verdict"]]  # noqa: E731
    no_unsupported = lambda r: float(r["faithfulness"]["verdict"] in ("supported", "no_claims"))  # noqa: E731

    out: dict = {"n_single": len(single_ids), "n_all": len(all_ids), "metrics": {}, "paired": {}, "cost": {}}
    runs = {"single search v4 (default)": (v4, "single_shot"),
            "single search": (v3, "single_shot"), "agent v3 (shipped)": (v3, "agent"),
            "agent v2a (before fix)": (v2a, "agent"), "agent v1 (PCG prompts)": (v1, "agent")}

    print(f"Single-passage questions: {len(single_ids)}; all questions incl. synthesis: {len(all_ids)}.")
    print("Each cell: mean (n). Runs v1/v2a lack some rows, so compare them only through the paired section.\n")
    print(f"{'system':24s} {'evidence':>11s} {'correct':>11s} {'credit':>11s} {'no unsupported (all)':>21s}")
    for name, (run, system) in runs.items():
        cells, rec = [], {}
        for metric, f, ids in (("evidence", evidence, single_ids), ("correct", correct, single_ids),
                               ("credit", credit, single_ids), ("no_unsupported", no_unsupported, all_ids)):
            vals = [v for v in (value(run, system, i, f) for i in ids) if v is not None]
            rec[metric] = {"mean": round(statistics.fmean(vals), 3), "n": len(vals)} if vals else None
            cells.append(f"{statistics.fmean(vals):.2f} ({len(vals)})" if vals else "n/a")
        out["metrics"][name] = rec
        print(f"{name:24s} {cells[0]:>11s} {cells[1]:>11s} {cells[2]:>11s} {cells[3]:>21s}")

    print("\nPaired differences B - A on questions both runs have, mean [95% bootstrap CI];")
    print("an interval that contains 0 means the difference is not distinguishable from noise:")
    pairs = [("agent v3 (shipped)", "single search"), ("agent v3 (shipped)", "agent v2a (before fix)"),
             ("agent v3 (shipped)", "agent v1 (PCG prompts)"), ("agent v2a (before fix)", "single search"),
             ("single search v4 (default)", "single search"), ("single search v4 (default)", "agent v3 (shipped)")]
    for bn, an in pairs:
        for metric, f, ids in (("evidence", evidence, single_ids), ("credit", credit, single_ids),
                               ("no_unsupported", no_unsupported, all_ids)):
            a_all = [value(*runs[an], i, f) for i in ids]
            b_all = [value(*runs[bn], i, f) for i in ids]
            ab = [(x, y) for x, y in zip(a_all, b_all) if x is not None and y is not None]
            if len(ab) < 10:
                continue
            m, lo, hi = boot_diff([x for x, _ in ab], [y for _, y in ab])
            key = f"{bn} - {an} | {metric}"
            out["paired"][key] = {"n": len(ab), "diff": round(m, 3), "ci95": [round(lo, 3), round(hi, 3)]}
            print(f"  {key:62s} n={len(ab):2d}  {m:+.2f} [{lo:+.2f}, {hi:+.2f}]")

    print("\nCost per question (median, all questions):")
    for name, run, system in (("single search v4 (default)", v4, "single_shot"),
                              ("single search", v3, "single_shot"), ("agent v3 (shipped)", v3, "agent")):
        R = [run[f"{i}|{system}"] for i in all_ids if f"{i}|{system}" in run]
        c = {k: statistics.median(r[k] for r in R) for k in ("llm_calls", "input_tokens", "latency_s")}
        out["cost"][name] = c
        print(f"  {name:22s} LLM calls {c['llm_calls']:.0f} | input tokens {c['input_tokens']:.0f} | latency {c['latency_s']:.1f}s")

    syn = [i for i in all_ids if v3[f"{i}|agent"]["kind"] == "synthesis"]
    def papers(r: dict) -> int:  # distinct papers among the passages an answer cites
        return len({s["chunk_id"].split(":")[0] for s in r["sources"] if s["label"] in r["cited"]})

    bs = [papers(v3[f"{i}|single_shot"]) for i in syn]
    ba = [papers(v3[f"{i}|agent"]) for i in syn]
    out["synthesis_papers_cited"] = {"n": len(syn), "single": round(statistics.fmean(bs), 2),
                                     "agent": round(statistics.fmean(ba), 2)}
    print(f"\nSynthesis questions (n={len(syn)}): distinct papers cited per answer, mean: "
          f"single {statistics.fmean(bs):.1f}, agent {statistics.fmean(ba):.1f}  (breadth, not quality)")

    (RES / "comparison.json").write_text(json.dumps(out, indent=1))
    print(f"\nwritten {RES / 'comparison.json'}")


if __name__ == "__main__":
    main()
