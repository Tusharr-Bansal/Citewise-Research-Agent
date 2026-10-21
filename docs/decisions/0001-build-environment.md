# 0001 — Where the code is built, run and delivered

**Date:** 2026-10-21 · **Status:** Accepted

## Context

The project is built by a coding agent (Claude) working in an isolated Linux cloud workspace, with Tushar's Windows folder `C:\TUSHAR\Agentic AI Project` linked as the delivery location. The two machines have different capabilities, checked on 2026-10-21:

| Capability | Cloud workspace | Linked folder (Linux VM on Tushar's machine) |
|---|---|---|
| Python | 3.13 | 3.10 |
| Postgres 16 | yes (+ pgvector installed via apt) | no |
| Docker | yes, but Docker Hub is blocked | no |
| Gemini API | yes (after allowlisting the domain) | no |
| Hugging Face | yes (after allowlisting) | no |
| RAM / CPUs | 7 GB / 2 | 3 GB / 2 |

Outbound network access is restricted by an account-level domain allowlist ("Package managers only" plus four domains Tushar added: `generativelanguage.googleapis.com`, `huggingface.co`, `*.huggingface.co`, `*.hf.co`). arXiv, Europe PMC, OpenAI and most hosting providers are not reachable.

## Decision

- **Build and run everything in the cloud workspace.** It has Postgres, pgvector and network access to the LLM.
- **Deliver to Tushar's folder at checkpoints.** The repo is copied to `C:\TUSHAR\Agentic AI Project\pcg-research-agent` after each working milestone.
- **GitHub becomes the source of truth once the repo exists there** (needed for deployment anyway).

## Alternatives considered

- **Build directly in the linked folder.** Rejected: it can't reach Gemini or run Postgres, so nothing could be tested there.
- **Run Postgres in Docker** (the usual way). Rejected for development because Docker Hub is blocked; a native Postgres 16 with the `postgresql-16-pgvector` apt package does the same job. Deployment will use a hosted Postgres, so this difference doesn't reach production.

## Consequences

- The workspace is ephemeral: it is reclaimed after inactivity. Anything not copied to the folder or pushed to GitHub can be lost, so checkpoints must be frequent.
- Paper PDFs can't be downloaded from the workspace (no arXiv/PMC access), so Tushar supplies them.

## Be ready to explain

- Why the dev database differs from production (native vs. hosted Postgres) and why that's acceptable here: same engine version family, same extension, schema created by the same migration script.
- What a domain allowlist is and why "package managers + four named domains" is safer than "all domains" (least privilege for an AI agent with a shell).

## Update (2026-10-22): local working copy

The workspace's shared output folder is a network-synced filesystem (rclone FUSE). SQLite, used for the LLM response cache, failed there with `attempt to write a readonly database` midway through a run, because SQLite's file locking doesn't work reliably on network filesystems. The working copy now lives on the workspace's local disk, and files are copied to the output folder only to hand them to Tushar's folder.
