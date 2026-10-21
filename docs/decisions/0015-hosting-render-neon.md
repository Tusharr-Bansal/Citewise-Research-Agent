# 0015 — Hosting: Render (app) + Neon (Postgres), kept awake by an external ping

**Date:** 2026-10-22 · **Status:** Accepted (supersedes the Hugging Face plan in 0013)

## Context

Decision 0013 packaged a single container (Postgres inside) for a free Hugging Face Space. When creating the Space, the API returned **402 Payment Required**: "hosting Gradio and Docker Spaces on free cpu-basic requires a PRO subscription." Free tiers had changed. The app needs ~280 MB RAM measured (embedding model, BM25 index, FastAPI) plus Postgres with pgvector.

Options as of late Sept 2026 (from providers' own pages, collected by snapdeploy.dev):

| Option | Cost | Fit |
|---|---|---|
| HF Space PRO | $9/month | Easiest (already packaged) |
| Render free + Neon free | $0, no card | 512 MB, 0.1 CPU, sleeps after 15 min; Neon 1 GB storage, 100 CU-h/month |
| Azure for Students | $100 credit | More compute, more setup, credit runs out |
| Heroku via Student Pack | $13/month credit for 24 months | Needs pack verification |
| Koyeb / Fly.io / Cloud Run / Oracle | | Card or pre-authorisation required |

**Tushar chose Render + Neon**, with a timed request to keep Render awake.

## Decision

- **App on Render** (free web service, Docker, Singapore region), from `Dockerfile` + `render.yaml` (Blueprint; secrets entered in the dashboard, never in the repo).
- **Postgres on Neon** (free, Singapore, pgvector). Database outside the container means **uploaded projects persist** across Render restarts and sleeps; they're no longer temporary.
- **First start against an empty database:** the app creates the schema, then loads the demo project from `deploy/demo_data.sql.gz`, a **data-only** dump (tables are created by the app, so the dump needs no special privileges). Tested against an empty, non-superuser database: the demo loaded in 0.5 s, chunks byte-identical, keyword vectors regenerated.
- **Keep-alive:** an external cron (cron-job.org) calls **`/api/ping` every 10 minutes**.
  - `/api/ping` **never touches the database**. Neon suspends after 5 idle minutes and bills compute-hours while awake. A ping hitting the database every 10 minutes would keep it awake most of the month, spending the free 100 CU-hours on nothing.
  - 10 minutes, not 14.5: cron schedules drift, and 14.5 can slip past Render's 15-minute cutoff.
  - Budget: 24/7 ≈ 744 of Render's 750 free instance-hours per month, enough for exactly one always-on service per account.
- **Small-host tuning:** ONNX Runtime limited to 1 thread (`CITEWISE_EMBED_THREADS=1`) on a 0.1-CPU host; one Uvicorn worker (in-memory indexes and rate limits); the Neon **direct** (unpooled) connection string, because psycopg's automatic prepared statements don't survive PgBouncer's transaction pooling.

## Consequences

- **Uploads are slow** on 0.1 CPU: embedding that took ~0.6 s per chunk on 2 cores will take several seconds per chunk, so minutes per paper. The UI says so. Questions are fine (one short query embedding each).
- **Render may restart free services at any time;** in-memory rate limits and BM25 caches reset (rebuilt on demand).
- **The Hugging Face container files were removed;** 0013's guardrails, local tests and UI checks still apply.
- **Neon cold start** adds ~1 s to the first request after it has slept.

## Be ready to explain

- Why the keep-alive must not touch the database (two different idle meters: Render's sleep vs Neon's compute-hours).
- Connection pooling (PgBouncer transaction mode) vs prepared statements.
- How the app bootstraps an empty database safely and idempotently.
- That "free" infrastructure changed underneath you mid-project, and how you re-planned (measure memory, compare options, write it down).

## Addendum (same day): the free tier's daily quota

**What happened:** the re-run evaluation stopped at 83 of 116 answers with `429 RESOURCE_EXHAUSTED`, quota id `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, limit **500 requests/day** for `gemini-3.5-flash-lite`, resetting in ~10 h (midnight Pacific).

**Two problems this exposed, both fixed:**
1. **Retrying a daily quota is pointless.** The retry loop treated every 429 alike, so a visitor waited ~30 s through six retries for "the model is busy, try again in a minute", which was false. Now `llm.py` recognises a per-day quota (a 429 whose quota id contains `PerDay`), raises `DailyQuotaExhausted` immediately, and the app answers **HTTP 429 in under a second**: "Today's free AI quota is used up. It resets at midnight Pacific time." Per-minute 429s still retry. Tests: `tests/test_llm.py` (uses the real quota id).
2. **The global cap was above what the quota allows.** 300 questions/day × ~3 LLM calls each ≈ 900 calls > 500. Lowered to **120 questions/day** (~360 calls), leaving room for upload metadata calls (one per paper). Override with `CITEWISE_GLOBAL_PER_DAY`.

**Consequence to remember:** the deployed app and the evaluation use the same API key, so they share one daily budget. Run evaluations before sharing the link widely, or on days the demo is quiet.

**Be ready to explain:** rate limit vs quota; why some errors should *not* be retried (retry budget, user-facing latency, honest error messages); capacity planning from calls-per-request.

## Addendum: `pdftotext` was missing from the deploy image

While writing the README's local-setup steps, I noticed the new Dockerfile installed only `postgresql-client`. Every upload calls the `pdftotext` binary (decision 0007), so **every upload would have failed in production** while the demo (pre-ingested) worked, which makes it easy to miss. Fixed: the image now installs `poppler-utils`. The image couldn't be built in the development workspace (Docker Hub is outside its network allowlist), so the check is: Render's first build succeeds, then one PDF is uploaded on the live site and reaches "ready".

**Lesson:** a smoke test of the deployed app must exercise every external binary, not just the happy path that pre-loaded data allows.
