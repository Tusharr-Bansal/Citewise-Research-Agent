# 0005 — API key handling

**Date:** 2026-10-21 · **Status:** Accepted

## Decision

- The Gemini key lives only in a `.env` file (`GEMINI_API_KEY=...`), loaded into the environment at runtime.
- `.env` is in `.gitignore`. The repo ships `.env.example` with a placeholder so others know which variable to set.
- The key is never pasted into chat, printed in logs, or written into code. When checking the file, only a masked form (first 4 and last 4 characters) is displayed.
- In deployment, the key is set as the host's secret environment variable, not baked into the container image.

## Alternatives considered

- **Network secret attached by a proxy** (the key never enters the build machine at all). Better, but not available for this session type.

## Be ready to explain

- Why a leaked key in git history stays leaked even after you delete the file (history), and what to do (rotate the key immediately).
- The difference between config (fine in the repo) and secrets (never in the repo).
