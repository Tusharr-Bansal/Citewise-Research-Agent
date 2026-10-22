"""Write the demo page's "How well does it work?" panel from the evaluation results.

Every number is read from eval/results/*.json, nothing is typed by hand, so the panel can't
drift from the measurements. Output: src/citewise/static/eval_summary.json ({"html": ...}),
served by GET /api/eval and shown on the demo project only.

Run:  python eval/publish_summary.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
RES = HERE / "results"
OUT = HERE.parent / "src" / "citewise" / "static" / "eval_summary.json"
REPO = "https://github.com/Tusharr-Bansal/Citewise-Research-Agent/blob/main"


def pct(x: float) -> str:
    return f"{round(100 * x)}%"


def main() -> None:
    retrieval = json.loads((RES / "retrieval.json").read_text())["results"]
    comparison = json.loads((RES / "comparison.json").read_text())
    agreement = json.loads((RES / "judge_agreement.json").read_text())
    rows = json.loads((RES / "agent_eval.json").read_text())
    rows_v4 = json.loads((RES / "agent_eval_v4_fast.json").read_text())  # the default mode (0019)
    human = json.loads((RES / "faith_labels_human.json").read_text())

    hybrid, vector = retrieval["hybrid_bm25"]["all"], retrieval["vector"]["all"]
    labels = [h["verdict"] for h in human.values()]
    n_rev = len(labels)
    fully = labels.count("supported") + labels.count("no_claims")
    unsupported = labels.count("unsupported")
    all_rows = list(rows.values()) + list(rows_v4.values())
    invalid = sum(len(r["invalid_citations"]) for r in all_rows)
    m = comparison["metrics"]
    single, agent = m["single search v4 (default)"], m["agent v3 (shipped)"]
    cost = comparison["cost"]

    html = f"""
<p style="margin:10px 0 0">Measured on this demo project with a hand-verified test set
({comparison['n_single']} single-passage and {comparison['n_all'] - comparison['n_single']} multi-paper questions).</p>
<div class="tablewrap"><table class="metrics">
<tr><th>What</th><th>Result</th></tr>
<tr><td>Answers with an invented (unsupported) claim, in a blind review of {n_rev} (both search modes, earlier prompt version)</td><td><strong>{unsupported} of {n_rev}</strong></td></tr>
<tr><td>Answers fully faithful to their cited passages (both search modes)</td><td><strong>{pct(fully / n_rev)}</strong> (the rest: minor overstatement)</td></tr>
<tr><td>Invalid citations, all {len(all_rows)} evaluated answers</td><td><strong>{invalid}</strong> (checked in code)</td></tr>
<tr><td>Answers correct, default search (AI-graded)</td><td>{pct(single['correct']['mean'])}</td></tr>
<tr><td>Right passage in the top 10, hybrid search</td><td><strong>{pct(hybrid['recall@10'])}</strong> (vector-only: {pct(vector['recall@10'])})</td></tr>
<tr><td>Default search vs Deep search (agent), correct answers</td><td>{pct(single['correct']['mean'])} vs {pct(agent['correct']['mean'])}, at {cost['single search v4 (default)']['latency_s']:.0f} s vs {cost['agent v3 (shipped)']['latency_s']:.0f} s</td></tr>
</table></div>
<p class="hint" style="margin:8px 0 0">Method, raw results and every design decision:
<a href="{REPO}/docs/decisions/0017-agent-evaluation-results.md" target="_blank" rel="noopener">evaluation write-up</a> and <a href="{REPO}/docs/decisions/0019-single-search-default.md" target="_blank" rel="noopener">why single search is the default</a>.</p>
""".strip()
    OUT.write_text(json.dumps({"html": html, "numbers": {
        "reviewed": n_rev, "unsupported": unsupported, "fully_faithful": round(fully / n_rev, 3),
        "invalid_citations": invalid, "answers_evaluated": len(all_rows),
        "correct_single": single["correct"]["mean"], "correct_agent": agent["correct"]["mean"],
        "recall10_hybrid": round(hybrid["recall@10"], 3), "recall10_vector": round(vector["recall@10"], 3),
    }}, indent=1))
    print(f"wrote {OUT}")
    print(json.dumps(json.loads(OUT.read_text())["numbers"], indent=1))


if __name__ == "__main__":
    main()
