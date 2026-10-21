# 0002 — LLM provider: Gemini free tier, pinned to `gemini-3.5-flash-lite`

**Date:** 2026-10-21 · **Status:** Accepted

## Context

The agent needs an LLM for: drafting gold questions, rewriting search queries, writing cited answers, and judging faithfulness. Budget: free, or at most ~$15.

Options checked:
- **Claude API**: reachable from the workspace, but Tushar's $100 Claude credit is a *cloud-session* credit, which doesn't cover API-key calls. It would need separately purchased API credit.
- **Grok (xAI)**: not reachable from the workspace.
- **Gemini (Google AI Studio)**: free tier; reachable once `generativelanguage.googleapis.com` was allowlisted.

## Decision

Use **Gemini via the free tier**, with the model **pinned to an explicit version**: `gemini-3.5-flash-lite`.

## Evidence

A one-line test prompt ("Reply with exactly: OK") on 2026-10-21:

| Model name | Result |
|---|---|
| `gemini-2.5-flash-lite`, `gemini-2.5-flash` | 404: no longer available to new users |
| `gemini-flash-lite-latest` | OK — resolved to `gemini-3.5-flash-lite` |
| `gemini-3.5-flash-lite` | OK |
| `gemini-flash-latest`, `gemini-3.8-flash`, `gemini-3.1-flash-lite` | 503: "currently experiencing high demand" |

## Why pin instead of using `-latest`

`gemini-flash-lite-latest` is an alias that Google can repoint to a new model at any time. If that happens between two eval runs, the numbers change for reasons that have nothing to do with our code, and we can't tell. Pinning means a metric change is always caused by something we did. We record the `modelVersion` field returned with every response so this can be audited.

## Alternatives considered

- **Bigger Flash models** for better answers. Not rejected forever: they returned 503 during testing. The model name will be a config value, so a stronger model can be swapped in for the judge or the answerer and compared by eval.
- **Claude API.** Better tooling, but costs money here. The code will talk to the LLM through one thin interface so the provider can change without touching the agent logic.

## Consequences

- **Rate limits:** the free tier caps requests per minute and per day. The client needs throttling, retry with exponential backoff (for 429 and 503), and a response cache keyed on (model, prompt) so re-running an eval doesn't re-spend quota.
- **Data use:** on the free tier, Google may use prompts and responses to improve its products. Acceptable because the corpus is open-access papers; nothing private may be sent through this key.
- **Same family as judge and answerer:** an LLM judge tends to favour outputs from its own model family (self-preference bias). Tushar's human labels and the judge–human agreement (Cohen's kappa) are how this is measured rather than assumed away.

## Be ready to explain

- Model pinning vs. aliases, and why it matters for reproducible evals.
- Why retry with exponential backoff (and jitter) instead of immediate retry: immediate retries hammer an overloaded service and make the overload worse.
- Self-preference bias in LLM-as-judge, and how a human-labeled subset checks it.
