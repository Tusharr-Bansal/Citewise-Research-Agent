"""Expired-project cleanup runs at most once per interval and never breaks a request."""
import citewise.app as app


class FakeConn:
    def __init__(self, fail=False):
        self.sql, self.fail = [], fail

    def execute(self, sql, params=()):
        if self.fail:
            raise RuntimeError("database down")
        self.sql.append((sql, params))
        return type("Cur", (), {"rowcount": 2})()


def test_cleanup_deletes_only_non_demo_projects_past_ttl():
    c = FakeConn()
    assert app.delete_expired_projects(c) == 2
    sql, params = c.sql[0]
    assert "NOT is_demo" in sql and "created_at <" in sql and params == (app.PROJECT_TTL_DAYS,)


def test_maybe_cleanup_runs_at_most_once_per_interval():
    app._last_cleanup = float("-inf")  # never run
    c = FakeConn()
    app.maybe_cleanup(c)
    app.maybe_cleanup(c)              # immediately again: skipped
    assert len(c.sql) == 1


def test_cleanup_failure_does_not_raise():
    app._last_cleanup = float("-inf")
    app.maybe_cleanup(FakeConn(fail=True))   # must not raise into the request
