# 0006 — Documentation lives in the repo as decision records

**Date:** 2026-10-21 · **Status:** Accepted

## Decision

Decisions are recorded as numbered Architecture Decision Records (ADRs) in `docs/decisions/`, one file per decision, never rewritten after the fact; a changed decision gets a new entry that supersedes the old one.

## Why

- They ship to GitHub next to the code, so a reviewer sees the reasoning, not just the result.
- Each entry has a "Be ready to explain" section, so the log doubles as interview preparation.
- Superseding instead of rewriting preserves *how* the thinking changed, which is often what interviewers ask about ("what did you try first, and why did you change it?").

## Alternatives considered

- A separate editable document outside the repo. Easier to comment on, but it drifts away from the code.
