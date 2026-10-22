# 0019 — Single search is the default; the agent becomes "Deep search"; hedge-keeping answer prompt; the corpus is complete

**Date:** 2026-10-22 · **Status:** Accepted. Amends 0012 (the agent is no longer the default path) and 0015 (the daily budget is counted in LLM calls).

## Context

Decision 0017 measured the multi-step agent against a single hybrid search on the same 45 single-passage questions:

- **Correct answers:** 0.87 for both.
- **Evidence:** the agent's +7 points was not distinguishable from noise (95% CI −4 to +18).
- **Cost:** the agent used 3 LLM calls and ~8 s per question, against 1 call and ~4 s.
- **Faithfulness review:** single search was at least as good (fully faithful 90% vs 77%, on 30 answers each; a small sample).

On the free tier the binding limit is the answer model's daily quota (500 requests). An agent question spends three of them.

The same review showed that **every** faithfulness problem was an overstatement:

- a dropped hedge ("may" became "primarily");
- a widened quantifier ("some" models became all models);
- a detail the passage didn't state (a word like "standard", a purpose like "for pretraining").

None was an invented fact.

Three papers of the 29-paper review (0009) were still missing from the demo: Wu 2024, Alotaibi 2025 and Rodrigues 2026.

## Decisions

### 1. Single search is the default; the agent is opt-in

`POST /api/projects/{id}/ask` takes `mode: "fast" | "deep"`, default `"fast"`:

- **fast** → `agent.single_shot`: one hybrid search over the question as typed, then one answer call.
- **deep** → `agent.run`: the plan → search → check → answer loop (0012, with the anchor from 0016).

The web page shows a **Deep search** checkbox, off by default. The response includes `mode`, and the trace panel reads "How it searched" in both modes.

**Rejected:** running the agent only when the single search looks weak. That needs a reliable signal for "weak". The check step is that signal, and it costs a call, so it brings back most of the cost it was meant to save. It isn't worth it at this corpus size; revisit if a larger corpus shows the agent pulling ahead.

### 2. The daily budget is counted in LLM calls, not questions

The 0015 cap of 120 questions/day assumed ~3 calls per question. It is now:

- **400 calls/day** (`CITEWISE_GLOBAL_CALLS_PER_DAY`); a fast question costs 1, a deep one 3 (`CALLS_CHARGED`);
- the remaining ~100 of the 500 are left for upload metadata extraction.

That means up to ~400 fast questions a day instead of 120. The per-IP limits (5/minute, 30/day) still count questions.

`RateLimiter.take` now charges a rule a given number of units and is **all-or-nothing** across rules. A request refused by the per-minute rule doesn't use up the global budget.

### 3. The answer prompt keeps the source's strength

Added to `ANSWER_PROMPT` (used by both modes):

> Keep the strength of what the passages say. Copy their hedges and quantifiers ("may", "likely", "some", "primarily") instead of strengthening them, and do not add details (a number, scope, dataset, purpose) that the cited passage does not state. Cite each passage only for what it actually says.

### 4. The three missing papers are added: the demo now holds all 29

Their PDFs are added to `papers/` (git-ignored; see 0009 for why) and listed in `papers/manifest.json`. They were ingested through the same pipeline as uploads.

| Paper | Chunks |
|---|---|
| Wu et al. 2024, murmur detection and recording quality (MDPI *Applied Sciences*) | 57 |
| Alotaibi et al. 2025, Whisper for heart sounds (*Connection Science*) | 21 |
| Rodrigues et al. 2026, poor-quality recording detection (SSRN preprint) | 26 |

Total: 1,089 chunks (was 985).

**Nothing about the original 26 papers changed.** The old and new demo dumps were compared: all 985 old chunks are present, with identical text and identical embeddings. Chunking and embedding are per paper, so a new paper can only change *ranking*, through BM25's corpus statistics and through competing for the top-k.

