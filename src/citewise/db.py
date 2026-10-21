"""Database connection helpers."""

from __future__ import annotations

from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector

from . import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(autocommit: bool = True) -> psycopg.Connection:
    conn = psycopg.connect(config.DATABASE_URL, autocommit=autocommit)
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        pass  # fresh database: the extension is created (and registered) by ensure_schema
    return conn


def ensure_schema(conn: psycopg.Connection) -> None:
    """Create tables if missing. Never drops anything."""
    try:
        conn.execute(SCHEMA_PATH.read_text())
    except psycopg.errors.InsufficientPrivilege as e:
        raise RuntimeError(
            "The database user can't enable pgvector. Run `CREATE EXTENSION vector;` once "
            "in the database (e.g. in Neon's SQL editor), then restart the app."
        ) from e
    register_vector(conn)  # the vector type may have just been created
