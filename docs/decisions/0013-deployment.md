# 0013 — Deployment: one Docker container on Hugging Face Spaces

**Date:** 2026-10-22 · **Status:** Hosting superseded by [0015](0015-hosting-render-neon.md) (HF free Docker Spaces now need PRO); the guardrails here still apply

## Context

The demo needs a public link that works when a recruiter clicks it, at no cost. The app needs Postgres with pgvector, the embedding model (67 MB), ~1 GB of RAM for the model plus BM25 index, and outbound access to the Gemini API.

## Decision

A single Docker container on a **Hugging Face Space** (free CPU tier: 2 vCPU, 16 GB RAM):

- **Base image** `pgvector/pgvector:0.8.0-pg16` (official Postgres 16 with pgvector), plus Python.
- **Database inside the container.** At startup `deploy/start.sh` initialises Postgres, listening on localhost only, loads the corpus from `deploy/corpus.sql.gz` (a 2.3 MB `pg_dump` of the dev database: papers, chunks, embeddings and indexes), then starts the API.
- **App:** FastAPI (`src/pcg_agent/app.py`) serving one static page plus `/api/ask`, `/api/papers`, `/api/health` and `/api/eval`.
- **Secret:** `GEMINI_API_KEY` set as a Space secret, never in the image or repo.

## Guardrails for a public demo on a free-tier key

| Risk | Control |
|---|---|
| Strangers exhausting the free API quota | Per-visitor limits (5/min, 30/day) and a **global cap of 300 questions/day**; all configurable by environment variable |
| Parallel bursts triggering provider 429s | One agent run at a time (a lock); the free tier can't absorb parallel calls anyway |
| Huge or abusive inputs | 3–500 character limit, validated before any work |
| Prompt injection leading to harmful actions | The agent has **no write tools**: it can only search a fixed, read-only corpus. The worst case is a bad answer, not a bad action (OWASP LLM06, "excessive agency") |
| Database exposure | Postgres listens on localhost only, with no external port |
| Provider overload | Retries with backoff in the LLM client; afterwards the user gets "the model is busy, try again in a minute", not a stack trace |

## Evidence (local test, 2026-10-22)

The startup script was run as a non-root user against an empty data directory, as the container would:
- **Found a real bug:** Postgres tried to create its socket in `/var/run/postgresql`, which a non-root user can't write. Fixed by `unix_socket_directories = '/tmp'` and connecting over localhost. Hugging Face runs containers as uid 1000, so this would have failed in production.
- **After the fix:** the corpus loaded (985 chunks), `/api/health` was OK, an invalid API key produced a clean error message, and the 6th request within a minute got HTTP 429.
- **UI** checked at 1280 px (light) and 390 px (dark): no horizontal overflow, citations link to their passages.

The Docker image itself couldn't be built in the development workspace (Docker Hub isn't reachable from there); the first real build happens on Hugging Face.

## Alternatives considered

- **Render / Railway + a hosted Postgres (Neon or Supabase).** More "production-shaped" (managed database, separate tiers), but needs two more accounts, and free web services there have 512 MB RAM, too little for the embedding model plus app. Free databases also pause when idle.
- **Gradio or Streamlit UI.** Faster to write, but a plain HTML page gives full control over citation display and the search-trace panel, and loads faster.
- **Pre-computing answers.** No API cost, but then it's not a live system.

## Consequences

- **Cold starts:** free Spaces sleep after ~48 h without visitors; the first visit then takes about 1–2 minutes to wake. The README should say so.
- **In-memory rate limits reset on restart.** That's acceptable for a demo; a production system would keep counters in Redis or the database.
- **Updating the corpus** means re-running ingestion locally, re-exporting the dump, and pushing.

## Be ready to explain

- Why the database lives inside the container here, and when you'd split it out (multiple app replicas, data that changes at runtime, backups).
- Each guardrail above, especially why "no write tools" is the strongest defence against prompt injection in this design.
- How you'd add observability in production (structured traces per request are already produced; they'd go to Langfuse or an OpenTelemetry backend).
