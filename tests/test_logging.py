"""Render's internal health checks are hidden from the access log; external keep-alive pings are not."""
import logging

from citewise.app import HideInternalHealthChecks


def record(client: str, path: str) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                             (client, "GET", path, "1.1", 200), None)


f = HideInternalHealthChecks()


def test_internal_health_check_hidden():
    assert not f.filter(record("10.237.27.149:47256", "/api/ping"))   # real address from the Render log


def test_external_keepalive_ping_kept():
    assert f.filter(record("195.201.26.157:51234", "/api/ping"))      # a public address (e.g. cron-job.org)


def test_other_paths_always_kept():
    assert f.filter(record("10.237.27.149:47256", "/api/health"))
    assert f.filter(record("10.237.27.149:47256", "/"))
