-- Citewise schema. Idempotent: safe to run on every start; never drops user data.
CREATE EXTENSION IF NOT EXISTS vector;

-- A project is one literature collection (e.g. "MySteth 2.0").
-- Its id is an unguessable token: knowing the id is what grants access (docs/decisions/0014).
CREATE TABLE IF NOT EXISTS projects (
    id          text PRIMARY KEY,
    name        text NOT NULL,
    description text NOT NULL DEFAULT '',
    is_demo     boolean NOT NULL DEFAULT false,   -- the built-in demo is read-only
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now() -- bumped when papers change; invalidates search caches
);

CREATE TABLE IF NOT EXISTS papers (
    id          text PRIMARY KEY,                  -- citation key, e.g. guo2017_calibration
    project_id  text NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       text NOT NULL,
    authors     text NOT NULL DEFAULT '',
    year        int,
    url         text,
    filename    text,
    n_pages     int,
    n_chunks    int NOT NULL DEFAULT 0,
    status      text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'processing', 'ready', 'failed')),
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS papers_project_idx ON papers (project_id);

CREATE TABLE IF NOT EXISTS chunks (
    id          text PRIMARY KEY,                  -- "<paper id>:<index>", stable across rebuilds
    project_id  text NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    paper_id    text NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    chunk_index int  NOT NULL,
    page_start  int  NOT NULL,
    page_end    int  NOT NULL,
    n_tokens    int  NOT NULL,
    text        text NOT NULL,
    embedding   vector(384) NOT NULL,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED
);
-- Every search is scoped to one project. Vector search is exact within the project
-- (no HNSW index): an approximate index searched across ALL projects and filtered
-- afterwards can return too few or the wrong neighbours (docs/decisions/0014).
CREATE INDEX IF NOT EXISTS chunks_project_idx ON chunks (project_id);
CREATE INDEX IF NOT EXISTS chunks_paper_idx ON chunks (paper_id);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