**Known residue: the Rodrigues watermark.** The SSRN PDF has a rotated side text ("Preprint not peer reviewed") that pdftotext extracts as stray two- or three-letter fragments ("ev ie", "we d"). The repeated footer line is removed by the header filter (0007); the fragments are not. 17 of its 26 chunks contain a few such tokens. They are harmless for search (they don't match real queries) and visible only in that paper's passages. Not worth a special case.

### 5. The demo data is versioned

Before this change, the demo was loaded only when the database had no demo project, so the live site would have kept the 26-paper demo forever. Now:

- `projects.data_version` holds the first 16 hex characters of the dump file's sha256.
- On start, if the stored version differs from the file's, the demo project is replaced (`DELETE` of the demo project + the dump + the version `UPDATE`) in **one psql transaction** (`--single-transaction`, `ON_ERROR_STOP=1`).
- **User projects are never touched.** The `DELETE` names the demo project's id, and its papers and chunks cascade.

The statements name `public.projects` explicitly, because pg_dump output clears `search_path` and an unqualified name fails after it. The first test run caught this.

Tested on a fresh database:

| Case | Result |
|---|---|
| Empty database | loaded: 29 papers, 1,089 chunks, version set |
| Restart, same dump | no reload |
| Stored version outdated, plus a user project | demo replaced; the user project survives |
| Broken dump file | startup fails, and the transaction rollback leaves the existing 1,089 demo chunks intact |

**The export script now refuses broken exports.** `deploy/export_demo.sh` aborts if the dump would hold fewer than 100 chunks, and writes to a temporary file that is renamed only on success. A run without the needed privileges had silently written a 4 KB dump with no data in it. It must run as the database owner (see the script).

## Evidence: the new default, measured

Single search with the new prompt was run on the 29-paper demo, on the same test set as 0017 (`eval/results/agent_eval_v4_fast.json`; `eval/compare_runs.py`). It is compared with single search from the v3 run (old prompt, 26 papers):

| Single-passage questions | v3 single search | **v4 default** | paired difference [95% CI] |
|---|---|---|---|
| Evidence reached the answer | 0.82 (45) | 0.80 (45) | −0.02 [−0.07, 0.00] |
| Correct | 0.87 (45) | 0.91 (44) | |
| Credit (partial = ½) | 0.90 (45) | 0.93 (44) | +0.01 [−0.06, +0.08] |
| No unsupported claim (judge, all questions) | 1.00 (58) | 0.98 (56) | −0.02 [−0.05, 0.00] |
| Invalid citations | 0 | 0 | |
| LLM calls / latency (median) | 1 / 4.0 s | 1 / 4.0 s | |

(The judge failed on 2 questions in v4, hence n = 44 and 56. Two corpus versions are mixed in this comparison: the prompt and the three new papers changed together.)

**Nothing got worse beyond noise, and nothing got better beyond noise.** The per-question changes:

- **One question lost its evidence because of the new papers.** For the EHST hyperparameter question, the right passage had been 14th of the 14 shown to the answer step. Two passages from the new papers outranked it, so the answer now says the information isn't in the passages. That's an honest abstention, and the expected cost of a larger corpus at a fixed top-k.
- **Two Festag questions improved** (partial → correct, incorrect → correct).
- **The Noponen sensitivity/specificity answer** went from supported to partly. See below.

### Faithfulness on the reviewed questions (development-set check)

The three single-search answers marked *Partly* in the 0017 review were compared before and after the prompt change, together with any reviewed answer whose judge verdict changed. These are the questions that motivated the prompt, so this is a check on the development set, not a new measurement. The 83% / 0-unsupported figures in 0017 still describe the reviewed (earlier) answers.

Reviewed by Tushar against the cited passages (2026-10-22):

| Question (single search) | Review, old answer | Problem then | New answer | Review, new answer |
|---|---|---|---|---|
| Niizumi: ICBHI2017 vs SPRS | Partly | "may" → "primarily"; "some" models → all | keeps "may" and "likely"; the SOTA overclaim is gone | **Supported** |
| Despotovic: Open Heart collection | Partly | attributed the wrong purposes to the short recordings and to concatenation | states the passage's purposes (pretraining data; concatenation before processing) | **Supported** |
| Khan: "standard" HMM segmentation | Partly | "standard" and the four states weren't in the passage | says the passages don't describe a standard method; cites only what S13 says | **Supported** |
| Noponen: duration/frequency rule | Supported | — | **swapped the numbers**: "90% sensitivity and 91% specificity" vs the paper's 90% specificity, 91% sensitivity | **Partly** |

**All three hedge/scope problems were fixed, and one new error appeared: a swapped pair of numbers.** That's not the kind of error the prompt targets. Citation checks in code can't catch it (the citation is valid). The AI judge did catch this one. On these 4 answers it's 3 better and 1 worse, too few to claim a faithfulness rate. The rate stays the 0017 figure until a fresh blind review of the new answers is done.

## Consequences

- About 3× as many questions fit in the free daily quota, and the default answer comes in ~4 s.
- The agent's code, tests and evaluation stay. Deep search is one checkbox away, and it is the right tool if a larger corpus starts to need multi-step retrieval.
- Every new demo dump redeploys itself. The export guard and the single transaction make a bad dump fail loudly, not quietly empty the demo.
- The README, the study guide and the demo's results panel (`eval/publish_summary.py`) now report the default mode's numbers, and the 29-paper retrieval rerun: hybrid recall@10 is unchanged at **0.78**, MRR 0.54 → 0.53, vector-only 0.64. The three new papers didn't dilute retrieval of the original questions' evidence within the top 10.

## Be ready to explain

- Why the cheaper system became the default when the evidence couldn't separate the two (equal quality, so cost decides). And why "the agent is better" would need a bigger test set or a harder corpus to show.
- Why the budget counts LLM calls, and why multi-rule rate limiting must be all-or-nothing.
- How you proved that adding papers didn't change the old ones (chunk text + embedding comparison), and the one regression it still caused (top-k competition).
- Why the demo reload runs in a single transaction, and the `search_path` bug the test caught.
- Why a prompt fix is checked on the answers that motivated it, without claiming a new faithfulness number.
