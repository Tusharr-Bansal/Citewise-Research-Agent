"""A connection dropped by the server (Neon's idle suspend) is replaced instead of failing every question."""
import psycopg

import citewise.retrieval as retrieval


class FakeConn:
    def __init__(self, dead=False):
        self.dead, self.closed, self.queries = dead, False, []

    def execute(self, sql, params=()):
        if self.dead or self.closed:
            raise psycopg.OperationalError("terminating connection due to administrator command")
        self.queries.append(sql)

    def close(self):
        self.closed = True


def test_dropped_connection_is_replaced(monkeypatch):
    made = iter([FakeConn(dead=True), FakeConn()])
    monkeypatch.setattr(retrieval.db, "connect", lambda: next(made))
    r = retrieval.Retriever()
    first = r.conn
    r.ensure_connection()
    assert first.closed and r.conn is not first
    r.conn.execute("SELECT 2")
    assert r.conn.queries == ["SELECT 2"]


def test_healthy_connection_is_kept(monkeypatch):
    made = iter([FakeConn()])
    monkeypatch.setattr(retrieval.db, "connect", lambda: next(made))
    r = retrieval.Retriever()
    first = r.conn
    r.ensure_connection()
    assert r.conn is first and first.queries == ["SELECT 1"]
